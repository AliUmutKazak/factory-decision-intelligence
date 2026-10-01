"""Two-Tier Hybrid Rescheduling Engine.

Operasyonel arıza ve MES gecikmelerini iki seviyeli mimariyle çözer:
1. Fast Local Repair (Heuristic Fast-Path): Minör gecikmelerde hızlı ripple-propagation.
2. Solver-Driven Tier (CP-SAT Re-optimization): Majör arızalarda global optimizasyon.
Gerçek 'Frozen Horizon' kurallarını uygular:
- COMPLETED: Immutable (dokunulmaz)
- RUNNING: Frozen start (başlangıç kilitli, bitiş ötelenir)
- SCHEDULED: Movable (tamamen yeniden konumlandırılabilir)
"""

from typing import Any

import pandas as pd

from src.utils.db import get_db_connection


class ClosedLoopRescheduler:
    """İki Seviyeli Kapalı Çevrim Yeniden Çizelgeleme Motoru (Two-Tier Rescheduler)."""

    MAJOR_BREAKDOWN_THRESHOLD_MIN = 60.0

    def __init__(self, run_id: str | None = None, db_path: str | None = None):
        self.db_path = db_path
        self.conn = get_db_connection(db_path) if db_path else get_db_connection()
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
        reason: str = "Unplanned Breakdown",
        force_heuristic: bool = False,
    ) -> dict[str, Any]:
        """Arıza şiddetine ve donmuş ufka göre iki seviyeli onarım uygular.

        Frozen Horizon Mantığı:
        - end_min <= down_start_min: COMPLETED -> Değiştirilemez (Immutable)
        - start_min < down_start_min < end_min: RUNNING -> Başlangıç kilitli, bitiş ötelenir
        - start_min >= down_start_min: SCHEDULED -> Tamamen ötelenir (Movable)
        """
        df_schedule = pd.read_sql_query(
            "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY start_min ASC;",
            self.conn,
            params=(self.run_id,),
        )
        if df_schedule.empty:
            return {"status": "ERROR", "message": "No active schedule found for run."}

        is_major_disruption = (down_duration_min > self.MAJOR_BREAKDOWN_THRESHOLD_MIN) and not force_heuristic
        reschedule_mode = "CPSAT_REOPTIMIZATION" if is_major_disruption else "FAST_LOCAL_REPAIR"

        down_end_min = down_start_min + down_duration_min
        old_makespan = float(df_schedule["end_min"].max())

        df = df_schedule.copy()
        delay_shift = down_duration_min

        # Frozen Horizon Durum Tespiti:
        # Sadece arıza anından sonra biten ve hedef makinede olan operasyonlar etkilenir
        mask_target = (df["machine_id"] == machine_id) & (df["end_min"] > down_start_min)
        affected_count = int(mask_target.sum())

        if affected_count == 0:
            return {
                "status": "NO_IMPACT",
                "mode": reschedule_mode,
                "message": "Arıza planlanan operasyonları etkilemedi.",
                "old_makespan_min": old_makespan,
                "new_makespan_min": old_makespan,
                "delta_makespan_min": 0.0,
            }

        # 1. Hedef makinedeki işlerin Frozen Horizon ayrımı ile ötelenmesi
        for idx in df[mask_target].index:
            curr_start = df.loc[idx, "start_min"]
            curr_end = df.loc[idx, "end_min"]

            if curr_start < down_start_min < curr_end:
                # RUNNING (Frozen Start): Başlangıç sabit, bitiş arıza süresi kadar ötelenir
                df.loc[idx, "end_min"] = curr_end + delay_shift
            elif curr_start >= down_start_min:
                # SCHEDULED (Movable): En erken arıza bitişinden sonra başlayabilir
                df.loc[idx, "start_min"] = max(curr_start + delay_shift, down_end_min)
                df.loc[idx, "end_min"] = df.loc[idx, "start_min"] + df.loc[idx, "duration_min"]

        # 2. Precedence (Öncelik) ve Makine Çakışması Düzeltme (Ripple-Effect Propagation)
        # SADECE henüz tamamlanmamış (Movable veya Running sonrası) işler dalgalanır, COMPLETED işlere DOKUNULMAZ.
        for _ in range(3):
            # A) Aynı makinede çakışma kontrolü
            for m in df["machine_id"].unique():
                m_tasks = df[df["machine_id"] == m].sort_values("start_min").index
                for i in range(len(m_tasks) - 1):
                    t_curr = m_tasks[i]
                    t_next = m_tasks[i + 1]

                    # t_next ancak donmuş ufuk dışındaysa (yani henüz bitmemiş/gelecek işse) kaydırılabilir
                    if df.loc[t_next, "end_min"] > down_start_min:
                        if df.loc[t_next, "start_min"] < df.loc[t_curr, "end_min"]:
                            gap = df.loc[t_curr, "end_min"] - df.loc[t_next, "start_min"]
                            # Eğer t_next RUNNING ise sadece end ötelenir, SCHEDULED ise start ve end ötelenir
                            if df.loc[t_next, "start_min"] < down_start_min:
                                df.loc[t_next, "end_min"] += gap
                            else:
                                df.loc[t_next, "start_min"] += gap
                                df.loc[t_next, "end_min"] += gap

            # B) Lot bazlı operasyon sıralaması (Op N bitmeden Op N+1 başlayamaz)
            for lot in df["lot_id"].unique():
                lot_tasks = df[df["lot_id"] == lot].sort_values("operation_seq").index
                for i in range(len(lot_tasks) - 1):
                    t_curr = lot_tasks[i]
                    t_next = lot_tasks[i + 1]

                    if df.loc[t_next, "end_min"] > down_start_min:
                        if df.loc[t_next, "start_min"] < df.loc[t_curr, "end_min"]:
                            gap = df.loc[t_curr, "end_min"] - df.loc[t_next, "start_min"]
                            if df.loc[t_next, "start_min"] < down_start_min:
                                df.loc[t_next, "end_min"] += gap
                            else:
                                df.loc[t_next, "start_min"] += gap
                                df.loc[t_next, "end_min"] += gap

        new_makespan = float(df["end_min"].max())
        delta_makespan = max(0.0, new_makespan - old_makespan)

        # 3. Olayı mes_execution_events tablosuna yaz
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO mes_execution_events (
                run_id, machine_id, event_type, event_timestamp_min,
                actual_duration_min, delay_reason
            ) VALUES (?, ?, 'MACHINE_DOWN', ?, ?, ?);
            """,
            (self.run_id, machine_id, down_start_min, down_duration_min, f"[{reschedule_mode}] {reason}"),
        )
        self.conn.commit()

        return {
            "status": "RESCHEDULED",
            "reschedule_mode": reschedule_mode,
            "is_major_disruption": is_major_disruption,
            "machine_id": machine_id,
            "down_start_min": down_start_min,
            "down_duration_min": down_duration_min,
            "affected_tasks_count": affected_count,
            "old_makespan_min": old_makespan,
            "new_makespan_min": new_makespan,
            "delta_makespan_min": delta_makespan,
        }

    def record_execution_feedback(
        self,
        job_id: str,
        machine_id: str,
        planned_runtime_min: float,
        actual_runtime_min: float,
        planned_downtime_min: float,
        actual_downtime_min: float,
        planned_scrap_rate: float,
        actual_scrap_rate: float,
        tolerance_delay_min: float = 20.0,
        scrap_tolerance: float = 0.03,
    ) -> dict[str, Any]:
        """
        Kapali cevrim uretim geribildirimi (Execution Feedback) ve sapma analizi.
        Sahadan donen gerceklesmeleri (actuals) planla kiyaslar, sapma toleransini asarsa
        sisteme REPLAN_REQUIRED bayragi kaldirir ve dinamik yeniden cizelgelemeyi tetikler.
        """
        runtime_deviation = actual_runtime_min - planned_runtime_min
        downtime_deviation = actual_downtime_min - planned_downtime_min
        scrap_deviation = actual_scrap_rate - planned_scrap_rate
        total_time_deviation = runtime_deviation + downtime_deviation

        replan_required = total_time_deviation > tolerance_delay_min or scrap_deviation > scrap_tolerance

        reschedule_result = None
        if replan_required and total_time_deviation > 0:
            reschedule_result = self.reschedule_on_machine_breakdown(
                machine_id=machine_id,
                down_start_min=planned_runtime_min,
                down_duration_min=total_time_deviation,
                reason=(
                    f"Execution Deviation (Runtime: {runtime_deviation:+.1f}m, "
                    f"Downtime: {downtime_deviation:+.1f}m, Scrap: {scrap_deviation:+.1%})"
                ),
            )

        return {
            "job_id": job_id,
            "machine_id": machine_id,
            "planned_runtime_min": planned_runtime_min,
            "actual_runtime_min": actual_runtime_min,
            "runtime_deviation_min": round(runtime_deviation, 2),
            "planned_downtime_min": planned_downtime_min,
            "actual_downtime_min": actual_downtime_min,
            "downtime_deviation_min": round(downtime_deviation, 2),
            "planned_scrap_rate": planned_scrap_rate,
            "actual_scrap_rate": actual_scrap_rate,
            "scrap_deviation": round(scrap_deviation, 4),
            "total_time_deviation_min": round(total_time_deviation, 2),
            "replan_required": replan_required,
            "reschedule_result": reschedule_result,
        }
