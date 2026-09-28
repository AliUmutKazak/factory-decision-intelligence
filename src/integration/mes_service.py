"""
MES Integration & Execution Feedback Service
Sahadan (MES) gelen telemetri, iş başlatma/bitirme ve arıza (downtime)
olaylarını yönetir, sapmaları hesaplar ve kapalı çevrim tetikler.
"""
from typing import Dict, Any, Optional
import pandas as pd
from src.utils.db import get_db_connection

class MESIntegrationService:
    def __init__(self, run_id: Optional[str] = None):
        self.conn = get_db_connection()
        self.run_id = run_id or self._get_active_run_id()

    def _get_active_run_id(self) -> str:
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1;")
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT run_id FROM pipeline_runs ORDER BY timestamp DESC LIMIT 1;")
                row = cur.fetchone()
            return row[0] if row else "DEFAULT_RUN"
        finally:
            cur.close()

    def initialize_tracking_from_schedule(self) -> int:
        """
        Aktif 'production_schedule' verilerini alıp 'mes_order_tracking' tablosuna aktarır.
        """
        # run_id kolonu tabloda var mı dinamik kontrol et
        cur = self.conn.cursor()
        cur.execute("PRAGMA table_info(production_schedule);")
        sched_cols = [c[1] for c in cur.fetchall()]
        cur.close()

        has_run_id = "run_id" in sched_cols

        if has_run_id:
            df_schedule = pd.read_sql_query(
                "SELECT task_id, lot_id, product_id, machine_id, start_min, end_min FROM production_schedule WHERE run_id = ?;",
                self.conn,
                params=(self.run_id,)
            )
            if df_schedule.empty:
                df_schedule = pd.read_sql_query(
                    "SELECT task_id, lot_id, product_id, machine_id, start_min, end_min FROM production_schedule;",
                    self.conn
                )
        else:
            df_schedule = pd.read_sql_query(
                "SELECT task_id, lot_id, product_id, machine_id, start_min, end_min FROM production_schedule;",
                self.conn
            )

        if df_schedule.empty:
            return 0

        cur = self.conn.cursor()
        try:
            cur.execute("DELETE FROM mes_order_tracking WHERE run_id = ?;", (self.run_id,))

            insert_data = [
                (
                    int(row["task_id"]),
                    self.run_id,
                    str(row["lot_id"]),
                    str(row["product_id"]),
                    str(row["machine_id"]),
                    float(row["start_min"]),
                    float(row["end_min"]),
                    "SCHEDULED",
                    0.0
                )
                for _, row in df_schedule.iterrows()
            ]

            cur.executemany("""
                INSERT OR REPLACE INTO mes_order_tracking (
                    task_id, run_id, lot_id, product_id, machine_id,
                    scheduled_start_min, scheduled_end_min, status, variance_min
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, insert_data)

            self.conn.commit()
            return len(insert_data)
        finally:
            cur.close()

    def record_event(
        self,
        event_type: str,
        machine_id: str,
        event_timestamp_min: float,
        task_id: Optional[int] = None,
        delay_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        MES olayını kaydeder (TASK_START, TASK_COMPLETE, MACHINE_DOWN vb.)
        ve sapmaya göre yeniden çizelgeleme gerekip gerekmediğini değerlendirir.
        """
        cur = self.conn.cursor()
        try:
            # Doğru kolon adı: event_timestamp_min
            cur.execute("""
                INSERT INTO mes_execution_events (
                    run_id, event_type, machine_id, task_id, event_timestamp_min, delay_reason
                ) VALUES (?, ?, ?, ?, ?, ?);
            """, (self.run_id, event_type, machine_id, task_id, event_timestamp_min, delay_reason))

            trigger_reschedule = False
            variance = 0.0

            if event_type == "TASK_START" and task_id is not None:
                cur.execute(
                    "SELECT scheduled_start_min FROM mes_order_tracking WHERE task_id = ? AND run_id = ?;",
                    (task_id, self.run_id)
                )
                row = cur.fetchone()
                if row:
                    variance = event_timestamp_min - float(row[0])
                    cur.execute("""
                        UPDATE mes_order_tracking
                        SET actual_start_min = ?, status = 'IN_PROGRESS', variance_min = ?
                        WHERE task_id = ? AND run_id = ?;
                    """, (event_timestamp_min, variance, task_id, self.run_id))
                    if variance > 60.0:
                        trigger_reschedule = True

            elif event_type == "TASK_COMPLETE" and task_id is not None:
                cur.execute(
                    "SELECT scheduled_end_min FROM mes_order_tracking WHERE task_id = ? AND run_id = ?;",
                    (task_id, self.run_id)
                )
                row = cur.fetchone()
                if row:
                    variance = event_timestamp_min - float(row[0])
                    cur.execute("""
                        UPDATE mes_order_tracking
                        SET actual_end_min = ?, status = 'COMPLETED', variance_min = ?
                        WHERE task_id = ? AND run_id = ?;
                    """, (event_timestamp_min, variance, task_id, self.run_id))
                    if variance > 60.0:
                        trigger_reschedule = True

            elif event_type == "MACHINE_DOWN":
                trigger_reschedule = True

            self.conn.commit()

            return {
                "status": "RECORDED",
                "event_type": event_type,
                "variance_min": variance,
                "trigger_reschedule": trigger_reschedule,
                "reschedule_required": trigger_reschedule
            }
        finally:
            cur.close()

    def close(self):
        if hasattr(self, "conn") and self.conn:
            try:
                self.conn.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()