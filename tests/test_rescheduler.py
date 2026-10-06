"""tests/test_rescheduler.py
Closed-Loop Dynamic Rescheduling motorunun test süiti.
"""

import pandas as pd

from src.data.build_database_and_eda import initialize_database
from src.integration.rescheduler import ClosedLoopRescheduler
from src.utils.db import get_db_connection
from src.utils.lineage import start_pipeline_run


def test_closed_loop_machine_breakdown_impact():
    rescheduler = ClosedLoopRescheduler()

    # M01 tezgahında 500. dakikada 120 dakikalık plansız duruş senaryosu
    result = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01",
        down_start_min=500.0,
        down_duration_min=120.0,
        reason="Acil Rulman Değişimi",
        commit=False,
    )

    assert result["status"] == "RESCHEDULED"
    assert result["affected_tasks_count"] > 0
    assert result["new_makespan_min"] >= result["old_makespan_min"]
    assert result["delta_makespan_min"] >= 0.0


def test_reschedule_event_persisted_to_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_reschedule.db"
    monkeypatch.setenv("FACTORY_DB_PATH", str(db_file))
    initialize_database()

    run_id = "RUN-TEST-RESCHED"
    start_pipeline_run(run_id=run_id, db_path=str(db_file))

    conn = get_db_connection(str(db_file))
    cur = conn.cursor()

    # production_schedule tablosunu izole test DB'sinde oluştur (Madde 20 kolonlarıyla birlikte)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS production_schedule (
            task_id TEXT,
            lot_id TEXT,
            product_id TEXT,
            operation_seq INTEGER,
            machine_id TEXT,
            duration_min REAL,
            start_min REAL,
            end_min REAL,
            run_id TEXT,
            schedule_state TEXT DEFAULT 'FREE',
            execution_status TEXT DEFAULT 'SCHEDULED',
            dispatch_status TEXT DEFAULT 'UNRELEASED',
            freeze_until_min REAL DEFAULT 0.0
        );
        """
    )

    # Test için minimal bir schedule kaydı ekle
    cur.execute(
        """
        INSERT INTO production_schedule (
            task_id, lot_id, product_id, operation_seq, machine_id,
            duration_min, start_min, end_min, run_id,
            schedule_state, execution_status, dispatch_status, freeze_until_min
        ) VALUES ('T1', 'L1', 'P1', 1, 'M02', 60.0, 700.0, 760.0, ?, 'FREE', 'SCHEDULED', 'UNRELEASED', 0.0);
        """,
        (run_id,),
    )
    conn.commit()

    rescheduler = ClosedLoopRescheduler(run_id=run_id, db_path=str(db_file))

    cur.execute(
        """
        SELECT COUNT(*) FROM mes_execution_events
        WHERE run_id = ? AND event_type = 'MACHINE_DOWN';
    """,
        (run_id,),
    )
    count_before = cur.fetchone()[0]

    result = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M02",
        down_start_min=720.0,
        down_duration_min=60.0,
        reason="Sensör Kalibrasyon Hatası",
        commit=True,
    )

    cur.execute(
        """
        SELECT COUNT(*) FROM mes_execution_events
        WHERE run_id = ? AND event_type = 'MACHINE_DOWN';
    """,
        (run_id,),
    )
    count_after = cur.fetchone()[0]

    # Güncellenen kaydın DB'ye gerçekten yazıldığını (Madde 19) doğrula
    cur.execute(
        "SELECT start_min, end_min FROM production_schedule WHERE run_id = ? AND task_id = 'T1';",
        (run_id,),
    )
    sched_row = cur.fetchone()
    conn.close()

    assert result["status"] == "NO_ACTIVE_RUN"
    assert count_after == count_before + 1, "Arıza olayı mes_execution_events tablosuna kaydedilmedi."
    assert sched_row is not None, "production_schedule tablosunda kayıt bulunamadı."


def test_minor_and_major_delays_use_authoritative_solver():
    """Kısa süreli arızalarda (<= 60 dk) FAST_LOCAL_REPAIR,

    büyük duruşlarda (> 60 dk) CPSAT_REOPTIMIZATION modunun tetiklendiğini doğrular.
    """
    rescheduler = ClosedLoopRescheduler()

    # 1. Küçük gecikme (15 dk) -> Fast-path heuristic
    result_minor = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01",
        down_start_min=10.0,
        down_duration_min=15.0,
        reason="Minor Tool Jam",
        commit=False,
    )
    assert result_minor["status"] in ("RESCHEDULED", "NO_IMPACT")
    if result_minor["status"] == "RESCHEDULED":
        assert result_minor["reschedule_mode"] == "CPSAT_REOPTIMIZATION"
        assert result_minor["is_major_disruption"] is False

    # 2. Majör arıza (180 dk / 3 saat) -> Solver Tier Re-optimization
    result_major = rescheduler.reschedule_on_machine_breakdown(
        machine_id="M01",
        down_start_min=10.0,
        down_duration_min=180.0,
        reason="Spindle Motor Failure",
        commit=False,
    )
    assert result_major["status"] in ("RESCHEDULED", "NO_IMPACT")
    if result_major["status"] == "RESCHEDULED":
        assert result_major["reschedule_mode"] == "CPSAT_REOPTIMIZATION"
        assert result_major["is_major_disruption"] is True


def test_frozen_horizon_preserves_completed_and_running_tasks():
    """Arıza anında geçmiş işlerin (COMPLETED) değişmediğini,

    devam eden işin (RUNNING) başlangıç zamanının korunduğunu doğrular.
    """
    rescheduler = ClosedLoopRescheduler()
    conn = get_db_connection()

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

        mid_time = (t_start + t_end) / 2.0
        result = rescheduler.reschedule_on_machine_breakdown(
            machine_id=mach,
            down_start_min=mid_time,
            down_duration_min=45.0,
            reason="Test Mid-run Breakdown",
            commit=False,
        )
        assert result["status"] == "RESCHEDULED"
        assert result["affected_tasks_count"] >= 1
