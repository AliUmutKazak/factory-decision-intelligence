"""Dynamic Event-Driven Rescheduling, Audit Trail and Lineage Engine for CP-SAT (Faz 5)."""

import sqlite3
import uuid

import numpy as np
import pandas as pd

from src.config import get_runtime_paths
from src.contracts.schemas import (
    RescheduleAuditEntry,
    RescheduleTriggerEvent,
    ScheduleNervousnessReport,
    ScheduleSolverMetadata,
)
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.what_if import NoCloseConnectionWrapper


class DynamicRescheduler:
    """Orchestrates event-driven rescheduling, freeze horizons, and audit logging."""

    def __init__(self, disk_db_path: str | None = None):
        self.disk_db_path = str(disk_db_path or get_runtime_paths()["db_path"])

    def _create_isolated_connection(self) -> sqlite3.Connection:
        disk_conn = sqlite3.connect(self.disk_db_path)
        mem_conn = sqlite3.connect(":memory:")
        disk_conn.backup(mem_conn)
        disk_conn.close()
        return mem_conn

    def _get_active_run_id(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1").fetchone()
        if not row or not row[0]:
            raise ValueError("[RESCHEDULE] ACTIVE run bulunamadı; silent fallback yasaktır.")
        return str(row[0])

    def _build_frozen_positions(self, baseline_sched: pd.DataFrame, trigger: RescheduleTriggerEvent, completed_tasks: set) -> dict:
        cutoff = trigger.current_time_min + trigger.freeze_horizon_min
        frozen = baseline_sched[(baseline_sched["start_min"] < cutoff) | baseline_sched["task_id"].isin(completed_tasks)]
        return {str(r["task_id"]):(str(r["machine_id"]),float(r["start_min"]),float(r["end_min"])) for _,r in frozen.iterrows()}

    def _create_new_run_record(self, conn: sqlite3.Connection, new_run_id: str, previous_run_id: str) -> None:
        row = conn.execute(
            "SELECT trigger_source, orders_count, git_sha, config_hash, data_source FROM pipeline_runs WHERE run_id = ?",
            (previous_run_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"[RESCHEDULE] Baseline run bulunamadı: {previous_run_id}")
        conn.execute(
            """INSERT INTO pipeline_runs
               (run_id,timestamp,trigger_source,orders_count,git_sha,config_hash,data_source,status)
               VALUES (?,datetime('now'),?,?,?,?,?,'COMPLETED')""",
            (new_run_id,f"RESCHEDULE:{previous_run_id}",row[1],row[2],row[3],row[4]),
        )

    def _persist_rescheduled_version(self, conn: sqlite3.Connection, new_df: pd.DataFrame, new_run_id: str, audit: RescheduleAuditEntry) -> None:
        self._create_new_run_record(conn,new_run_id,audit.previous_run_id)
        new_df.to_sql("production_schedule",conn,if_exists="append",index=False)
        # Solver metadata is also versioned; never replace historical metadata.
        meta_row = {
            "run_id": new_run_id,
            "status": "RESCHEDULED",
            "reschedule_from_run_id": audit.previous_run_id,
            "trigger_event_id": audit.trigger_event_id,
            "nervousness_score": audit.nervousness_score,
        }
        pd.DataFrame([meta_row]).to_sql("reschedule_version_metadata", conn, if_exists="append", index=False)
        self._persist_audit_entry(conn,audit)
        conn.commit()

    def scan_pending_mes_events(
        self, mem_conn: sqlite3.Connection, current_time_min: int
    ) -> list[RescheduleTriggerEvent]:
        """Scans mes_execution_events for recent delays or breakdown incidents."""
        query = """
            SELECT event_id, task_id, machine_id, event_type, event_timestamp_min,
                   actual_duration_min, delay_reason
            FROM mes_execution_events
            WHERE event_timestamp_min <= ?
              AND (event_type LIKE '%DELAY%' OR event_type LIKE '%BREAKDOWN%' OR event_type LIKE '%STOP%')
            ORDER BY event_timestamp_min DESC
        """
        events_df = pd.read_sql(query, mem_conn, params=(current_time_min,))
        triggers = []
        for _, row in events_df.iterrows():
            triggers.append(
                RescheduleTriggerEvent(
                    event_id=str(row["event_id"]),
                    current_time_min=int(row["event_timestamp_min"]),
                    freeze_horizon_min=60,
                    delay_machine_id=row["machine_id"],
                    delay_duration_min=int(row["actual_duration_min"] or 0),
                    reason=f"{row['event_type']}: {row['delay_reason'] or 'Unspecified deviation'}",
                )
            )
        return triggers

    def execute_reschedule(self, trigger: RescheduleTriggerEvent, new_run_id: str | None = None, persist_audit: bool = True):
        """Reschedule the ACTIVE schedule in an isolated sandbox and persist it as a new immutable run."""
        disk_conn = sqlite3.connect(self.disk_db_path)
        try:
            previous_run_id = self._get_active_run_id(disk_conn)
            baseline_sched = pd.read_sql("SELECT * FROM production_schedule WHERE run_id = ? ORDER BY start_min",disk_conn,params=(previous_run_id,))
            if baseline_sched.empty: raise ValueError(f"[RESCHEDULE] ACTIVE schedule bulunamadı: {previous_run_id}")
            new_run_id = new_run_id or f"RESCHED-{uuid.uuid4().hex[:10].upper()}"
            if new_run_id == previous_run_id: raise ValueError("[RESCHEDULE] new_run_id ACTIVE run ile aynı olamaz.")
            track_df = pd.read_sql("SELECT task_id,status FROM mes_order_tracking WHERE run_id = ?",disk_conn,params=(previous_run_id,))
            completed = set(track_df.loc[track_df["status"]=="COMPLETED","task_id"]) if not track_df.empty else set()
            frozen = self._build_frozen_positions(baseline_sched,trigger,completed)
            mem_conn = sqlite3.connect(":memory:")
            disk_conn.backup(mem_conn)
            try:
                if trigger.delay_machine_id and trigger.delay_duration_min > 0:
                    mem_conn.execute("UPDATE machine_calendar SET available_hours=MAX(0.0,available_hours-?) WHERE machine_id=?",(trigger.delay_duration_min/60.0,trigger.delay_machine_id))
                    mem_conn.commit()
                from unittest.mock import patch
                with patch("src.scheduling.schedule_cpsat.get_db_connection",return_value=NoCloseConnectionWrapper(mem_conn)):
                    meta=run_cpsat_scheduling(run_id=new_run_id,frozen_task_positions=frozen,persist_outputs=False)
                new_sched=pd.read_sql("SELECT * FROM production_schedule WHERE run_id = ?",mem_conn,params=(new_run_id,))
            finally: mem_conn.close()
            if new_sched.empty: raise ValueError("[RESCHEDULE] Solver yeni schedule üretmedi.")
            for tid,(machine,start,end) in frozen.items():
                row=new_sched[new_sched["task_id"].astype(str)==tid]
                if row.empty: raise ValueError(f"[RESCHEDULE] Frozen task missing: {tid}")
                nr=row.iloc[0]
                if str(nr["machine_id"])!=machine or abs(float(nr["start_min"])-start)>1e-6 or abs(float(nr["end_min"])-end)>1e-6:
                    raise ValueError(f"[RESCHEDULE] Frozen constraint violated: {tid}")
            report=self._calculate_nervousness(baseline_sched,new_sched,len(frozen),len(baseline_sched)-len(frozen))
            audit=RescheduleAuditEntry(audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",trigger_event_id=trigger.event_id,previous_run_id=previous_run_id,new_run_id=new_run_id,trigger_timestamp_min=trigger.current_time_min,freeze_horizon_min=trigger.freeze_horizon_min,affected_machine_id=trigger.delay_machine_id,delay_duration_min=trigger.delay_duration_min,reason=trigger.reason,total_tasks=report.total_tasks,frozen_tasks_count=report.frozen_tasks_count,rescheduled_tasks_count=report.rescheduled_tasks_count,machine_swapped_count=report.machine_swapped_count,avg_start_delta_min=report.average_start_delta_min,nervousness_score=report.nervousness_score)
            if persist_audit:
                self._persist_rescheduled_version(disk_conn,new_sched,new_run_id,audit)
                from src.utils.lineage import promote_run_to_active
                promote_run_to_active(new_run_id, db_path=self.disk_db_path)
            return baseline_sched,new_sched,meta,report,audit
        finally: disk_conn.close()

    def _persist_audit_entry(self, conn: sqlite3.Connection, audit: RescheduleAuditEntry) -> None:
        """Persists the audit lineage record into SQLite."""
        conn.execute(
            """
            INSERT OR REPLACE INTO reschedule_audit_log (
                audit_id, trigger_event_id, previous_run_id, new_run_id,
                trigger_timestamp_min, freeze_horizon_min, affected_machine_id,
                delay_duration_min, reason, total_tasks, frozen_tasks_count,
                rescheduled_tasks_count, machine_swapped_count, avg_start_delta_min,
                nervousness_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit.audit_id,
                audit.trigger_event_id,
                audit.previous_run_id,
                audit.new_run_id,
                audit.trigger_timestamp_min,
                audit.freeze_horizon_min,
                audit.affected_machine_id,
                audit.delay_duration_min,
                audit.reason,
                audit.total_tasks,
                audit.frozen_tasks_count,
                audit.rescheduled_tasks_count,
                audit.machine_swapped_count,
                audit.avg_start_delta_min,
                audit.nervousness_score,
            ),
        )
        conn.commit()

    def _reconcile_frozen_schedule(
        self,
        new_sched: pd.DataFrame,
        frozen_tasks: pd.DataFrame,
        new_run_id: str,
    ) -> pd.DataFrame:
        if frozen_tasks.empty:
            return new_sched.copy()

        frozen_ids = set(frozen_tasks["task_id"])
        non_frozen_part = new_sched[~new_sched["task_id"].isin(frozen_ids)].copy()
        frozen_part = frozen_tasks.copy()
        frozen_part["run_id"] = new_run_id

        combined = pd.concat([frozen_part, non_frozen_part], ignore_index=True)
        return combined.sort_values(by=["machine_id", "start_min"]).reset_index(drop=True)

    def _calculate_nervousness(
        self,
        baseline_sched: pd.DataFrame,
        new_sched: pd.DataFrame,
        frozen_count: int,
        rescheduled_count: int,
    ) -> ScheduleNervousnessReport:
        base_indexed = baseline_sched.set_index("task_id")
        new_indexed = new_sched.set_index("task_id")

        common_tasks = base_indexed.index.intersection(new_indexed.index)
        total_tasks = len(common_tasks)

        if total_tasks == 0:
            return ScheduleNervousnessReport(
                total_tasks=0,
                frozen_tasks_count=frozen_count,
                rescheduled_tasks_count=rescheduled_count,
                machine_swapped_count=0,
                average_start_delta_min=0.0,
                max_start_delta_min=0.0,
                nervousness_score=0.0,
            )

        machine_swaps = 0
        start_deltas = []

        for task_id in common_tasks:
            b_row = base_indexed.loc[task_id]
            n_row = new_indexed.loc[task_id]

            if b_row["machine_id"] != n_row["machine_id"]:
                machine_swaps += 1

            delta = abs(float(n_row["start_min"]) - float(b_row["start_min"]))
            start_deltas.append(delta)

        avg_delta = float(np.mean(start_deltas)) if start_deltas else 0.0
        max_delta = float(np.max(start_deltas)) if start_deltas else 0.0

        # Kararlılık Skoru (Nervousness Score):
        # 1 haftalık nominal planlama ufku (10.080 dk) üzerinden zaman sapması normalizasyonu
        swap_ratio = machine_swaps / total_tasks
        time_disruption_ratio = min(1.0, avg_delta / 10080.0)
        nervousness_score = round(0.5 * swap_ratio + 0.5 * time_disruption_ratio, 4)

        return ScheduleNervousnessReport(
            total_tasks=total_tasks,
            frozen_tasks_count=frozen_count,
            rescheduled_tasks_count=rescheduled_count,
            machine_swapped_count=machine_swaps,
            average_start_delta_min=round(avg_delta, 2),
            max_start_delta_min=round(max_delta, 2),
            nervousness_score=nervousness_score,
        )
