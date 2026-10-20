"""Tests for What-If Scenario Simulation and Sensitivity Analysis Engine (Faz 4)."""

import shutil
import sqlite3
import warnings
from contextlib import closing
from pathlib import Path

import pandas as pd
import pytest

from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    ScenarioDeltaReport,
    ScenarioType,
    ScheduleSolverMetadata,
    SolverStatus,
)
from src.scheduling.what_if import WhatIfEngine, _schedule_kpis
from src.utils.run_bundle import sha256_file

REFERENCE_DB = Path(__file__).resolve().parents[1] / "artifacts" / "reference" / "factory.db"


def test_what_if_kpis_count_tardiness_once_per_lot_and_all_setups():
    rows = pd.DataFrame(
        [
            {"lot_id": "A", "end_min": 8, "due_date_min": 12, "priority_weight": 3, "setup_before_min": 2},
            {"lot_id": "A", "end_min": 15, "due_date_min": 12, "priority_weight": 3, "setup_before_min": 4},
            {"lot_id": "B", "end_min": 20, "due_date_min": 17, "priority_weight": 2, "setup_before_min": 5},
        ]
    )
    kpis = _schedule_kpis(rows)
    assert kpis.makespan_min == 20
    assert kpis.weighted_tardiness_min == 15  # A: 3*3, B: 3*2; no double count for A.
    assert kpis.total_setup_min == 11


@pytest.mark.parametrize(
    "column,value", [("due_date_min", None), ("priority_weight", float("inf")), ("setup_before_min", -1)]
)
def test_what_if_kpis_reject_incomplete_or_invalid_rows(column, value):
    row = {"lot_id": "A", "end_min": 15, "due_date_min": 12, "priority_weight": 3, "setup_before_min": 2}
    row[column] = value
    rows = pd.DataFrame([row])
    with pytest.raises(RuntimeError, match="invalid"):
        _schedule_kpis(rows)


def test_what_if_kpis_reject_conflicting_lot_commitment():
    rows = pd.DataFrame(
        [
            {"lot_id": "A", "end_min": 8, "due_date_min": 12, "priority_weight": 3, "setup_before_min": 2},
            {"lot_id": "A", "end_min": 15, "due_date_min": 13, "priority_weight": 3, "setup_before_min": 4},
        ]
    )
    with pytest.raises(RuntimeError, match="conflicting"):
        _schedule_kpis(rows)


def test_what_if_delta_uses_schedule_rows_for_both_plans():
    baseline = pd.DataFrame(
        [{"lot_id": "A", "end_min": 20, "due_date_min": 12, "priority_weight": 2, "setup_before_min": 5}]
    )
    scenario = pd.DataFrame(
        [{"lot_id": "A", "end_min": 15, "due_date_min": 12, "priority_weight": 2, "setup_before_min": 3}]
    )
    report = WhatIfEngine()._calculate_delta("DUMMY", ScenarioType.MACHINE_BREAKDOWN, baseline, scenario)
    assert report.makespan_delta_min == -5
    assert report.tardiness_delta_min == -10
    assert report.setup_delta_min == -2
    assert report.impacted_tasks_count == 1


@pytest.fixture
def reference_active_db(tmp_path):
    """Use one sealed input set, independent of the mutable local ACTIVE run."""
    db = tmp_path / "factory.db"
    shutil.copy2(REFERENCE_DB, db)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE pipeline_runs SET status = 'ACTIVE' WHERE status = 'COMPLETED'")
    return db


