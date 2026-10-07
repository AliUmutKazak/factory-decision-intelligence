import sqlite3

import pandas as pd
import pytest

from src.config import ECONOMIC_CONFIG, get_runtime_paths
from src.economics.schedule_cost import evaluate_schedule_cost
from src.scheduling.calendar_service import MachineCalendarService
from src.scheduling.dispatch import local_repair_candidate
from src.scheduling.maintenance import MaintenanceWindow
from src.scheduling.model_context import load_model_context
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.what_if import NoCloseConnectionWrapper
from src.utils.db import clone_run_inputs, get_active_run_id


def private_case():
    conn = sqlite3.connect(":memory:")
    with sqlite3.connect(get_runtime_paths()["db_path"]) as source:
        source.backup(conn)
    active = get_active_run_id(conn)
    clone_run_inputs(conn, active, "TINY")
    conn.execute("UPDATE mrp_plan SET net_req=0, action_message='NONE' WHERE run_id='TINY'")
    conn.execute("UPDATE machine_capacity_plan SET overtime_hours=0 WHERE run_id='TINY'")
    conn.execute("UPDATE machine_state_snapshot SET last_product_id='P01' WHERE run_id='TINY' AND machine_id='M01'")
    conn.execute("UPDATE changeover_matrix SET setup_time_min=0")
    conn.execute("UPDATE changeover_matrix SET setup_time_min=120 WHERE from_product='P02' AND to_product='P01'")
    tasks = pd.DataFrame(
        [
            dict(
                task_id="A",
                lot_id="A",
                product_id="P01",
                machine_id="M01",
                operation_seq=1,
                duration_min=60,
                due_date_min=10080,
                priority_weight=1,
                production_units=10,
                batch_count=1,
                batch_size_units=10,
                release_time_min=480,
            ),
            dict(
                task_id="B",
                lot_id="B",
                product_id="P02",
                machine_id="M01",
                operation_seq=1,
                duration_min=10,
                due_date_min=490,
                priority_weight=5,
                production_units=10,
                batch_count=1,
                batch_size_units=10,
                release_time_min=480,
            ),
        ]
    )
    return conn, tasks


def test_money_rates_change_chosen_sequence_and_match_independent_tmc():
    conn, tasks = private_case()
    try:
        choices = []
        for penalty in (0, 1000):
            rates = ECONOMIC_CONFIG.model_copy(
                update={"holding_cost_per_unit_per_day": 0, "tardiness_cost_per_hour": penalty}
            )
            meta = run_cpsat_scheduling(
                run_id="TINY",
                connection=NoCloseConnectionWrapper(conn),
                persist_outputs=False,
                task_override=tasks,
                policy="COST_OPTIMIZED",
                economic_config=rates,
                time_limit_seconds=3,
            )
            schedule = pd.read_sql("SELECT * FROM production_schedule WHERE run_id='TINY' ORDER BY start_min", conn)
            choices.append(schedule.iloc[0].task_id)
            cost = evaluate_schedule_cost(conn, schedule, "TINY", rates)
            assert meta.objective_units == "EUR"
            assert meta.objective_value == pytest.approx(cost["total_manufacturing_cost"], abs=0.011)
            assert load_model_context(conn, "TINY")["earliest_start_min"] == 0
        assert choices == ["A", "B"]
    finally:
        conn.close()


def test_flexible_window_is_a_hard_start_and_machine_constraint():
    conn, tasks = private_case()
    try:
        run_cpsat_scheduling(
            run_id="TINY",
            connection=NoCloseConnectionWrapper(conn),
            persist_outputs=False,
            task_override=tasks,
            flexible_task_windows={"B": ("M01", 600, 600)},
            time_limit_seconds=3,
        )
        assert (
            conn.execute("SELECT start_min FROM production_schedule WHERE run_id='TINY' AND task_id='B'").fetchone()[0]
            == 600
        )
        with pytest.raises(ValueError, match="machine"):
            run_cpsat_scheduling(
                run_id="TINY",
                connection=NoCloseConnectionWrapper(conn),
                persist_outputs=False,
                task_override=tasks,
                flexible_task_windows={"B": ("M02", 600, 600)},
                time_limit_seconds=3,
            )
    finally:
        conn.close()


def test_local_repair_preserves_commitments_and_rejects_excess_movement():
    schedule = pd.DataFrame(
        [
            dict(
                task_id="A",
                lot_id="A",
                product_id="P01",
                machine_id="M01",
                operation_seq=1,
                duration_min=60,
                start_min=480,
                end_min=540,
            ),
            dict(
                task_id="B",
                lot_id="B",
                product_id="P02",
                machine_id="M01",
                operation_seq=1,
                duration_min=60,
                start_min=540,
                end_min=600,
            ),
        ]
    )
    arguments = dict(
        schedule=schedule,
        current_time=500,
        frozen={"A": ("M01", 480, 540)},
        daily_hours={"M01": 16},
        setup_matrix={},
        initial_states={},
        maintenance=[MaintenanceWindow("M01", 540, 600)],
    )
    candidate = local_repair_candidate(**arguments, flexible={"B": ("M01", 540, 610)})
    assert candidate == {"A": ("M01", 480, 540), "B": ("M01", 600, 660)}
    with pytest.raises(ValueError, match="movement"):
        local_repair_candidate(**arguments, flexible={"B": ("M01", 540, 580)})


