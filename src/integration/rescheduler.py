"""Compatibility facade for the authoritative dynamic rescheduler.

P0-3: There is one production rescheduling engine:
src.scheduling.rescheduler.DynamicRescheduler.
This module keeps the historical public API used by MES/legacy callers while
delegating all schedule decisions to the authoritative engine.
"""

import uuid
from contextlib import closing
from functools import wraps
from typing import Any

from src.contracts.schemas import RescheduleTriggerEvent
from src.scheduling.rescheduler import DynamicRescheduler
from src.utils.db import get_active_run_id
from src.utils.runtime_lock import run_mutation_lock


def _serialized(method):
    @wraps(method)
    def execute(self, *args, **kwargs):
        with run_mutation_lock(self._engine.disk_db_path):
            return method(self, *args, **kwargs)

    return execute


class ClosedLoopRescheduler:
    """Backward-compatible facade over DynamicRescheduler."""

    def __init__(self, run_id: str | None = None, db_path: str | None = None):
        self.db_path = db_path
        self.run_id = run_id
        self._engine = DynamicRescheduler(disk_db_path=db_path)
        if self.run_id is None:
            import sqlite3

            with closing(sqlite3.connect(self._engine.disk_db_path)) as conn:
                try:
                    self.run_id = get_active_run_id(conn)
                except RuntimeError:
                    pass

    @_serialized
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
        """Delegate to the authoritative ACTIVE -> new run rescheduler.

        commit=False is a sandbox call and does not persist the new version.
        force_heuristic is retained for API compatibility; the authoritative
        engine intentionally uses the solver path so freeze semantics stay
        mathematically enforceable.
        """
        trigger = RescheduleTriggerEvent(
            event_id=f"EVT-{uuid.uuid4().hex[:10].upper()}",
            current_time_min=int(round(down_start_min)),
            freeze_horizon_min=240,
            delay_machine_id=machine_id,
            delay_duration_min=int(round(down_duration_min)),
            reason=f"[{event_type}] {reason}",
        )
        # The observed MES event is durable even when no ACTIVE schedule is
        # available or a subsequent solve fails. Sandbox calls never write it.
        if commit and self.run_id:
            import sqlite3

            with closing(sqlite3.connect(self._engine.disk_db_path)) as conn:
                conn.execute(
                    "INSERT INTO mes_execution_events "
                    "(run_id, machine_id, event_type, event_timestamp_min, actual_duration_min, delay_reason) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (self.run_id, machine_id, event_type, down_start_min, down_duration_min, reason),
                )
                conn.commit()
        try:
            base_df, new_df, meta, report, audit = self._engine.execute_reschedule(
                trigger=trigger,
                new_run_id=None,
                persist_audit=commit,
            )
        except ValueError as exc:
            if "ACTIVE run" in str(exc) or "ACTIVE schedule" in str(exc):
                return {
                    "status": "NO_ACTIVE_RUN",
                    "affected_tasks_count": 0,
                    "old_makespan_min": 0.0,
                    "new_makespan_min": 0.0,
                    "delta_makespan_min": 0.0,
                    "reschedule_mode": "NONE",
                    "is_major_disruption": down_duration_min > 60.0,
                    "error": str(exc),
                }
            raise

        old_makespan = float(base_df["end_min"].max()) if not base_df.empty else 0.0
        new_makespan = float(new_df["end_min"].max()) if not new_df.empty else old_makespan
        if commit:
            self.run_id = audit.new_run_id
        return {
            "status": "RESCHEDULED",
            "affected_tasks_count": int(report.rescheduled_tasks_count),
            "old_makespan_min": old_makespan,
            "new_makespan_min": new_makespan,
            "delta_makespan_min": max(0.0, new_makespan - old_makespan),
            "reschedule_mode": "CPSAT_REOPTIMIZATION",
            "is_major_disruption": down_duration_min > 60.0,
            "previous_run_id": audit.previous_run_id,
            "new_run_id": audit.new_run_id,
            "audit_id": audit.audit_id,
            "nervousness_score": report.nervousness_score,
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
        runtime_deviation = actual_runtime_min - planned_runtime_min
        downtime_deviation = actual_downtime_min - planned_downtime_min
        scrap_deviation = actual_scrap_rate - planned_scrap_rate
        total_time_deviation = runtime_deviation + downtime_deviation
        replan_required = total_time_deviation > tolerance_delay_min or scrap_deviation > scrap_tolerance
        result = None
        if replan_required and total_time_deviation > 0:
            result = self.reschedule_on_machine_breakdown(
                machine_id=machine_id,
                down_start_min=planned_runtime_min,
                down_duration_min=total_time_deviation,
                reason=(
                    f"Execution Deviation (Runtime: {runtime_deviation:+.1f}m, "
                    f"Downtime: {downtime_deviation:+.1f}m, "
                    f"Scrap: {scrap_deviation:+.1%})"
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
            "reschedule_result": result,
        }
