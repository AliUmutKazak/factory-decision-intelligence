"""tests/test_frozen_horizon.py
Madde 20: Multi-Tiered Dynamic Frozen Horizon (MES/APS uyumluluk) doğrulama testleri.
"""

import pandas as pd

from src.integration.rescheduler import ClosedLoopRescheduler
from src.utils.db import get_db_connection


def test_execution_commitments_override_planned_start_and_zero_freeze_window():
    from src.contracts.schemas import RescheduleTriggerEvent
    from src.scheduling.rescheduler import DynamicRescheduler

    baseline = pd.DataFrame(
        [
            {"task_id": 1, "machine_id": "M01", "start_min": 480, "end_min": 600, "execution_status": "SCHEDULED"},
            {"task_id": 2, "machine_id": "M01", "start_min": 900, "end_min": 960, "execution_status": "IN_PROGRESS"},
            {"task_id": 3, "machine_id": "M01", "start_min": 1000, "end_min": 1060, "execution_status": "SCHEDULED"},
            {"task_id": 4, "machine_id": "M01", "start_min": 1200, "end_min": 1260, "execution_status": "SCHEDULED"},
        ]
    )
    trigger = RescheduleTriggerEvent(event_id="ZERO-FREEZE", current_time_min=480, freeze_horizon_min=0)
    engine = DynamicRescheduler.__new__(DynamicRescheduler)
    frozen = engine._build_frozen_positions(baseline, trigger, {"3"})
    assert set(frozen) == {"1", "2", "3"}
    assert frozen["2"] == ("M01", 900.0, 960.0)


def test_frozen_horizon_data_model_columns_exist():
    conn = get_db_connection()
    df = pd.read_sql("SELECT * FROM production_schedule LIMIT 10;", conn)
    conn.close()

    required_cols = [
        "schedule_state",
        "execution_status",
        "dispatch_status",
        "freeze_until_min",
    ]
    for col in required_cols:
        assert col in df.columns, f"{col} kolonu production_schedule tablosunda eksik!"


def test_multi_tiered_state_transitions_on_breakdown():
    rescheduler = ClosedLoopRescheduler()
    conn = get_db_connection()
    df_init = pd.read_sql(
        "SELECT * FROM production_schedule WHERE run_id = ?;",
        conn,
        params=(rescheduler.run_id,),
    )
    conn.close()

    down_start = 600.0
    down_dur = 90.0

    from src.contracts.schemas import RescheduleTriggerEvent

    base, df_resched, meta, report, audit = rescheduler._engine.execute_reschedule(
        RescheduleTriggerEvent(
            event_id="FREEZE-AUDIT",
            current_time_min=int(down_start),
            freeze_horizon_min=240,
            delay_machine_id="M01",
            delay_duration_min=int(down_dur),
        ),
        persist_audit=False,
    )
    assert len(df_resched) == len(df_init) > 0

    # 1. COMPLETED -> Immutable (Arıza öncesinde biten işlerin zamanları değişmez)
    completed_tasks = df_init[df_init["end_min"] <= down_start]
    for _, row in completed_tasks.iterrows():
        tid = row["task_id"]
        row_new = df_resched[df_resched["task_id"] == tid].iloc[0]
        assert row_new["start_min"] == row["start_min"], f"{tid} COMPLETED işin başlangıcı değişmiş!"
        assert row_new["end_min"] == row["end_min"], f"{tid} COMPLETED işin bitişi değişmiş!"
        assert row_new["schedule_state"] == "FROZEN"

    # 2. IN_PROGRESS -> Locked start (Arıza anında çalışan işin başlangıcı korunur)
    running_tasks = df_init[(df_init["start_min"] <= down_start) & (df_init["end_min"] > down_start)]
    for _, row in running_tasks.iterrows():
        tid = row["task_id"]
        row_new = df_resched[df_resched["task_id"] == tid].iloc[0]
        assert row_new["start_min"] == row["start_min"], f"{tid} IN_PROGRESS işin başlangıcı ötelenmiş!"
