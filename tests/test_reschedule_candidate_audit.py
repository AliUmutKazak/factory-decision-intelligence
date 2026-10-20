import sqlite3

import pandas as pd

from src.contracts.schemas import RescheduleTriggerEvent
from src.scheduling.maintenance import MaintenanceWindow
from src.scheduling.reschedule_candidate_audit import audit_reschedule_candidate as _raw_audit


def _calendar_connection(variable_day=None):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE machines (machine_id TEXT PRIMARY KEY, max_daily_hours REAL)")
    conn.execute(
        "CREATE TABLE machine_capacity_plan (run_id TEXT, period_week INTEGER, machine_id TEXT, overtime_hours REAL)"
    )
    conn.execute("INSERT INTO machine_capacity_plan VALUES ('BASE', 1, 'M01', 0)")
    conn.execute(
        "CREATE TABLE sku_production_plan (run_id TEXT, period_week INTEGER, product_id TEXT, planned_units INTEGER)"
    )
    conn.execute("INSERT INTO sku_production_plan VALUES ('BASE', 1, 'P01', 75)")
    conn.execute(
        "CREATE TABLE routing (product_id TEXT, operation_seq INTEGER, machine_id TEXT, processing_time_min REAL)"
    )
    conn.execute("INSERT INTO routing VALUES ('P01', 1, 'M01', 40)")
    conn.execute(
        "CREATE TABLE changeover_matrix (machine_id TEXT, from_product TEXT, to_product TEXT, setup_time_min REAL)"
    )
    conn.execute("INSERT INTO changeover_matrix VALUES ('ALL', 'P01', 'P01', 0)")
    conn.execute(
        "CREATE TABLE machine_calendar (machine_id TEXT, day_of_week INTEGER, shift_id TEXT, "
        "start_minute INTEGER, end_minute INTEGER, available_hours REAL, exception_type TEXT, is_available INTEGER)"
    )
    conn.execute("INSERT INTO machines VALUES ('M01', 16)")
    for day in range(7):
        changed = day == variable_day
        conn.execute(
            "INSERT INTO machine_calendar VALUES ('M01', ?, 'SHIFT_REGULAR', 480, ?, ?, ?, 1)",
            (day, 1380 if changed else 1440, 15 if changed else 16, "EXCEPTION" if changed else "REGULAR"),
        )
    return conn


def audit_reschedule_candidate(conn, baseline, candidate, trigger, **kwargs):
    kwargs.setdefault("baseline_run_id", "BASE")
    return _raw_audit(conn, baseline, candidate, trigger, **kwargs)


def _schedules():
    baseline = pd.DataFrame(
        [
            {
                "task_id": "FROZEN",
                "lot_id": "LOT-FROZEN",
                "product_id": "P01",
                "machine_id": "M01",
                "operation_seq": 1,
                "start_min": 500,
                "end_min": 540,
                "duration_min": 40,
                "release_time_min": 0,
                "setup_before_min": 0,
                "setup_start_min": 500,
                "setup_end_min": 500,
                "schedule_state": "FREE",
                "freeze_until_min": 0,
                "execution_status": "SCHEDULED",
            },
            {
                "task_id": "FLEX",
                "lot_id": "LOT-FLEX",
                "product_id": "P01",
                "machine_id": "M01",
                "operation_seq": 1,
                "start_min": 600,
                "end_min": 640,
                "duration_min": 40,
                "release_time_min": 0,
                "setup_before_min": 0,
                "setup_start_min": 600,
                "setup_end_min": 600,
                "schedule_state": "FREE",
                "freeze_until_min": 0,
                "execution_status": "SCHEDULED",
            },
            {
                "task_id": "OUTSIDE",
                "lot_id": "LOT-OUTSIDE",
                "product_id": "P01",
                "machine_id": "M01",
                "operation_seq": 1,
                "start_min": 900,
                "end_min": 940,
                "duration_min": 40,
                "release_time_min": 0,
                "setup_before_min": 0,
                "setup_start_min": 900,
                "setup_end_min": 900,
                "schedule_state": "FREE",
                "freeze_until_min": 0,
                "execution_status": "SCHEDULED",
            },
        ]
    )
    baseline["parent_lot_id"] = baseline["lot_id"]
    baseline["sub_lot_index"] = 1
    baseline["batch_count"] = 1
    baseline["batch_size_units"] = 25
    baseline["production_units"] = 25
    baseline["due_date_min"] = 10080
    baseline["priority_weight"] = 1
    candidate = baseline.copy()
    candidate.loc[candidate.task_id == "FROZEN", "schedule_state"] = "FROZEN"
    candidate.loc[candidate.task_id == "FROZEN", "freeze_until_min"] = 540
    candidate.loc[candidate.task_id == "FLEX", "schedule_state"] = "FLEXIBLE"
    candidate.loc[candidate.task_id == "FLEX", "start_min"] = 580
    candidate.loc[candidate.task_id == "FLEX", "end_min"] = 620
    candidate.loc[candidate.task_id == "FLEX", "setup_start_min"] = 580
    candidate.loc[candidate.task_id == "FLEX", "setup_end_min"] = 580
    return baseline, candidate