def test_machine_breakdown_scenario_simulation(reference_active_db):
    """Verify that a machine breakdown event simulates isolated CP-SAT replanning

    and generates an accurate delta report.
    """
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    breakdown_event = MachineBreakdownEvent(
        machine_id="M01",
        start_min=600,
        duration_min=240,  # 4 saatlik duruş
        description="M01 Spindle failure",
    )
    before = sha256_file(Path(engine.disk_db_path))

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        base_meta, scn_meta, delta_report, sched_df = engine.simulate_breakdown(
            breakdown=breakdown_event,
            scenario_name="SCENARIO_BREAKDOWN_M01",
        )

    # Doğrulamalar
    assert base_meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert scn_meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert isinstance(delta_report, ScenarioDeltaReport)
    assert delta_report.scenario_type == ScenarioType.MACHINE_BREAKDOWN
    assert not sched_df.empty
    assert sha256_file(Path(engine.disk_db_path)) == before
    machine_tasks = sched_df[sched_df["machine_id"] == "M01"]
    assert ((machine_tasks["end_min"] <= 600) | (machine_tasks["setup_start_min"] >= 840)).all()

    # Delta raporu alanlarının mantıksal tutarlılığı
    assert delta_report.scenario_makespan_min >= 0
    assert delta_report.baseline_makespan_min >= 0
    assert delta_report.makespan_delta_min == delta_report.scenario_makespan_min - delta_report.baseline_makespan_min
    assert delta_report.impacted_tasks_count == len(sched_df)
    assert delta_report.scenario_makespan_min == sched_df["end_min"].max()
    assert delta_report.scenario_total_setup_min == sched_df["setup_before_min"].sum()


def test_breakdown_rejects_independent_audit_failure_after_solver_success(reference_active_db, monkeypatch):
    before = sha256_file(reference_active_db)
    observed = []

    def reject_candidate(conn, baseline, candidate, trigger, **kwargs):
        observed.append((len(baseline), len(candidate), trigger.current_time_min, kwargs["baseline_run_id"]))
        return {"status": "REJECTED", "issues": [{"code": "INJECTED_AUDIT_FAILURE"}]}

    monkeypatch.setattr("src.scheduling.what_if.audit_reschedule_candidate", reject_candidate)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        with pytest.raises(RuntimeError, match="INJECTED_AUDIT_FAILURE"):
            engine.simulate_breakdown(
                MachineBreakdownEvent(machine_id="M01", start_min=600, duration_min=240),
                scenario_name="SCENARIO_BREAKDOWN_AUDIT_REJECT",
            )
    assert len(observed) == 1
    assert observed[0] == (31, 31, 0, "BASE")
    assert sha256_file(reference_active_db) == before


def test_hot_order_injection_scenario_simulation(reference_active_db, monkeypatch):
    """Verify that injecting a rush hot order triggers schedule expansion

    and evaluates tardiness/makespan impacts.
    """
    # This checks scenario correctness, not the G7 solve-time SLO. The rush
    # workload can need more than the interactive default on slower hosts.
    monkeypatch.setattr("src.scheduling.schedule_cpsat.CPSAT_TIME_LIMIT_SECONDS", 90.0)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    hot_order = HotOrderInjection(
        order_id="RUSH-999",
        product_id="P01",
        quantity=51,
        due_date_min=1200,
        priority_weight=20,
    )
    before = sha256_file(Path(engine.disk_db_path))

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        base_meta, scn_meta, delta_report, sched_df = engine.simulate_hot_order(
            hot_order=hot_order,
            scenario_name="SCENARIO_HOT_ORDER_P01",
        )

    # Doğrulamalar
    assert base_meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert scn_meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert isinstance(delta_report, ScenarioDeltaReport)
    assert delta_report.scenario_type == ScenarioType.HOT_ORDER
    assert not sched_df.empty
    assert sha256_file(Path(engine.disk_db_path)) == before
    rush = sched_df[sched_df["parent_lot_id"] == "HOT_P01"]
    assert not rush.empty
    assert (rush["due_date_min"] == 1200).all()
    assert (rush["priority_weight"] == 20).all()
    assert rush[rush["operation_seq"] == 1]["production_units"].sum() == 75

    # Acil sipariş sonrasında çizelgelenen iş sayısı baz plana eşit veya daha fazla olmalıdır
    assert delta_report.makespan_delta_min == delta_report.scenario_makespan_min - delta_report.baseline_makespan_min
    assert delta_report.scenario_makespan_min == sched_df["end_min"].max()
    assert delta_report.scenario_total_setup_min == sched_df["setup_before_min"].sum()


