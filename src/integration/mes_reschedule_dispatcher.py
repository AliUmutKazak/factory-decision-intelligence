"""Explicit, serialized handoff from durable MES intent to the rescheduler."""

import math
from contextlib import closing
from typing import Any

from src.contracts.schemas import RescheduleTriggerEvent
from src.integration.mes_service import MESIntegrationService
from src.scheduling.rescheduler import DynamicRescheduler
from src.utils.db import get_active_run_id, get_db_connection, resolve_db_path
from src.utils.runtime_lock import run_mutation_lock


class MESRescheduleDispatcher:
    """Process one selected intent; no polling, vendor transport, or automatic scheduling."""

    def __init__(self, engine: DynamicRescheduler | None = None):
        self.db_path = resolve_db_path()
        self.engine = engine or DynamicRescheduler(disk_db_path=str(self.db_path))
        if resolve_db_path(self.engine.disk_db_path).resolve() != self.db_path.resolve():
            raise ValueError("Rescheduler and MES service must use the same database.")

    def dispatch_one(
        self,
        event_id: int,
        *,
        outage_duration_min: int | None = None,
        freeze_horizon_min: int = 60,
    ) -> dict[str, Any]:
        """Run a validated machine outage once, or explain why it cannot run."""
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id <= 0:
            raise ValueError("event_id must be a positive integer.")
        if not isinstance(freeze_horizon_min, int) or isinstance(freeze_horizon_min, bool) or freeze_horizon_min < 0:
            raise ValueError("freeze_horizon_min must be a nonnegative integer.")
        if outage_duration_min is not None and (
            not isinstance(outage_duration_min, int)
            or isinstance(outage_duration_min, bool)
            or outage_duration_min <= 0
        ):
            raise ValueError("outage_duration_min must be a positive integer.")

        with run_mutation_lock(self.db_path):
            service = MESIntegrationService()
            # Also recovers intents written by the inbox version before outbox existed.
            service.list_pending_reschedule_intents()
            with closing(get_db_connection(self.db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT o.run_id, o.status, o.audit_id, e.event_type, e.machine_id,
                           e.event_timestamp_min, e.delay_reason
                    FROM mes_reschedule_outbox AS o
                    JOIN mes_execution_events AS e ON e.event_id = o.event_id
                    WHERE o.event_id = ?
                    """,
                    (event_id,),
                ).fetchone()
                if not row:
                    raise ValueError("Reschedule intent not found.")
                source_run, status, audit_id, event_type, machine_id, event_time, reason = row
                if status == "ACKED":
                    return {"status": "ALREADY_ACKED", "event_id": event_id, "audit_id": audit_id}

                # A crash may have happened after promotion but before the outbox ACK.
                audit_rows = []
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reschedule_audit_log'"
                ).fetchone():
                    audit_rows = conn.execute(
                        """
                        SELECT a.audit_id, a.new_run_id
                        FROM reschedule_audit_log AS a
                        JOIN pipeline_runs AS p ON p.run_id = a.new_run_id
                        WHERE a.trigger_event_id = ? AND a.previous_run_id = ?
                          AND p.status IN ('ACTIVE', 'ARCHIVED')
                        ORDER BY a.audit_id
                        """,
                        (str(event_id), source_run),
                    ).fetchall()
                if len(audit_rows) > 1:
                    return {"status": "CONFLICTING_AUDITS", "event_id": event_id}
                if not audit_rows:
                    try:
                        active_run = get_active_run_id(conn)
                    except RuntimeError as exc:
                        return {"status": "RUN_GOVERNANCE_BLOCKED", "event_id": event_id, "reason": str(exc)}
                    if active_run != source_run:
                        return {
                            "status": "STALE_BASELINE",
                            "event_id": event_id,
                            "source_run_id": source_run,
                            "active_run_id": active_run,
                        }

            if audit_rows:
                recovered_audit, new_run = audit_rows[0]
                service.ack_reschedule_intent(event_id, recovered_audit)
                return {
                    "status": "RECOVERED_ACK",
                    "event_id": event_id,
                    "audit_id": recovered_audit,
                    "new_run_id": new_run,
                }

            if event_type != "MACHINE_DOWN":
                return {"status": "NEEDS_EVENT_POLICY", "event_id": event_id, "event_type": event_type}
            if outage_duration_min is None:
                return {"status": "NEEDS_DURATION", "event_id": event_id}

            trigger = RescheduleTriggerEvent(
                event_id=str(event_id),
                current_time_min=math.ceil(event_time),
                freeze_horizon_min=freeze_horizon_min,
                delay_machine_id=machine_id,
                delay_duration_min=outage_duration_min,
                reason=f"MACHINE_DOWN: {reason or 'Unspecified outage'}",
            )
            _, _, _, _, audit = self.engine.execute_reschedule(trigger=trigger, persist_audit=True)
            service.ack_reschedule_intent(event_id, audit.audit_id)
            return {
                "status": "DISPATCHED",
                "event_id": event_id,
                "audit_id": audit.audit_id,
                "new_run_id": audit.new_run_id,
            }
