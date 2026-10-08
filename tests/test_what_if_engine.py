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
