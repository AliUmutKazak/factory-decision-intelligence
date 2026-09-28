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
        cur.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1;")
        row = cur.fetchone()
        return row[0] if row else "DEFAULT_RUN"

    def initialize_tracking_from_schedule(self) -> int:
        """
        Aktif 'production_schedule' verilerini alıp 'mes_order_tracking' tablosuna aktarır.
        """
        df_schedule = pd.read_sql_query(
            "SELECT task_id, lot_id, product_id, machine_id, start_min, end_min, run_id FROM production_schedule WHERE run_id = ?;",
            self.conn,
            params=(self.run_id,)
        )
        if df_schedule.empty:
            return 0

        cur = self.conn.cursor()
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
            INSERT INTO mes_order_tracking (
                task_id, run_id, lot_id, product_id, machine_id,
                scheduled_start_min, scheduled_end_min, status, variance_min
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, insert_data)

        self.conn.commit()
        return len(insert_data)

    def record_event(
        self,
        event_type: str,
        machine_id: str,
        event_timestamp_min: float,
        task_id: Optional[int] = None,
        actual_duration_min: Optional[float] = None,
        delay_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sahadan gelen bir MES olayını kaydeder ve durum güncellemesi yapar.
        """
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO mes_execution_events (
                run_id, task_id, machine_id, event_type,
                event_timestamp_min, actual_duration_min, delay_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (self.run_id, task_id, machine_id, event_type, event_timestamp_min, actual_duration_min, delay_reason))

        impact = {"event_type": event_type, "reschedule_required": False, "variance_min": 0.0}

        if task_id is not None:
            if event_type == "TASK_START":
                cur.execute("""
                    UPDATE mes_order_tracking
                    SET actual_start_min = ?,
                        status = 'IN_PROGRESS',
                        variance_min = ? - scheduled_start_min,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE task_id = ?;
                """, (event_timestamp_min, event_timestamp_min, task_id))
            
            elif event_type == "TASK_COMPLETE":
                cur.execute("""
                    UPDATE mes_order_tracking
                    SET actual_end_min = ?,
                        status = 'COMPLETED',
                        variance_min = ? - scheduled_end_min,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE task_id = ?;
                """, (event_timestamp_min, event_timestamp_min, task_id))

            cur.execute("SELECT variance_min FROM mes_order_tracking WHERE task_id = ?;", (task_id,))
            row = cur.fetchone()
            if row and abs(row[0]) > 60.0:
                impact["reschedule_required"] = True
                impact["variance_min"] = row[0]

        elif event_type == "MACHINE_DOWN":
            impact["reschedule_required"] = True
            impact["delay_reason"] = delay_reason

        self.conn.commit()
        return impact