def test_hot_order_timeout_keeps_source_active_run_unchanged(reference_active_db, monkeypatch):
    """A failed in-memory scenario must not alter the source ACTIVE version."""
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    before = sha256_file(reference_active_db)
    with sqlite3.connect(reference_active_db) as conn:
        active_before = conn.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE'").fetchone()[0]

    def baseline_then_timeout(**kwargs):
        if kwargs["run_id"] == "BASE":
            return object()
        raise TimeoutError("UNKNOWN: no accepted hot-order schedule")

    monkeypatch.setattr("src.scheduling.what_if.run_cpsat_scheduling", baseline_then_timeout)
    hot_order = HotOrderInjection(
        order_id="RUSH-TIMEOUT",
        product_id="P01",
        quantity=51,
        due_date_min=1200,
        priority_weight=20,
    )

    with pytest.raises(TimeoutError, match="no accepted hot-order schedule"):
        engine.simulate_hot_order(hot_order, scenario_name="SCENARIO_TIMEOUT")

    assert sha256_file(reference_active_db) == before
    with sqlite3.connect(reference_active_db) as conn:
        assert conn.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE'").fetchone()[0] == active_before
        assert conn.execute("SELECT 1 FROM pipeline_runs WHERE run_id = 'SCENARIO_TIMEOUT'").fetchone() is None


def test_hot_order_uses_distinct_baseline_and_scenario_limits(reference_active_db, monkeypatch):
    observed = []

    def record_solve(**kwargs):
        observed.append((kwargs["run_id"], kwargs["time_limit_seconds"]))
        return ScheduleSolverMetadata(
            run_id=kwargs["run_id"],
            status=SolverStatus.FEASIBLE,
            proven_optimal=False,
            wall_time_seconds=0.1,
            objective_value=1.0,
        )

    monkeypatch.setattr("src.scheduling.what_if.run_cpsat_scheduling", record_solve)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    before = sha256_file(reference_active_db)
    with pytest.raises(RuntimeError, match="EMPTY_SCHEDULE"):
        engine.simulate_hot_order(
            HotOrderInjection(order_id="LIMIT-CHECK", product_id="P01", quantity=51, due_date_min=1200),
            scenario_name="SCENARIO_LIMIT_CHECK",
            baseline_time_limit_seconds=7,
            scenario_time_limit_seconds=2,
        )
    assert observed == [("BASE", 7), ("SCENARIO_LIMIT_CHECK", 2)]
    assert sha256_file(reference_active_db) == before


def test_hot_order_reuses_accepted_active_baseline_without_resolving_it(reference_active_db, monkeypatch):
    observed = []

    def record_solve(**kwargs):
        observed.append(kwargs)
        return ScheduleSolverMetadata(
            run_id=kwargs["run_id"],
            status=SolverStatus.FEASIBLE,
            proven_optimal=False,
            wall_time_seconds=0.1,
            objective_value=1.0,
        )

    monkeypatch.setattr("src.scheduling.what_if.run_cpsat_scheduling", record_solve)
    before = sha256_file(reference_active_db)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    with pytest.raises(RuntimeError, match="EMPTY_SCHEDULE"):
        engine.simulate_hot_order(
            HotOrderInjection(order_id="RUSH-SNAPSHOT", product_id="P01", quantity=51, due_date_min=1200),
            scenario_name="SCENARIO_SNAPSHOT",
            reuse_active_baseline=True,
            scenario_time_limit_seconds=2,
            scenario_dispatch_rule="EDD",
        )
    assert len(observed) == 1
    assert observed[0]["run_id"] == "SCENARIO_SNAPSHOT"
    assert observed[0]["time_limit_seconds"] == 2
    assert observed[0]["dispatch_rule"] == "EDD"
    assert not observed[0]["reference_schedule"].empty
    assert (observed[0]["sku_plan"]["lot_id"] == "HOT_P01").any()
    assert sha256_file(reference_active_db) == before


