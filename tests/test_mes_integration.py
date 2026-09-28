"""
tests/test_mes_integration.py
MES Entegrasyon ve Kapalı Çevrim Geri Besleme (Execution Feedback) Test Süiti.
"""
import pytest
from src.integration.mes_service import MESIntegrationService
from src.utils.db import get_db_connection

def test_mes_tracking_initialization():
    service = MESIntegrationService()
    count = service.initialize_tracking_from_schedule()
    assert count > 0, "Aktif çizelgeden iş emirleri MES takip tablosuna aktarılamadı!"

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM mes_order_tracking WHERE run_id = ?;", (service.run_id,))
    db_count = cur.fetchone()[0]
    assert db_count == count, f"Tablodaki kayıt sayısı ({db_count}) beklenen ({count}) ile uyuşmuyor."

def test_mes_event_normal_execution():
    service = MESIntegrationService()
    service.initialize_tracking_from_schedule()

    # Task 1'in gerçek planlanan başlangıç dakikasını al
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT scheduled_start_min FROM mes_order_tracking WHERE task_id = 1 AND run_id = ?;", (service.run_id,))
    row = cur.fetchone()
    sched_start = row[0] if row else 0.0

    # Planlanan zamandan sadece 5 dakika sapma (normal tolerans içi)
    impact = service.record_event(
        event_type="TASK_START",
        machine_id="M01",
        event_timestamp_min=sched_start + 5.0,
        task_id=1
    )
    assert impact["reschedule_required"] is False, "Tolerans dahilindeki başlangıçta reschedule tetiklenmemeli."

def test_mes_event_critical_delay_triggers_reschedule():
    service = MESIntegrationService()
    service.initialize_tracking_from_schedule()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT scheduled_end_min FROM mes_order_tracking WHERE task_id = 1 AND run_id = ?;", (service.run_id,))
    row = cur.fetchone()
    sched_end = row[0] if row else 100.0

    # Planlanan bitişten 120 dakika gecikmeli tamamlanma bildirimi (> 60 dk eşiği)
    impact = service.record_event(
        event_type="TASK_COMPLETE",
        machine_id="M01",
        event_timestamp_min=sched_end + 120.0,
        task_id=1,
        delay_reason="Takım kırılması ve kalıp ayar gecikmesi"
    )
    assert impact["reschedule_required"] is True, "60 dakikayı aşan sapma yeniden çizelgeleme tetiklemeli."

def test_mes_machine_down_triggers_reschedule():
    service = MESIntegrationService()
    # M02 tezgahında plansız duruş
    impact = service.record_event(
        event_type="MACHINE_DOWN",
        machine_id="M02",
        event_timestamp_min=120.0,
        delay_reason="Hidrolik basınç kaybı"
    )
    assert impact["reschedule_required"] is True, "Makine arızası anında reschedule tetiklemeli."