def _trigger():
    return RescheduleTriggerEvent(
        event_id="AUDIT-1",
        current_time_min=480,
        freeze_horizon_min=60,
        flexible_horizon_min=300,
        max_flexible_shift_min=30,
    )


def test_independent_audit_accepts_frozen_and_bounded_flexible_tasks():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert result["status"] == "ACCEPTED"
    assert result["task_count"] == 3


def test_independent_audit_rejects_frozen_position_and_flexible_window_changes():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        candidate.loc[candidate.task_id == "FROZEN", "start_min"] = 510
        candidate.loc[candidate.task_id == "FLEX", "start_min"] = 700
        candidate.loc[candidate.task_id == "FLEX", "end_min"] = 740
        candidate.loc[candidate.task_id == "OUTSIDE", "machine_id"] = "M02"
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert result["status"] == "REJECTED"
    assert "FROZEN_POSITION_CHANGED" in codes
    assert "FLEXIBLE_START_OUT_OF_BOUNDS" in codes
    assert "ROUTING_CHANGED" in codes


def test_independent_audit_rejects_variable_per_day_calendar_until_supported():
    conn = _calendar_connection(variable_day=2)
    try:
        baseline, candidate = _schedules()
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert result["status"] == "REJECTED"
    assert any(item["code"] in {"UNSUPPORTED_DAILY_CALENDAR", "VARIABLE_DAILY_CALENDAR"} for item in result["issues"])


def test_independent_audit_rejects_sunday_hours_that_change_model_daily_average():
    conn = _calendar_connection(variable_day=6)
    try:
        baseline, candidate = _schedules()
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert result["status"] == "REJECTED"
    assert any(item["code"] == "SUNDAY_HOURS_AFFECT_DAILY_AVERAGE" for item in result["issues"])


def test_independent_audit_rejects_machine_overlap_and_invalid_setup():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        candidate.loc[candidate.task_id == "OUTSIDE", ["start_min", "end_min", "setup_start_min", "setup_end_min"]] = [
            530,
            570,
            530,
            530,
        ]
        candidate.loc[candidate.task_id == "FLEX", "setup_before_min"] = 10
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert "MACHINE_OCCUPANCY_OVERLAP" in codes
    assert "INVALID_SETUP_INTERVAL" in codes


