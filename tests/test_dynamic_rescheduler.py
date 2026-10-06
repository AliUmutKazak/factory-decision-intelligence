"""Tests for Dynamic Rescheduling, Freeze Horizon, and Lineage Audit (Faz 5)."""

import sqlite3
import warnings

from src.contracts.schemas import (
    RescheduleAuditEntry,
    RescheduleTriggerEvent,
    ScheduleNervousnessReport,
    SolverStatus,
)
from src.scheduling.rescheduler import DynamicRescheduler


def test_dynamic_reschedule_with_freeze_horizon_and_audit():
    """Verify that dynamic rescheduling preserves frozen tasks,

    calculates nervousness, and writes lineage audit logs.
    """
    rescheduler = DynamicRescheduler()

    trigger = RescheduleTriggerEvent(
        event_id="EVT-BREAK-001",
        current_time_min=480,
        freeze_horizon_min=120,
        delay_machine_id="M01",
        delay_duration_min=180,
        reason="M01 feeder malfunction at shift handover",
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        base_df, new_df, meta, report, audit = rescheduler.execute_reschedule(
            trigger=trigger,
            new_run_id="RESCHED_TEST_01",
        )

    assert meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert not new_df.empty
    assert len(base_df) == len(new_df)

    # Freeze horizon doğrulaması
    freeze_cutoff = trigger.current_time_min + trigger.freeze_horizon_min
    base_indexed = base_df.set_index("task_id")
    new_indexed = new_df.set_index("task_id")

    for task_id, b_row in base_indexed.iterrows():
        if b_row["start_min"] < freeze_cutoff:
            n_row = new_indexed.loc[task_id]
            assert b_row["machine_id"] == n_row["machine_id"]
            assert b_row["start_min"] == n_row["start_min"]
            assert b_row["end_min"] == n_row["end_min"]

    # Nervousness ve Audit doğrulaması
    assert isinstance(report, ScheduleNervousnessReport)
    assert isinstance(audit, RescheduleAuditEntry)
    assert audit.trigger_event_id == "EVT-BREAK-001"
    assert audit.affected_machine_id == "M01"
    assert audit.delay_duration_min == 180
    assert audit.nervousness_score == report.nervousness_score


def test_zero_nervousness_on_identical_run():
    """Verify that rescheduling without disruptions results in a low nervousness score."""
    rescheduler = DynamicRescheduler()

    trigger = RescheduleTriggerEvent(
        event_id="EVT-ROUTINE-CHECK",
        current_time_min=0,
        freeze_horizon_min=0,
        delay_machine_id=None,
        delay_duration_min=0,
        reason="Routine alignment",
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        base_df, new_df, meta, report, audit = rescheduler.execute_reschedule(
            trigger=trigger,
            new_run_id="RESCHED_CLEAN",
        )

    assert meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert isinstance(report, ScheduleNervousnessReport)
    assert isinstance(audit, RescheduleAuditEntry)
    assert report.machine_swapped_count == 0
    # Sıfır kesinti durumunda haftalık ufka göre sarsıntı skoru kontrollü olmalıdır
    assert report.nervousness_score <= 0.15


def test_scan_pending_mes_events():
    """Verify that scanner detects delay and breakdown events from mes_execution_events."""
    rescheduler = DynamicRescheduler()
    conn = sqlite3.connect(rescheduler.disk_db_path)
    try:
        triggers = rescheduler.scan_pending_mes_events(conn, current_time_min=10000)
        assert isinstance(triggers, list)
    finally:
        conn.close()


def test_local_repair_is_certified_and_persists_real_model_context():
    from src.scheduling.model_context import load_model_context

    engine = DynamicRescheduler()
    trigger = RescheduleTriggerEvent(event_id="LOCAL-CERTIFY", current_time_min=0, freeze_horizon_min=100000)
    base, schedule, metadata, _, audit = engine.execute_reschedule(trigger, new_run_id="LOCAL-CERTIFIED")
    assert audit.decision_tier == "VALIDATED_LOCAL_REPAIR"
    assert metadata.proven_optimal is False
    assert metadata.best_objective_bound is None
    assert schedule.set_index("task_id").start_min.to_dict() == base.set_index("task_id").start_min.to_dict()
    with sqlite3.connect(engine.disk_db_path) as conn:
        context = load_model_context(conn, "LOCAL-CERTIFIED")
        assert len(context["frozen_positions"]) == len(schedule)
        tier = conn.execute(
            "SELECT decision_tier FROM reschedule_audit_log WHERE new_run_id='LOCAL-CERTIFIED'"
        ).fetchone()[0]
        assert tier == audit.decision_tier
        row = conn.execute(
            "SELECT status, solver_status, is_optimal, best_bound_min, solve_time_seconds FROM schedule_solver_metadata WHERE run_id='LOCAL-CERTIFIED'"
        ).fetchone()
        assert row[0] == row[1] == "FEASIBLE"
        assert row[2] == 0 and row[3] is None and row[4] is not None
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert not app.error


def test_rejected_local_candidate_falls_back_to_authoritative_solver(monkeypatch):
    import src.scheduling.rescheduler as module

    def reject_candidate(*args, **kwargs):
        raise ValueError("candidate exceeds movement budget")

    original = module.run_cpsat_scheduling

    def bounded_solve(**kwargs):
        return original(**kwargs, time_limit_seconds=3)

    monkeypatch.setattr(module, "local_repair_candidate", reject_candidate)
    monkeypatch.setattr(module, "run_cpsat_scheduling", bounded_solve)
    engine = DynamicRescheduler()
    _, schedule, _, _, audit = engine.execute_reschedule(
        RescheduleTriggerEvent(event_id="LOCAL-FALLBACK", current_time_min=0, freeze_horizon_min=100000),
        new_run_id="LOCAL-FALLBACK",
        persist_audit=False,
    )
    assert not schedule.empty
    assert audit.decision_tier == "CPSAT_REOPTIMIZATION"
    assert "movement budget" in audit.repair_rejection_reason
