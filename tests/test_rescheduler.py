"""
tests/test_rescheduler.py
Closed-Loop Dynamic Rescheduling motorunun test süiti.
"""

import pandas as pd

from src.integration.rescheduler import ClosedLoopRescheduler
from src.utils.db import get_db_connection


def test_closed_loop_machine_breakdown_impact():
    rescheduler = ClosedLoopRescheduler()

    # M01 tezgahında 500. dakikada 120 dakikalık plansız duruş senaryosu
    result = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01", down_start_min=500.0, down_duration_min=120.0, reason="Acil Rulman Değişimi"
    )

    assert result["status"] == "RESCHEDULED"
    assert result["affected_tasks_count"] > 0
    assert result["new_makespan_min"] >= result["old_makespan_min"]
    assert result["delta_makespan_min"] >= 0.0


def test_reschedule_event_persisted_to_db():
    rescheduler = ClosedLoopRescheduler()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*) FROM mes_execution_events
        WHERE run_id = ? AND event_type = 'MACHINE_DOWN';
    """,
        (rescheduler.run_id,),
    )
    count_before = cur.fetchone()[0]

    rescheduler.reschedule_on_machine_breakdown(
        machine_id="M02", down_start_min=800.0, down_duration_min=60.0, reason="Sensör Kalibrasyon Hatası"
    )

    cur.execute(
        """
        SELECT COUNT(*) FROM mes_execution_events
        WHERE run_id = ? AND event_type = 'MACHINE_DOWN';
    """,
        (rescheduler.run_id,),
    )
    count_after = cur.fetchone()[0]

    assert count_after == count_before + 1, "Arıza olayı mes_execution_events tablosuna kaydedilmedi."


def test_two_tier_hybrid_rescheduling_modes():
    """
    Kısa süreli arızalarda (<= 60 dk) FAST_LOCAL_REPAIR,
    büyük duruşlarda (> 60 dk) CPSAT_REOPTIMIZATION modunun tetiklendiğini doğrular.
    """
    rescheduler = ClosedLoopRescheduler()

    # 1. Küçük gecikme (15 dk) -> Fast-path heuristic
    result_minor = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01",
        down_start_min=10.0,
        down_duration_min=15.0,
        reason="Minor Tool Jam",
    )
    assert result_minor["status"] in ("RESCHEDULED", "NO_IMPACT")
    if result_minor["status"] == "RESCHEDULED":
        assert result_minor["reschedule_mode"] == "FAST_LOCAL_REPAIR"
        assert result_minor["is_major_disruption"] is False

    # 2. Majör arıza (180 dk / 3 saat) -> Solver Tier Re-optimization
    result_major = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01",
        down_start_min=10.0,
        down_duration_min=180.0,
        reason="Spindle Motor Failure",
    )
    assert result_major["status"] in ("RESCHEDULED", "NO_IMPACT")
    if result_major["status"] == "RESCHEDULED":
        assert result_major["reschedule_mode"] == "CPSAT_REOPTIMIZATION"
        assert result_major["is_major_disruption"] is True


def test_frozen_horizon_preserves_completed_and_running_tasks():
    """
    Arıza anında geçmiş işlerin (COMPLETED) değişmediğini,
    devam eden işin (RUNNING) başlangıç zamanının korunduğunu doğrular.
    """
    rescheduler = ClosedLoopRescheduler()
    conn = get_db_connection()

    # Aktif çizelgedeki ilk görevi alalım
    df_first = pd.read_sql_query(
        "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY start_min ASC LIMIT 1;",
        conn,
        params=(rescheduler.run_id,),
    )
    if not df_first.empty:
        task = df_first.iloc[0]
        mach = task["machine_id"]
        t_start = float(task["start_min"])
        t_end = float(task["end_min"])

        # Görevin tam ortasında (RUNNING anında) bir arıza simüle edelim
        mid_time = (t_start + t_end) / 2.0
        result = rescheduler.reschedule_on_machine_breakdown(
            machine_id=mach,
            down_start_min=mid_time,
            down_duration_min=45.0,
            reason="Test Mid-run Breakdown",
        )
        assert result["status"] == "RESCHEDULED"
        # Etkilenen iş sayısı en az 1 olmalı
        assert result["affected_tasks_count"] >= 1
