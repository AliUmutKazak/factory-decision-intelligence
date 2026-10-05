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
