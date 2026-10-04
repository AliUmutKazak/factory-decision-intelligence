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
        try:
            cur.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1;")
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0])
        except Exception:
            pass

        # pipeline_runs yoksa veya boşsa production_schedule üzerindeki en son run_id'ye bak
        try:
            cur.execute("SELECT run_id FROM production_schedule LIMIT 1;")
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0])
        except Exception:
            pass

        return "DEFAULT_RUN"

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
        event_type: str = "MACHINE_DOWN",
        force_heuristic: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Madde 21: Two-Tier Dynamic Rescheduling Engine.

        Tier 1 (Fast Local Repair): Minor breakdowns, delays, scrap.
        Tier 2 (Full Reoptimization): Major breakdowns, capacity loss, crises.
        Rolling Horizon: [FROZEN: 0-4h], [FLEXIBLE: 4-24h], [FREE: 24h+].
        """
        # Aktif çizelgeyi veritabanından çek
        df = pd.read_sql_query(
            "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY start_min ASC;",
            self.conn,
            params=(self.run_id,),
        )

        if df.empty:
            return {
                "status": "NO_SCHEDULE_FOUND",
                "affected_tasks_count": 0,
                "old_makespan_min": 0.0,
                "new_makespan_min": 0.0,
                "delta_makespan_min": 0.0,
                "reschedule_mode": "NONE",
            }

        old_makespan = float(df["end_min"].max()) if not df.empty else 0.0

        mask_target = (df["machine_id"] == machine_id) & (df["end_min"] > down_start_min)
        affected_count = int(mask_target.sum())

        if affected_count == 0:
            return {
                "status": "NO_IMPACT",
                "affected_tasks_count": 0,
                "old_makespan_min": old_makespan,
                "new_makespan_min": old_makespan,
                "delta_makespan_min": 0.0,
                "reschedule_mode": "NONE",
            }

        # ---------------------------------------------------------------------
        # MADDE 21: Tier Selection Logic
        # Tier 1: Minor delays/breakdowns (<= 60 min) -> Fast Local Repair
        # Tier 2: Major breakdowns (> 60 min) / Crises -> CP-SAT Reoptimization
        # ---------------------------------------------------------------------
        is_major_disruption = (
            (down_duration_min > 60.0)
            or (
                event_type
                in (
                    "MAJOR_BREAKDOWN",
                    "LARGE_CAPACITY_LOSS",
                    "MATERIAL_CRISIS",
                    "LARGE_ORDER_INJECTION",
                )
            )
        ) and not force_heuristic

        reschedule_mode = "FAST_LOCAL_REPAIR"

        if is_major_disruption:
            df_cpsat = self._solve_cpsat_reschedule(
                df=df.copy(),
                machine_id=machine_id,
                down_start_min=down_start_min,
                down_duration_min=down_duration_min,
            )
            if df_cpsat is not None:
                df = df_cpsat
                reschedule_mode = "CPSAT_REOPTIMIZATION"

        # Tier 1 Fallback veya Doğrudan Tier 1 Fast Local Repair
        if reschedule_mode == "FAST_LOCAL_REPAIR":
            for idx in df[mask_target].index:
                t_start = df.at[idx, "start_min"]
                t_end = df.at[idx, "end_min"]

                # IN_PROGRESS (Başlangıç kilitli, bitiş ötelenir)
                if t_start <= down_start_min and t_end > down_start_min:
                    df.at[idx, "end_min"] = t_end + down_duration_min
                # İleriki işler (Tamamen sağa ötelenir)
                elif t_start > down_start_min:
                    df.at[idx, "start_min"] = t_start + down_duration_min
                    df.at[idx, "end_min"] = t_end + down_duration_min

            # Ripple-shift ardışıl operasyon ve makine çakışmalarını düzeltme
            changed = True
            while changed:
                changed = False
                for lot_id, group in df.groupby("lot_id"):
                    sorted_ops = group.sort_values("operation_seq").index.tolist()
                    for i in range(len(sorted_ops) - 1):
                        curr_idx = sorted_ops[i]
                        next_idx = sorted_ops[i + 1]
                        if df.at[next_idx, "start_min"] < df.at[curr_idx, "end_min"]:
                            dur = df.at[next_idx, "end_min"] - df.at[next_idx, "start_min"]
                            df.at[next_idx, "start_min"] = df.at[curr_idx, "end_min"]
                            df.at[next_idx, "end_min"] = df.at[next_idx, "start_min"] + dur
                            changed = True

                for m_id, group in df.groupby("machine_id"):
                    sorted_mach = group.sort_values("start_min").index.tolist()
                    for i in range(len(sorted_mach) - 1):
                        curr_idx = sorted_mach[i]
                        next_idx = sorted_mach[i + 1]
                        if df.at[next_idx, "start_min"] < df.at[curr_idx, "end_min"]:
                            dur = df.at[next_idx, "end_min"] - df.at[next_idx, "start_min"]
                            df.at[next_idx, "start_min"] = df.at[curr_idx, "end_min"]
                            df.at[next_idx, "end_min"] = df.at[next_idx, "start_min"] + dur
                            changed = True

        new_makespan = float(df["end_min"].max())
        delta_makespan = max(0.0, new_makespan - old_makespan)

        # ---------------------------------------------------------------------
        # MADDE 21: Rolling Horizon Assignment
        # [FROZEN]   0 - 4h   (0 - 240 dk)
        # [FLEXIBLE] 4 - 24h  (240 - 1440 dk)
        # [FREE]     24h+     (> 1440 dk)
        # ---------------------------------------------------------------------
        frozen_cutoff = down_start_min + 240.0  # 4 saat (240 dk)[cite: 2]
        flexible_cutoff = down_start_min + 1440.0  # 24 saat (1440 dk)[cite: 2]

        # COMPLETED (Geçmiş işler)
        mask_completed = df["end_min"] <= down_start_min
        df.loc[mask_completed, "execution_status"] = "COMPLETED"
        df.loc[mask_completed, "schedule_state"] = "FROZEN"

        # IN_PROGRESS (Duruş anında çalışanlar)
        mask_running = (df["start_min"] <= down_start_min) & (df["end_min"] > down_start_min)
        df.loc[mask_running, "execution_status"] = "IN_PROGRESS"
        df.loc[mask_running, "schedule_state"] = "FROZEN"

        # FROZEN (0 - 4 saat arası başlayacak işler)[cite: 2]
        mask_frozen = (df["start_min"] > down_start_min) & (df["start_min"] <= frozen_cutoff)
        df.loc[mask_frozen, "schedule_state"] = "FROZEN"
        df.loc[mask_frozen, "dispatch_status"] = "DISPATCHED"
        df.loc[mask_frozen, "freeze_until_min"] = frozen_cutoff

        # FLEXIBLE (4 - 24 saat arası başlayacak işler)[cite: 2]
        mask_flexible = (df["start_min"] > frozen_cutoff) & (df["start_min"] <= flexible_cutoff)
        df.loc[mask_flexible, "schedule_state"] = "FLEXIBLE"
        df.loc[mask_flexible, "dispatch_status"] = "UNRELEASED"
        df.loc[mask_flexible, "freeze_until_min"] = 0.0

        # FREE (24 saatten sonraki işler)[cite: 2]
        mask_free = df["start_min"] > flexible_cutoff
        df.loc[mask_free, "schedule_state"] = "FREE"
        df.loc[mask_free, "dispatch_status"] = "UNRELEASED"
        df.loc[mask_free, "freeze_until_min"] = 0.0

        # ---------------------------------------------------------------------
        # MADDE 19 & 20 & 21: DB Persistence
        # ---------------------------------------------------------------------
        if commit:
            cur = self.conn.cursor()
            for _, row in df.iterrows():
                cur.execute(
                    """
                    UPDATE production_schedule
                    SET start_min = ?,
                        end_min = ?,
                        schedule_state = ?,
                        execution_status = ?,
                        dispatch_status = ?,
                        freeze_until_min = ?
                    WHERE run_id = ? AND task_id = ?;
                    """,
                    (
                        float(row["start_min"]),
                        float(row["end_min"]),
                        str(row.get("schedule_state", "FREE")),
                        str(row.get("execution_status", "SCHEDULED")),
                        str(row.get("dispatch_status", "UNRELEASED")),
                        float(row.get("freeze_until_min", 0.0)),
                        self.run_id,
                        str(row["task_id"]),
                    ),
                )

            cur.execute(
                """
                INSERT INTO mes_execution_events (
                    run_id, machine_id, event_type, event_timestamp_min,
                    actual_duration_min, delay_reason
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    self.run_id,
                    machine_id,
                    event_type,
                    down_start_min,
                    down_duration_min,
                    f"[{reschedule_mode}] {reason}",
                ),
            )
            self.conn.commit()

        return {
            "status": "RESCHEDULED",
            "affected_tasks_count": affected_count,
            "old_makespan_min": old_makespan,
            "new_makespan_min": new_makespan,
            "delta_makespan_min": delta_makespan,
            "reschedule_mode": reschedule_mode,
            "is_major_disruption": is_major_disruption,
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
