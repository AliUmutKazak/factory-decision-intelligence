"""
tests/test_rescheduler.py
Closed-Loop Dynamic Rescheduling motorunun test süiti.
"""
import pytest
from src.integration.rescheduler import ClosedLoopRescheduler
from src.utils.db import get_db_connection

def test_closed_loop_machine_breakdown_impact():
    rescheduler = ClosedLoopRescheduler()
    
    # M01 tezgahında 500. dakikada 120 dakikalık plansız duruş senaryosu
    result = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01",
        down_start_min=500.0,
        down_duration_min=120.0,
        reason="Acil Rulman Değişimi"
    )

    assert result["status"] == "RESCHEDULED"
    assert result["affected_tasks_count"] > 0
    assert result["new_makespan_min"] >= result["old_makespan_min"]
    assert result["delta_makespan_min"] >= 0.0

def test_reschedule_event_persisted_to_db():
    rescheduler = ClosedLoopRescheduler()
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT COUNT(*) FROM mes_execution_events 
        WHERE run_id = ? AND event_type = 'MACHINE_DOWN';
    """, (rescheduler.run_id,))
    count_before = cur.fetchone()[0]

    rescheduler.reschedule_on_machine_breakdown(
        machine_id="M02",
        down_start_min=800.0,
        down_duration_min=60.0,
        reason="Sensör Kalibrasyon Hatası"
    )

    cur.execute("""
        SELECT COUNT(*) FROM mes_execution_events 
        WHERE run_id = ? AND event_type = 'MACHINE_DOWN';
    """, (rescheduler.run_id,))
    count_after = cur.fetchone()[0]
    
    assert count_after == count_before + 1, "Arıza olayı mes_execution_events tablosuna kaydedilmedi."