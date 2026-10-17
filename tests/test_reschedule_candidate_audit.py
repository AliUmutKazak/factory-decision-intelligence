import sqlite3

import pandas as pd

from src.contracts.schemas import RescheduleTriggerEvent
from src.scheduling.reschedule_candidate_audit import audit_reschedule_candidate


def _calendar_connection(variable_day=None):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE machines (machine_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE machine_calendar (machine_id TEXT, day_of_week INTEGER, shift_id TEXT, "
                 "start_minute INTEGER, end_minute INTEGER, available_hours REAL, exception_type TEXT, is_available INTEGER)")
    conn.execute("INSERT INTO machines VALUES ('M01')")
    for day in range(7):
        changed = day == variable_day
        conn.execute(
            "INSERT INTO machine_calendar VALUES ('M01', ?, 'SHIFT_REGULAR', 480, ?, ?, ?, 1)",
            (day, 1380 if changed else 1440, 15 if changed else 16, "EXCEPTION" if changed else "REGULAR"),
        )
    return conn


def _schedules():
    baseline = pd.DataFrame(
        [
            {"task_id": "FROZEN", "machine_id": "M01", "start_min": 500, "end_min": 540,
             "schedule_state": "FREE", "freeze_until_min": 0, "execution_status": "SCHEDULED"},
            {"task_id": "FLEX", "machine_id": "M01", "start_min": 600, "end_min": 640,
             "schedule_state": "FREE", "freeze_until_min": 0, "execution_status": "SCHEDULED"},
            {"task_id": "OUTSIDE", "machine_id": "M01", "start_min": 900, "end_min": 940,
             "schedule_state": "FREE", "freeze_until_min": 0, "execution_status": "SCHEDULED"},
        ]
    )
    candidate = baseline.copy()
    candidate.loc[candidate.task_id == "FROZEN", "schedule_state"] = "FROZEN"
    candidate.loc[candidate.task_id == "FROZEN", "freeze_until_min"] = 540
    candidate.loc[candidate.task_id == "FLEX", "schedule_state"] = "FLEXIBLE"
    candidate.loc[candidate.task_id == "FLEX", "start_min"] = 580
    candidate.loc[candidate.task_id == "FLEX", "end_min"] = 620
    return baseline, candidate


def _trigger():
    return RescheduleTriggerEvent(
        event_id="AUDIT-1", current_time_min=480, freeze_horizon_min=60,
        flexible_horizon_min=300, max_flexible_shift_min=30,
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
