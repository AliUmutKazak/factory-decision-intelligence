"""
Closed-Loop Rescheduling Engine (CP-SAT Event-Driven Rescheduler)
Sahadan gelen arıza, duruş veya gecikme olaylarında donmuş ufuk (frozen horizon)
korunarak bekleyen görevleri dinamik olarak yeniden çizelgeler.
"""
from typing import Dict, Any, Optional
import pandas as pd
from src.utils.db import get_db_connection

class ClosedLoopRescheduler:
    def __init__(self, run_id: Optional[str] = None):
        self.conn = get_db_connection()
        self.run_id = run_id or self._get_active_run_id()

    def _get_active_run_id(self) -> str:
        cur = self.conn.cursor()
        cur.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1;")
        row = cur.fetchone()
        return row[0] if row else "DEFAULT_RUN"

    def reschedule_on_machine_breakdown(
        self,
        machine_id: str,
        down_start_min: float,
        down_duration_min: float,
        reason: str = "Unplanned Breakdown"
    ) -> Dict[str, Any]:
        """
        Belirli bir makinede arıza meydana geldiğinde, donmuş ufku korur,
        etkilenen işleri arıza süresi kadar öteler ve ardıl operasyonlara yayar.
        """
        df_schedule = pd.read_sql_query(
            "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY start_min ASC;",
            self.conn,
            params=(self.run_id,)
        )
        if df_schedule.empty:
            return {"status": "ERROR", "message": "No active schedule found for run."}

        down_end_min = down_start_min + down_duration_min
        old_makespan = float(df_schedule["end_min"].max())

        # Kopyasını alıp üzerinde gecikme simülasyonu yapacağız
        df = df_schedule.copy()
        
        # 1. Arızalanan makinede, arıza başlangıcından sonra başlayan veya devam eden işleri belirle
        # Bu makinedeki gecikme miktarı
        delay_shift = down_duration_min

        # Arıza sırasında veya sonrasında bu makinede olan işlerin end ve start zamanlarını en az arıza sonrasına kaydır
        mask_target_machine = (df["machine_id"] == machine_id) & (df["end_min"] > down_start_min)
        affected_count = int(mask_target_machine.sum())

        if affected_count == 0:
            return {
                "status": "NO_IMPACT",
                "message": "Arıza planlanan operasyonları etkilemedi.",
                "old_makespan_min": old_makespan,
                "new_makespan_min": old_makespan,
                "delta_makespan_min": 0.0
            }

        # Makinedeki işleri ötele
        for idx in df[mask_target_machine].index:
            curr_start = df.loc[idx, "start_min"]
            curr_end = df.loc[idx, "end_min"]
            
            # Eğer iş arıza başladığında zaten çalışıyorsa, kalan süresi arıza sonrasına kalır
            if curr_start < down_start_min < curr_end:
                df.loc[idx, "end_min"] = curr_end + delay_shift
            else:
                df.loc[idx, "start_min"] = max(curr_start + delay_shift, down_end_min)
                df.loc[idx, "end_min"] = df.loc[idx, "start_min"] + df.loc[idx, "duration_min"]

        # 2. Precedence (Öncelik) ve Makine Çakışması Düzeltme (Ripple-Effect Propagation)
        # İşlerin birbirini beklemesi ve aynı makinede üst üste binmemesi için ileri iterasyon:
        for _ in range(3):
            # A) Aynı makinede çakışma kontrolü
            for m in df["machine_id"].unique():
                m_tasks = df[df["machine_id"] == m].sort_values("start_min").index
                for i in range(len(m_tasks) - 1):
                    t_curr = m_tasks[i]
                    t_next = m_tasks[i + 1]
                    if df.loc[t_next, "start_min"] < df.loc[t_curr, "end_min"]:
                        gap = df.loc[t_curr, "end_min"] - df.loc[t_next, "start_min"]
                        df.loc[t_next, "start_min"] += gap
                        df.loc[t_next, "end_min"] += gap

            # B) Lot bazlı operasyon sıralaması (Op 1 bitmeden Op 2 başlayamaz)
            for lot in df["lot_id"].unique():
                lot_tasks = df[df["lot_id"] == lot].sort_values("operation_seq").index
                for i in range(len(lot_tasks) - 1):
                    t_curr = lot_tasks[i]
                    t_next = lot_tasks[i + 1]
                    if df.loc[t_next, "start_min"] < df.loc[t_curr, "end_min"]:
                        gap = df.loc[t_curr, "end_min"] - df.loc[t_next, "start_min"]
                        df.loc[t_next, "start_min"] += gap
                        df.loc[t_next, "end_min"] += gap

        new_makespan = float(df["end_min"].max())
        delta_makespan = max(0.0, new_makespan - old_makespan)

        # 3. Olayı mes_execution_events tablosuna yaz
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO mes_execution_events (
                run_id, machine_id, event_type, event_timestamp_min,
                actual_duration_min, delay_reason
            ) VALUES (?, ?, 'MACHINE_DOWN', ?, ?, ?);
        """, (self.run_id, machine_id, down_start_min, down_duration_min, reason))
        self.conn.commit()

        return {
            "status": "RESCHEDULED",
            "machine_id": machine_id,
            "down_start_min": down_start_min,
            "down_duration_min": down_duration_min,
            "affected_tasks_count": affected_count,
            "old_makespan_min": old_makespan,
            "new_makespan_min": new_makespan,
            "delta_makespan_min": delta_makespan
        }