def test_week_two_nights_do_not_become_overtime_idle_energy():
    assert MachineCalendarService.open_minutes(10080, 10560, 16, True) == 0
    assert MachineCalendarService.open_minutes(0, 480, 16, True) == 480
    assert MachineCalendarService.open_minutes(8640, 10080, 16, True) == 0


def test_dispatch_benchmark_preserves_snapshot_and_shared_disruption_constraints(tmp_path):
    import hashlib

    from src.scheduling.production_benchmark import production_benchmark

    conn, tasks = private_case()
    try:
        conn.execute("UPDATE pipeline_runs SET status='COMPLETED', trigger_source='test' WHERE run_id='TINY'")
        run_cpsat_scheduling(
            run_id="TINY",
            connection=NoCloseConnectionWrapper(conn),
            persist_outputs=False,
            task_override=tasks,
            earliest_start_min=700,
            maintenance_overrides=[MaintenanceWindow("M01", 700, 760)],
            time_limit_seconds=3,
        )
        path = tmp_path / "benchmark.db"
        with sqlite3.connect(path) as disk:
            conn.backup(disk)
    finally:
        conn.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    report = production_benchmark(path, baseline_run_id="TINY", time_limit_seconds=3)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert len(report["cases"]) == 6
    for case in report["cases"]:
        assert case["Status"] in {"OPTIMAL", "FEASIBLE"}
        assert case["Physical Constraints"] == report["input_hash"]
        assert all(task["start_min"] >= 760 for task in case["schedule"])
        assert {task["task_id"] for task in case["schedule"]} == {"A", "B"}


def test_energy_setup_and_partial_buckets_match_independent_schedule_cost(tmp_path):
    from src.carbon.carbon_analytics import compute_carbon_analytics
    from src.energy.energy_analytics import compute_energy_analytics

    conn, tasks = private_case()
    try:
        rates = ECONOMIC_CONFIG.model_copy(update={"holding_cost_per_unit_per_day": 0, "tardiness_cost_per_hour": 1000})
        run_cpsat_scheduling(
            run_id="TINY",
            connection=NoCloseConnectionWrapper(conn),
            persist_outputs=False,
            task_override=tasks,
            policy="COST_OPTIMIZED",
            economic_config=rates,
            time_limit_seconds=3,
        )
        schedule = pd.read_sql("SELECT * FROM production_schedule WHERE run_id='TINY'", conn)
        expected = evaluate_schedule_cost(conn, schedule, "TINY", rates)
        path = tmp_path / "energy.db"
        with sqlite3.connect(path) as disk:
            conn.backup(disk)
    finally:
        conn.close()
    kpis = compute_energy_analytics(run_id="TINY", db_path=path, processed_dir=tmp_path / "processed")
    with sqlite3.connect(path) as conn:
        machines = pd.read_sql("SELECT * FROM energy_machine_kpis WHERE run_id='TINY'", conn)
        profile = pd.read_sql("SELECT * FROM energy_profile_15min WHERE run_id='TINY'", conn)
    assert kpis["grand_total_kwh"] == pytest.approx(expected["energy_kwh"], abs=0.001)
    assert kpis["setup_kwh"] > 0
    assert kpis["grand_total_kwh"] == pytest.approx(
        (profile.total_load_kw * profile.interval_min / 60).sum(), abs=0.001
    )
    assert machines.set_index("machine_id").loc["M01", "setup_hours"] == 2
    compute_carbon_analytics(run_id="TINY", db_path=path, processed_dir=tmp_path / "processed")
    with sqlite3.connect(path) as conn:
        carbon = pd.read_sql("SELECT * FROM carbon_kpis WHERE run_id='TINY'", conn).iloc[0]
    assert expected["scope_1_tco2e"] == pytest.approx(carbon.scope_1_tco2e, abs=0.0001)
    assert expected["carbon_tco2e"] == pytest.approx(carbon.total_tco2e, abs=0.0001)


def test_financial_scenario_includes_material_and_expedite_with_shared_tmc():
    from src.scenarios.scenario_engine import ScenarioEngine, ScenarioShock

    path = get_runtime_paths()["db_path"]
    baseline = ScenarioEngine(str(path)).evaluate_scenario(ScenarioShock("BASELINE"))
    with sqlite3.connect(path) as conn:
        active = get_active_run_id(conn)
        schedule = pd.read_sql("SELECT * FROM production_schedule WHERE run_id = ?", conn, params=(active,))
        costs = evaluate_schedule_cost(conn, schedule, active)
    assert costs["material_cost"] > 0
    assert baseline.total_cost_eur == costs["total_manufacturing_cost"]
