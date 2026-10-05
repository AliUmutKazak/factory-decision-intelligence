"""Dynamic Event-Driven Rescheduling, Audit Trail and Lineage Engine for CP-SAT (Faz 5)."""

import sqlite3
import uuid

import numpy as np
import pandas as pd

from src.config import DB_PATH
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

    def __init__(self, disk_db_path: str = DB_PATH):
        self.disk_db_path = disk_db_path

    def _create_isolated_connection(self) -> sqlite3.Connection:
        disk_conn = sqlite3.connect(self.disk_db_path)
        mem_conn = sqlite3.connect(":memory:")
        disk_conn.backup(mem_conn)
        disk_conn.close()
        return mem_conn

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

    def execute_reschedule(
        self,
        trigger: RescheduleTriggerEvent,
        new_run_id: str = "RESCHEDULED_RUN",
        persist_audit: bool = True,
    ) -> tuple[
        pd.DataFrame,
        pd.DataFrame,
        ScheduleSolverMetadata,
        ScheduleNervousnessReport,
        RescheduleAuditEntry,
    ]:
        """Executes event-driven dynamic rescheduling with a frozen horizon and records audit lineage."""
        from unittest.mock import patch

        mem_conn = self._create_isolated_connection()
        try:
            # 1. Mevcut Aktif Çizelgeyi Oku
            baseline_sched = pd.read_sql(
                "SELECT * FROM production_schedule ORDER BY start_min ASC",
                mem_conn,
            )
            if baseline_sched.empty:
                raise ValueError("Veritabanında yeniden çizelgelenecek aktif bir baz plan bulunamadı.")

            previous_run_id = str(baseline_sched.iloc[0]["run_id"])
            freeze_cutoff_min = trigger.current_time_min + trigger.freeze_horizon_min

            # 2. Dondurulan ve Yeniden Çizelgelenecek Görevleri Belirle
            completed_tasks = set()
            track_df = pd.read_sql(
                "SELECT task_id, status FROM mes_order_tracking",
                mem_conn,
            )
            if not track_df.empty:
                completed_tasks = set(track_df[track_df["status"] == "COMPLETED"]["task_id"])

            frozen_mask = (baseline_sched["start_min"] < freeze_cutoff_min) | (
                baseline_sched["task_id"].isin(completed_tasks)
            )

            frozen_tasks = baseline_sched[frozen_mask].copy()
            tasks_to_reschedule = baseline_sched[~frozen_mask].copy()

            # 3. Gecikme / Arıza Varsa İlgili Makine Takvimine Yansıt
            if trigger.delay_machine_id and trigger.delay_duration_min > 0:
                down_hours = trigger.delay_duration_min / 60.0
                mem_conn.execute(
                    "UPDATE machine_calendar SET available_hours = MAX(0.0, available_hours - ?) WHERE machine_id = ?",
                    (down_hours, trigger.delay_machine_id),
                )
                mem_conn.commit()

            # 4. CP-SAT Çözücüyü Çalıştır
            wrapped_conn = NoCloseConnectionWrapper(mem_conn)
            with patch(
                "src.scheduling.schedule_cpsat.get_db_connection",
                return_value=wrapped_conn,
            ):
                new_meta = run_cpsat_scheduling(run_id=new_run_id)

            new_sched = pd.read_sql(
                f"SELECT * FROM production_schedule WHERE run_id = '{new_run_id}'",
                mem_conn,
            )

            # 5. Dondurulmuş Görevleri Koru
            merged_sched = self._reconcile_frozen_schedule(
                new_sched=new_sched,
                frozen_tasks=frozen_tasks,
                new_run_id=new_run_id,
            )

            # 6. Schedule Nervousness Metriği
            nervousness_report = self._calculate_nervousness(
                baseline_sched=baseline_sched,
                new_sched=merged_sched,
                frozen_count=len(frozen_tasks),
                rescheduled_count=len(tasks_to_reschedule),
            )

            # 7. Denetim ve Soyağacı (Audit Lineage) Kaydı
            audit_entry = RescheduleAuditEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                trigger_event_id=trigger.event_id,
                previous_run_id=previous_run_id,
                new_run_id=new_run_id,
                trigger_timestamp_min=trigger.current_time_min,
                freeze_horizon_min=trigger.freeze_horizon_min,
                affected_machine_id=trigger.delay_machine_id,
                delay_duration_min=trigger.delay_duration_min,
                reason=trigger.reason,
                total_tasks=nervousness_report.total_tasks,
                frozen_tasks_count=nervousness_report.frozen_tasks_count,
                rescheduled_tasks_count=nervousness_report.rescheduled_tasks_count,
                machine_swapped_count=nervousness_report.machine_swapped_count,
                avg_start_delta_min=nervousness_report.average_start_delta_min,
                nervousness_score=nervousness_report.nervousness_score,
            )

            if persist_audit:
                self._persist_audit_entry(mem_conn, audit_entry)

            return (
                baseline_sched,
                merged_sched,
                new_meta,
                nervousness_report,
                audit_entry,
            )

        finally:
            mem_conn.close()

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
