"""Tests for Dynamic Rescheduling, Freeze Horizon, and Nervousness Engine (Faz 5)."""

import warnings

from src.contracts.schemas import (
    RescheduleTriggerEvent,
    ScheduleNervousnessReport,
    SolverStatus,
)
from src.scheduling.rescheduler import DynamicRescheduler


def test_dynamic_reschedule_with_freeze_horizon():
    """Verify that dynamic rescheduling preserves frozen tasks

    and recalculates nervousness metrics accurately.
    """
    rescheduler = DynamicRescheduler()

    # Olay: 480. dakikada (1. vardiya bitimi) tetikleme ve 120 dakikalık freeze horizon
    trigger = RescheduleTriggerEvent(
        event_id="EVT-BREAK-001",
        current_time_min=480,
        freeze_horizon_min=120,  # Toplam 600. dakikaya kadar olan işler kilitli
        delay_machine_id="M01",
        delay_duration_min=180,  # M01 tezgâhında 3 saatlik arıza/gecikme
        reason="M01 feeder malfunction at shift handover",
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        base_df, new_df, meta, report = rescheduler.execute_reschedule(
            trigger=trigger,
            new_run_id="RESCHED_TEST_01",
        )

    # 1. Çözücü Durumu
    assert meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert not new_df.empty
    assert len(base_df) == len(new_df)

    # 2. Freeze Horizon Doğrulaması: Cutoff öncesi işler eski çizelgeyle birebir aynı kalmalı
    freeze_cutoff = trigger.current_time_min + trigger.freeze_horizon_min
    base_indexed = base_df.set_index("task_id")
    new_indexed = new_df.set_index("task_id")

    for task_id, b_row in base_indexed.iterrows():
        if b_row["start_min"] < freeze_cutoff:
            n_row = new_indexed.loc[task_id]
            assert b_row["machine_id"] == n_row["machine_id"]
            assert b_row["start_min"] == n_row["start_min"]
            assert b_row["end_min"] == n_row["end_min"]

    # 3. Nervousness Metriği Doğrulaması
    assert isinstance(report, ScheduleNervousnessReport)
    assert report.total_tasks == len(base_df)
    assert report.frozen_tasks_count > 0
    assert 0.0 <= report.nervousness_score <= 1.0
    assert report.average_start_delta_min >= 0.0
    assert report.max_start_delta_min >= report.average_start_delta_min


def test_zero_nervousness_on_identical_run():
    """Verify that rescheduling without disruptions results in a near-zero nervousness score."""
    rescheduler = DynamicRescheduler()

    # Olay: 0 anında, gecikmesiz rutin yeniden tetikleme
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
        base_df, new_df, meta, report = rescheduler.execute_reschedule(
            trigger=trigger,
            new_run_id="RESCHED_CLEAN",
        )

    assert meta.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert isinstance(report, ScheduleNervousnessReport)
    # Temiz koşuda makine takası 0 olmalıdır
    assert report.machine_swapped_count == 0
    assert report.nervousness_score <= 0.05