def test_independent_audit_rejects_route_precedence_and_input_change():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        baseline.loc[baseline.task_id == "FLEX", ["lot_id", "operation_seq", "machine_id"]] = ["LOT-FROZEN", 2, "M02"]
        candidate.loc[candidate.task_id == "FLEX", ["lot_id", "operation_seq", "machine_id"]] = ["LOT-FROZEN", 2, "M02"]
        candidate.loc[candidate.task_id == "FLEX", ["start_min", "end_min", "setup_start_min", "setup_end_min"]] = [
            530,
            570,
            530,
            530,
        ]
        candidate.loc[candidate.task_id == "OUTSIDE", "product_id"] = "P02"
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert "ROUTE_PRECEDENCE" in codes
    assert "TASK_INPUT_CHANGED" in codes


def test_independent_audit_rejects_active_maintenance_during_work():
    conn = _calendar_connection()
    try:
        conn.execute(
            "CREATE TABLE machine_maintenance (machine_id TEXT, start_min INTEGER, end_min INTEGER, is_active INTEGER)"
        )
        conn.executemany(
            "INSERT INTO machine_maintenance VALUES ('M01', ?, ?, ?)",
            [(585, 590, 1), (905, 915, 0)],
        )
        baseline, candidate = _schedules()
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert result["status"] == "REJECTED"
    assert any(item["code"] == "MAINTENANCE_OVERLAP" and "FLEX" in item["detail"] for item in result["issues"])
    assert not any("OUTSIDE" in item["detail"] for item in result["issues"])


def test_independent_audit_checks_setup_against_event_outage():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        candidate.loc[candidate.task_id == "OUTSIDE", "setup_before_min"] = 10
        candidate.loc[candidate.task_id == "OUTSIDE", "setup_start_min"] = 890
        result = audit_reschedule_candidate(
            conn,
            baseline,
            candidate,
            _trigger(),
            maintenance_overrides=[MaintenanceWindow("M01", 895, 900, "RESCHEDULE_DELAY")],
        )
    finally:
        conn.close()
    assert result["status"] == "REJECTED"
    assert any(item["code"] == "MAINTENANCE_OVERLAP" and "OUTSIDE" in item["detail"] for item in result["issues"])


def test_independent_audit_accepts_boundary_and_overlapping_closed_windows():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        result = audit_reschedule_candidate(
            conn,
            baseline,
            candidate,
            _trigger(),
            maintenance_overrides=[
                MaintenanceWindow("M01", 620, 650),
                MaintenanceWindow("M01", 630, 660),
            ],
        )
    finally:
        conn.close()
    assert result["status"] == "ACCEPTED"


def _mixed_product_setup_case(conn):
    baseline, candidate = _schedules()
    for frame in (baseline, candidate):
        frame.loc[frame.task_id == "FLEX", "product_id"] = "P02"
    conn.execute("UPDATE sku_production_plan SET planned_units = 50 WHERE product_id = 'P01'")
    conn.execute("INSERT INTO sku_production_plan VALUES ('BASE', 1, 'P02', 25)")
    conn.execute("INSERT INTO routing VALUES ('P02', 1, 'M01', 40)")
    conn.executemany(
        "INSERT INTO changeover_matrix VALUES (?, ?, ?, ?)",
        [
            ("M01", "P01", "P02", 17),
            ("ALL", "P01", "P02", 12),
            ("ALL", "P02", "P01", 7),
        ],
    )
    conn.execute("CREATE TABLE machine_state (machine_id TEXT, last_product_id TEXT)")
    conn.execute("INSERT INTO machine_state VALUES ('M01', 'P01')")
    conn.execute("CREATE TABLE machine_state_snapshot (run_id TEXT, machine_id TEXT, last_product_id TEXT)")
    conn.execute("INSERT INTO machine_state_snapshot VALUES ('BASE', 'M01', 'P02')")
    for task_id, minutes in (("FROZEN", 7), ("FLEX", 17), ("OUTSIDE", 7)):
        mask = candidate.task_id == task_id
        candidate.loc[mask, "setup_before_min"] = minutes
        candidate.loc[mask, "setup_start_min"] = candidate.loc[mask, "start_min"] - minutes
    return baseline, candidate


