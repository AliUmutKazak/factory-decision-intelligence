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

from ortools.sat.python import cp_model
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

    def _solve_cpsat_reschedule(
        self,
        df: pd.DataFrame,
        machine_id: str,
        down_start_min: float,
        down_duration_min: float,
        time_limit_sec: float = 10.0,
    ) -> pd.DataFrame | None:
        """Majör arıza durumunda serbest görevleri CP-SAT ile yeniden optimize eder."""
        model = cp_model.CpModel()
        down_end_min = down_start_min + down_duration_min
        horizon = int(df["end_min"].max() + down_duration_min * 2 + 1440)

        task_vars = {}
        machine_intervals = {m: [] for m in df["machine_id"].unique()}

        down_start_int = int(down_start_min)
        down_dur_int = int(down_duration_min)
        down_interval = model.NewFixedSizeIntervalVar(down_start_int, down_dur_int, f"breakdown_{machine_id}")
        if machine_id in machine_intervals:
            machine_intervals[machine_id].append(down_interval)

        for _, row in df.iterrows():
            tid = str(row["task_id"])
            dur = max(1, int(row["duration_min"]))
            m = row["machine_id"]
            orig_start = int(row["start_min"])
            orig_end = int(row["end_min"])

            if orig_end <= down_start_min:
                start_var = model.NewConstant(orig_start)
                end_var = model.NewConstant(orig_end)
                interval_var = model.NewFixedSizeIntervalVar(orig_start, dur, f"task_{tid}")
            elif orig_start < down_start_min < orig_end:
                new_dur = dur + down_dur_int
                start_var = model.NewConstant(orig_start)
                end_var = model.NewConstant(orig_start + new_dur)
                interval_var = model.NewFixedSizeIntervalVar(orig_start, new_dur, f"task_{tid}")
            else:
                start_var = model.NewIntVar(0, horizon, f"start_{tid}")
                end_var = model.NewIntVar(0, horizon, f"end_{tid}")
                interval_var = model.NewIntervalVar(start_var, dur, end_var, f"task_{tid}")

                # Stabilite kuralı: İşler eski başlangıçlarından daha erkene çekilemez
                model.Add(start_var >= orig_start)

                if m == machine_id:
                    model.Add(start_var >= int(down_end_min))

            task_vars[tid] = {"start": start_var, "end": end_var, "interval": interval_var}
            if m in machine_intervals:
                machine_intervals[m].append(interval_var)

        for m, intervals in machine_intervals.items():
            model.AddNoOverlap(intervals)

        for _, lot_tasks in df.groupby("lot_id"):
            sorted_tasks = lot_tasks.sort_values("operation_seq")
            task_ids = sorted_tasks["task_id"].astype(str).tolist()
            for i in range(len(task_ids) - 1):
                prev_tid = task_ids[i]
                next_tid = task_ids[i + 1]
                if prev_tid in task_vars and next_tid in task_vars:
                    model.Add(task_vars[next_tid]["start"] >= task_vars[prev_tid]["end"])

        makespan = model.NewIntVar(int(df["end_min"].max()), horizon, "makespan")
        for tv in task_vars.values():
            model.Add(makespan >= tv["end"])
        model.Minimize(makespan)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_sec
        solver.parameters.num_workers = 4
        status = solver.Solve(model)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            df_opt = df.copy()
            for idx, row in df_opt.iterrows():
                tid = str(row["task_id"])
                if tid in task_vars:
                    df_opt.loc[idx, "start_min"] = float(solver.Value(task_vars[tid]["start"]))
                    df_opt.loc[idx, "end_min"] = float(solver.Value(task_vars[tid]["end"]))
            return df_opt

        return None

    def reschedule_on_machine_breakdown(
        self,
        machine_id: str,
        down_start_min: float,
        down_duration_min: float,
        reason: str = "Unplanned Breakdown",
        force_heuristic: bool = False,
        commit: bool = True,
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

        # Majör arızalarda CP-SAT re-optimization çalıştırılır
        if is_major_disruption:
            opt_df = self._solve_cpsat_reschedule(
                df=df_schedule.copy(),
                machine_id=machine_id,
                down_start_min=down_start_min,
                down_duration_min=down_duration_min,
            )
            if opt_df is not None:
                df = opt_df

        new_makespan = float(df["end_min"].max())
        delta_makespan = max(0.0, new_makespan - old_makespan)

        # ---------------------------------------------------------------------
        # MADDE 19: Closed-Loop DB Persistence (Source of Truth Synchronization)
        # ---------------------------------------------------------------------
        if commit:
            cur = self.conn.cursor()
            for _, row in df.iterrows():
                cur.execute(
                    """
                    UPDATE production_schedule
                    SET start_min = ?,
                        end_min = ?
                    WHERE run_id = ? AND task_id = ?;
                    """,
                    (
                        float(row["start_min"]),
                        float(row["end_min"]),
                        self.run_id,
                        str(row["task_id"]),
                    ),
                )

            # 3. Olayı mes_execution_events tablosuna yaz
            cur.execute(
                """
                INSERT INTO mes_execution_events (
                    run_id, machine_id, event_type, event_timestamp_min,
                    actual_duration_min, delay_reason
                ) VALUES (?, ?, 'MACHINE_DOWN', ?, ?, ?);
                """,
                (
                    self.run_id,
                    machine_id,
                    down_start_min,
                    down_duration_min,
                    f"[{reschedule_mode}] {reason}",
                ),
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
