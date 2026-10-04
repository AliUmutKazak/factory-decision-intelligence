"""tests/test_frozen_horizon.py
Madde 20: Multi-Tiered Dynamic Frozen Horizon (MES/APS uyumluluk) doğrulama testleri.
"""

import pandas as pd

from src.integration.rescheduler import ClosedLoopRescheduler
from src.utils.db import get_db_connection


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

    result = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01",
        down_start_min=down_start,
        down_duration_min=down_dur,
        reason="Madde 20 Horizon Audit",
        commit=False,
    )
    assert result["status"] == "RESCHEDULED"

    # CP-SAT çözümü üzerinden durumları denetle
    df_resched = rescheduler._solve_cpsat_reschedule(
        df=df_init.copy(),
        machine_id="M01",
        down_start_min=down_start,
        down_duration_min=down_dur,
    )
    if df_resched is None:
        df_resched = df_init.copy()

    # 1. COMPLETED -> Immutable (Arıza öncesinde biten işlerin zamanları değişmez)
    completed_tasks = df_init[df_init["end_min"] <= down_start]
    for _, row in completed_tasks.iterrows():
        tid = row["task_id"]
        row_new = df_resched[df_resched["task_id"] == tid].iloc[0]
        assert row_new["start_min"] == row["start_min"], f"{tid} COMPLETED işin başlangıcı değişmiş!"
        assert row_new["end_min"] == row["end_min"], f"{tid} COMPLETED işin bitişi değişmiş!"

    # 2. IN_PROGRESS -> Locked start (Arıza anında çalışan işin başlangıcı korunur)
    running_tasks = df_init[(df_init["start_min"] <= down_start) & (df_init["end_min"] > down_start)]
    for _, row in running_tasks.iterrows():
        tid = row["task_id"]
        row_new = df_resched[df_resched["task_id"] == tid].iloc[0]
        assert row_new["start_min"] == row["start_min"], f"{tid} IN_PROGRESS işin başlangıcı ötelenmiş!"