def test_independent_audit_accepts_snapshot_state_and_machine_override():
    conn = _calendar_connection()
    try:
        baseline, candidate = _mixed_product_setup_case(conn)
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger(), baseline_run_id="BASE")
    finally:
        conn.close()
    assert result["status"] == "ACCEPTED", result["issues"]


def test_independent_audit_rejects_self_consistent_but_wrong_changeover():
    conn = _calendar_connection()
    try:
        baseline, candidate = _mixed_product_setup_case(conn)
        candidate.loc[candidate.task_id == "FLEX", "setup_before_min"] = 12
        candidate.loc[candidate.task_id == "FLEX", "setup_start_min"] = 568
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger(), baseline_run_id="BASE")
    finally:
        conn.close()
    assert result["status"] == "REJECTED"
    assert any(item["code"] == "SETUP_TRANSITION_MISMATCH" and "FLEX" in item["detail"] for item in result["issues"])
    assert not any(item["code"] == "INVALID_SETUP_INTERVAL" for item in result["issues"])


def test_independent_audit_rejects_missing_or_invalid_changeover_source():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        conn.execute("INSERT INTO changeover_matrix VALUES ('ALL', 'P02', 'P01', -5)")
        invalid = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
        conn.execute("DROP TABLE changeover_matrix")
        missing = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert any(item["code"] == "INVALID_CHANGEOVER_ROW" for item in invalid["issues"])
    assert any(item["code"] == "MISSING_CHANGEOVER_MATRIX" for item in missing["issues"])


def test_independent_audit_does_not_treat_another_machine_rule_as_global():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        conn.execute("DELETE FROM changeover_matrix")
        conn.execute("INSERT INTO changeover_matrix VALUES ('M99', 'P01', 'P01', 99)")
        conn.execute("INSERT INTO changeover_matrix VALUES ('ALL', 'P01', 'P01', 0)")
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert result["status"] == "ACCEPTED", result["issues"]


def _move_outside_to_day(baseline, candidate, day, minute, duration=40, task_id="OUTSIDE"):
    for frame in (baseline, candidate):
        mask = frame.task_id == task_id
        start = day * 1440 + minute
        frame.loc[mask, ["start_min", "end_min", "duration_min", "setup_start_min", "setup_end_min"]] = [
            start,
            start + duration,
            duration,
            start,
            start,
        ]


def test_independent_audit_rejects_sunday_and_second_week_night():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        _move_outside_to_day(baseline, candidate, 6, 600)
        sunday = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
        _move_outside_to_day(baseline, candidate, 7, 100)
        week_two = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert "SUNDAY_CLOSED" in {item["code"] for item in sunday["issues"]}
    assert "WEEK2_OVERTIME" in {item["code"] for item in week_two["issues"]}


def test_independent_audit_recounts_week_one_setup_and_work_against_budget():
    conn = _calendar_connection()
    try:
        conn.execute("UPDATE machine_capacity_plan SET overtime_hours = 0.5")
        baseline, candidate = _schedules()
        _move_outside_to_day(baseline, candidate, 1, 0)
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert "OT_BUDGET_EXCEEDED" in {item["code"] for item in result["issues"]}


def test_independent_audit_counts_setup_before_regular_shift_as_overtime():
    conn = _calendar_connection()
    try:
        baseline, candidate = _mixed_product_setup_case(conn)
        _move_outside_to_day(baseline, candidate, 1, 480)
        mask = candidate.task_id == "OUTSIDE"
        candidate.loc[mask, "setup_before_min"] = 7
        candidate.loc[mask, "setup_start_min"] = 1440 + 473
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger(), baseline_run_id="BASE")
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert "OT_BUDGET_EXCEEDED" in codes
    assert "SETUP_TRANSITION_MISMATCH" not in codes


