"""Tests for What-If Scenario Simulation and Sensitivity Analysis Engine (Faz 4)."""

import shutil
import sqlite3
import warnings
from contextlib import closing
from pathlib import Path

import pytest

from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    ScenarioDeltaReport,
    ScenarioType,
    ScheduleSolverMetadata,
    SolverStatus,
)
from src.scheduling.what_if import WhatIfEngine
from src.utils.run_bundle import sha256_file

REFERENCE_DB = Path(__file__).resolve().parents[1] / "artifacts" / "reference" / "factory.db"


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
    baseline, _, _, _ = engine.simulate_hot_order(
        HotOrderInjection(order_id="RUSH-SNAPSHOT", product_id="P01", quantity=51, due_date_min=1200),
        scenario_name="SCENARIO_SNAPSHOT",
        reuse_active_baseline=True,
        scenario_time_limit_seconds=2,
    )
    assert baseline.status == SolverStatus.FEASIBLE
    assert len(observed) == 1
    assert observed[0]["run_id"] == "SCENARIO_SNAPSHOT"
    assert observed[0]["time_limit_seconds"] == 2
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