def test_hot_order_rejects_unaccepted_active_baseline(reference_active_db, monkeypatch):
    with sqlite3.connect(reference_active_db) as conn:
        conn.execute("UPDATE schedule_solver_metadata SET status = 'UNKNOWN'")
    before = sha256_file(reference_active_db)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))

    def unexpected_solve(**kwargs):
        pytest.fail("solver must not run with an unaccepted ACTIVE baseline")

    monkeypatch.setattr("src.scheduling.what_if.run_cpsat_scheduling", unexpected_solve)
    with pytest.raises(RuntimeError, match="no accepted solver result"):
        engine.simulate_hot_order(
            HotOrderInjection(order_id="RUSH-INVALID", product_id="P01", quantity=51, due_date_min=1200),
            reuse_active_baseline=True,
        )
    assert sha256_file(reference_active_db) == before


def test_hot_order_rejects_active_context_it_cannot_replay(reference_active_db):
    with sqlite3.connect(reference_active_db) as conn:
        conn.execute(
            "UPDATE schedule_model_context SET payload_json = ?",
            (
                '{"earliest_start_min": 0, "frozen_positions": {"1": ["M01", 0, 10]}, "flexible_windows": {}, "maintenance_overrides": []}',
            ),
        )
    before = sha256_file(reference_active_db)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    with pytest.raises(RuntimeError, match="cannot preserve"):
        engine.simulate_hot_order(
            HotOrderInjection(order_id="RUSH-FROZEN", product_id="P01", quantity=51, due_date_min=1200),
            reuse_active_baseline=True,
        )
    assert sha256_file(reference_active_db) == before


def test_hot_order_fixed_dispatch_returns_isolated_schedule(reference_active_db, capsys):
    before = sha256_file(reference_active_db)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        baseline, scenario, _, schedule = engine.simulate_hot_order(
            HotOrderInjection(order_id="RUSH-EDD", product_id="P01", quantity=51, due_date_min=1200),
            scenario_name="SCENARIO_EDD",
            reuse_active_baseline=True,
            scenario_dispatch_rule="EDD",
            scenario_time_limit_seconds=2,
        )
    assert baseline.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert scenario.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert schedule["task_id"].is_unique
    assert (schedule["parent_lot_id"] == "HOT_P01").any()
    assert sha256_file(reference_active_db) == before
    audit_output = capsys.readouterr().out
    assert "MİKTAR MUTABAKATI" in audit_output
    assert "Hafta 1 son operasyon bitişi:" in audit_output
    assert "Bu değerler fiili üretim veya teslimat değildir." in audit_output


def test_hot_order_rejects_independent_audit_failure_after_solver_success(reference_active_db, monkeypatch):
    before = sha256_file(reference_active_db)
    observed = []

    def reject_candidate(conn, run_id, order, schedule):
        observed.append((run_id, order.order_id, len(schedule)))
        return {"status": "REJECTED", "issues": [{"code": "INJECTED_AUDIT_FAILURE"}]}

    monkeypatch.setattr("src.scheduling.what_if.audit_hot_order_schedule", reject_candidate)
    engine = WhatIfEngine(disk_db_path=str(reference_active_db))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        with pytest.raises(RuntimeError, match="INJECTED_AUDIT_FAILURE"):
            engine.simulate_hot_order(
                HotOrderInjection(order_id="RUSH-AUDIT", product_id="P01", quantity=51, due_date_min=1200),
                scenario_name="SCENARIO_AUDIT_REJECT",
                reuse_active_baseline=True,
                scenario_dispatch_rule="EDD",
                scenario_time_limit_seconds=2,
            )
    assert len(observed) == 1
    assert observed[0][1:] == ("RUSH-AUDIT", 34)
    assert sha256_file(reference_active_db) == before