def test_independent_audit_enforces_count_of_open_ot_nights():
    conn = _calendar_connection()
    try:
        conn.execute("UPDATE machine_capacity_plan SET overtime_hours = 0.5")
        baseline, candidate = _schedules()
        _move_outside_to_day(baseline, candidate, 1, 10, duration=10)
        extra_base = baseline.loc[baseline.task_id == "OUTSIDE"].copy()
        extra_candidate = candidate.loc[candidate.task_id == "OUTSIDE"].copy()
        extra_base.loc[:, ["task_id", "lot_id"]] = ["EXTRA", "LOT-EXTRA"]
        extra_candidate.loc[:, ["task_id", "lot_id"]] = ["EXTRA", "LOT-EXTRA"]
        _move_outside_to_day(extra_base, extra_candidate, 2, 10, duration=10, task_id="EXTRA")
        baseline = pd.concat([baseline, extra_base], ignore_index=True)
        candidate = pd.concat([candidate, extra_candidate], ignore_index=True)
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert "OT_WINDOW_COUNT" in codes
    assert "OT_BUDGET_EXCEEDED" not in codes


def test_independent_audit_rejects_missing_baseline_or_ot_authorization():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        missing_run = _raw_audit(conn, baseline, candidate, _trigger())
        conn.execute("DELETE FROM machine_capacity_plan")
        conn.execute("INSERT INTO machine_capacity_plan VALUES ('OTHER', 1, 'M01', 48)")
        missing_budget = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert "MISSING_BASELINE_RUN_ID" in {item["code"] for item in missing_run["issues"]}
    assert "MISSING_OT_BUDGET" in {item["code"] for item in missing_budget["issues"]}


def test_independent_audit_rejects_candidate_quantity_and_order_input_change():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        candidate.loc[candidate.task_id == "OUTSIDE", ["batch_count", "production_units", "due_date_min"]] = [
            2,
            50,
            10000,
        ]
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert "TASK_INPUT_CHANGED" in codes
    assert "PRODUCTION_PLAN_QUANTITY_MISMATCH" in codes


def test_independent_audit_detects_self_consistent_but_wrong_plan_quantity():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        for frame in (baseline, candidate):
            frame.loc[frame.task_id == "OUTSIDE", ["batch_count", "production_units"]] = [2, 50]
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert "PRODUCTION_PLAN_QUANTITY_MISMATCH" in codes
    assert "TASK_INPUT_CHANGED" not in codes


def test_independent_audit_rejects_missing_run_scoped_sku_plan():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        conn.execute("DELETE FROM sku_production_plan")
        conn.execute("INSERT INTO sku_production_plan VALUES ('OTHER', 1, 'P01', 75)")
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert "MISSING_SKU_PLAN" in {item["code"] for item in result["issues"]}


def test_independent_audit_rejects_units_without_matching_batches():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        candidate.loc[candidate.task_id == "OUTSIDE", "production_units"] = 30
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert "INVALID_LOT_QUANTITY" in {item["code"] for item in result["issues"]}


def test_independent_audit_detects_source_routing_machine_and_duration_drift():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        for frame in (baseline, candidate):
            frame.loc[frame.task_id == "OUTSIDE", ["end_min", "duration_min"]] = [950, 50]
        conn.execute("UPDATE routing SET machine_id = 'M02'")
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    codes = {item["code"] for item in result["issues"]}
    assert "ROUTING_MISMATCH" in codes
    assert "ROUTE_DURATION_MISMATCH" in codes
    assert "DURATION_CHANGED" not in codes


def test_independent_audit_rejects_missing_lot_operation_in_source_route():
    conn = _calendar_connection()
    try:
        baseline, candidate = _schedules()
        conn.execute("INSERT INTO routing VALUES ('P01', 2, 'M01', 20)")
        result = audit_reschedule_candidate(conn, baseline, candidate, _trigger())
    finally:
        conn.close()
    assert "INCOMPLETE_LOT_ROUTE" in {item["code"] for item in result["issues"]}
