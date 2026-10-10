"""
MES Integration & Execution Feedback Service
Sahadan (MES) gelen telemetri, iş başlatma/bitirme ve arıza (downtime)
olaylarını yönetir, sapmaları hesaplar ve kapalı çevrim tetikler.
"""

import hashlib
import json
import math
from functools import wraps
from typing import Any

import pandas as pd

from src.utils.db import get_db_connection, resolve_db_path
from src.utils.runtime_lock import run_mutation_lock


def _external_payload_hash(event_type, machine_id, event_timestamp_min, task_id, delay_reason, outage_duration_min):
    """Validate the narrow external event contract and hash its canonical payload."""
    if not isinstance(event_type, str) or event_type not in {"TASK_START", "TASK_COMPLETE", "MACHINE_DOWN"}:
        raise ValueError("Unsupported external MES event_type.")
    if not isinstance(machine_id, str) or not machine_id.strip():
        raise ValueError("External MES machine_id is required.")
    if (
        not isinstance(event_timestamp_min, (int, float))
        or isinstance(event_timestamp_min, bool)
        or not math.isfinite(event_timestamp_min)
        or event_timestamp_min < 0
    ):
        raise ValueError("External MES event_timestamp_min must be finite and nonnegative.")
    if task_id is not None and (not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0):
        raise ValueError("External MES task_id must be a positive integer when supplied.")
    if event_type in {"TASK_START", "TASK_COMPLETE"} and task_id is None:
        raise ValueError("External task event requires task_id.")
    if delay_reason is not None and not isinstance(delay_reason, str):
        raise ValueError("External MES delay_reason must be text or null.")
    if outage_duration_min is not None:
        if event_type != "MACHINE_DOWN":
            raise ValueError("outage_duration_min is only valid for MACHINE_DOWN.")
        if (
            not isinstance(outage_duration_min, int)
            or isinstance(outage_duration_min, bool)
            or outage_duration_min <= 0
        ):
            raise ValueError("outage_duration_min must be a positive integer.")
    payload = {
        "event_type": event_type,
        "machine_id": machine_id,
        "event_timestamp_min": float(event_timestamp_min),
        "task_id": task_id,
        "delay_reason": delay_reason,
    }
    # Old messages omitted this optional field; keep their original hash stable.
    if outage_duration_min is not None:
        payload["outage_duration_min"] = outage_duration_min
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ensure_execution_duration_column(conn):
    """Add the optional duration to databases created before this MES contract."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(mes_execution_events)")}
    if "actual_duration_min" not in columns:
        conn.execute("ALTER TABLE mes_execution_events ADD COLUMN actual_duration_min REAL")


def _ensure_reschedule_outbox(conn):
    """Create the outbox and conservatively recover pre-outbox inbox decisions."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mes_reschedule_outbox (
            event_id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PENDING', 'ACKED')),
            audit_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            acknowledged_at TEXT,
            FOREIGN KEY (event_id) REFERENCES mes_execution_events(event_id)
        )
        """
    )
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mes_external_inbox'").fetchone():
        return
    old_messages = conn.execute(
        """
        SELECT i.event_id, i.run_id, i.outcome_json
        FROM mes_external_inbox AS i
        LEFT JOIN mes_reschedule_outbox AS o ON o.event_id = i.event_id
        WHERE o.event_id IS NULL
        """
    ).fetchall()
    for event_id, run_id, outcome_json in old_messages:
        if json.loads(outcome_json).get("trigger_reschedule"):
            conn.execute(
                "INSERT INTO mes_reschedule_outbox (event_id, run_id, status) VALUES (?, ?, 'PENDING')",
                (event_id, run_id),
            )


def _canonical_writer(method):
    @wraps(method)
    def write(self, *args, **kwargs):
        with run_mutation_lock(self.db_path):
            self.conn = get_db_connection(self.db_path)
            try:
                if self._follow_active:
                    self.run_id = self._get_active_run_id()
                return method(self, *args, **kwargs)
            except Exception:
                self.conn.rollback()
                raise
            finally:
                self.conn.close()
                self.conn = None

    return write


class MESIntegrationService:
    def __init__(self, run_id: str | None = None):
        self.db_path = resolve_db_path()
        self._follow_active = run_id is None
        self.conn = get_db_connection(self.db_path)
        try:
            self.run_id = run_id or self._get_active_run_id()
        finally:
            self.conn.close()
            self.conn = None

    def _get_active_run_id(self) -> str | None:
        """
        Sadece aktif durumdaki en güncel pipeline_runs kaydını döner.
        Sessizce geçmiş/inaktif koşulara geri düşmez (No silent fallback).
        """
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1;")
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close()

    @_canonical_writer
    def initialize_tracking_from_schedule(self) -> int:
        """
        Aktif 'production_schedule' verilerini alıp 'mes_order_tracking' tablosuna aktarır.
        Yalnızca geçerli run_id'ye ait verileri işler; sessizce genel tabloya fallback yapmaz.
        """
        if not self.run_id:
            # Aktif koşu yoksa veri uyumsuzluğunu önlemek için işlem yapma
            return 0

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
                params=(self.run_id,),
            )
        else:
            df_schedule = pd.DataFrame()

        if df_schedule.empty:
            return 0

        cur = self.conn.cursor()
        try:
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
                    0.0,
                )
                for _, row in df_schedule.iterrows()
            ]

            cur.executemany(
                """
                INSERT OR IGNORE INTO mes_order_tracking (
                    task_id, run_id, lot_id, product_id, machine_id,
                    scheduled_start_min, scheduled_end_min, status, variance_min
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
                insert_data,
            )

            self.conn.commit()
            return len(insert_data)
        finally:
            cur.close()

    @_canonical_writer
    def record_event(
        self,
        event_type: str,
        machine_id: str,
        event_timestamp_min: float,
        task_id: int | None = None,
        delay_reason: str | None = None,
        *,
        source_system: str | None = None,
        external_message_id: str | None = None,
        outage_duration_min: int | None = None,
    ) -> dict[str, Any]:
        """
        MES olayını kaydeder (TASK_START, TASK_COMPLETE, MACHINE_DOWN vb.)
        ve sapmaya göre yeniden çizelgeleme gerekip gerekmediğini değerlendirir.
        Dış kaynak ve mesaj kimliği birlikte verilirse aynı mesajın tekrarını
        tekilleştirir; kimliksiz eski çağrılar bu güvenceyi taşımaz.
        """
        cur = self.conn.cursor()
        try:
            external = source_system is not None or external_message_id is not None
            if outage_duration_min is not None and not external:
                raise ValueError("outage_duration_min requires external MES message identity.")
            if external:
                if not all(
                    isinstance(value, str) and value.strip() and value == value.strip()
                    for value in (source_system, external_message_id)
                ):
                    raise ValueError(
                        "source_system and external_message_id are both required without outer whitespace."
                    )
                payload_sha256 = _external_payload_hash(
                    event_type, machine_id, event_timestamp_min, task_id, delay_reason, outage_duration_min
                )
                cur.execute("BEGIN IMMEDIATE")
                _ensure_execution_duration_column(self.conn)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mes_external_inbox (
                        source_system TEXT NOT NULL,
                        external_message_id TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        event_id INTEGER NOT NULL,
                        outcome_json TEXT NOT NULL,
                        PRIMARY KEY (source_system, external_message_id),
                        FOREIGN KEY (event_id) REFERENCES mes_execution_events(event_id)
                    )
                    """
                )
                _ensure_reschedule_outbox(self.conn)
                cur.execute(
                    "SELECT payload_sha256, outcome_json FROM mes_external_inbox "
                    "WHERE source_system = ? AND external_message_id = ?",
                    (source_system, external_message_id),
                )
                existing = cur.fetchone()
                if existing:
                    if existing[0] != payload_sha256:
                        raise ValueError("Conflicting external MES message ID and payload.")
                    original = json.loads(existing[1])
                    intent_status = "NONE"
                    if original["trigger_reschedule"]:
                        cur.execute(
                            "SELECT status FROM mes_reschedule_outbox WHERE event_id = ?",
                            (original["event_id"],),
                        )
                        intent = cur.fetchone()
                        if not intent:
                            raise RuntimeError("External MES reschedule intent is missing.")
                        intent_status = intent[0]
                    # The legacy inbox backfill above may have inserted a pending intent.
                    self.conn.commit()
                    return {
                        **original,
                        "status": "DUPLICATE_IGNORED",
                        "original_trigger_reschedule": original["trigger_reschedule"],
                        "trigger_reschedule": intent_status == "PENDING",
                        "reschedule_required": intent_status == "PENDING",
                        "reschedule_intent_status": intent_status,
                    }
                if not self.run_id:
                    raise ValueError("External MES message requires an ACTIVE run.")
                if task_id is not None and event_type in {"TASK_START", "TASK_COMPLETE"}:
                    cur.execute(
                        "SELECT machine_id FROM mes_order_tracking WHERE run_id = ? AND task_id = ?",
                        (self.run_id, task_id),
                    )
                    tracking = cur.fetchone()
                    if not tracking or tracking[0] != machine_id:
                        raise ValueError("External MES task is absent from this run or machine_id differs.")

            # Doğru kolon adı: event_timestamp_min
            if external:
                cur.execute(
                    """
                    INSERT INTO mes_execution_events (
                        run_id, event_type, machine_id, task_id, event_timestamp_min,
                        actual_duration_min, delay_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.run_id,
                        event_type,
                        machine_id,
                        task_id,
                        event_timestamp_min,
                        outage_duration_min,
                        delay_reason,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO mes_execution_events (
                        run_id, event_type, machine_id, task_id, event_timestamp_min, delay_reason
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (self.run_id, event_type, machine_id, task_id, event_timestamp_min, delay_reason),
                )
            event_id = cur.lastrowid

            trigger_reschedule = False
            variance = 0.0

            if event_type == "TASK_START" and task_id is not None:
                cur.execute(
                    "SELECT scheduled_start_min FROM mes_order_tracking WHERE task_id = ? AND run_id = ?;",
                    (task_id, self.run_id),
                )
                row = cur.fetchone()
                if row:
                    variance = event_timestamp_min - float(row[0])
                    cur.execute(
                        """
                        UPDATE mes_order_tracking
                        SET actual_start_min = ?, status = 'IN_PROGRESS', variance_min = ?
                        WHERE task_id = ? AND run_id = ?;
                    """,
                        (event_timestamp_min, variance, task_id, self.run_id),
                    )
                    if variance > 60.0:
                        trigger_reschedule = True

            elif event_type == "TASK_COMPLETE" and task_id is not None:
                cur.execute(
                    "SELECT scheduled_end_min FROM mes_order_tracking WHERE task_id = ? AND run_id = ?;",
                    (task_id, self.run_id),
                )
                row = cur.fetchone()
                if row:
                    variance = event_timestamp_min - float(row[0])
                    cur.execute(
                        """
                        UPDATE mes_order_tracking
                        SET actual_end_min = ?, status = 'COMPLETED', variance_min = ?
                        WHERE task_id = ? AND run_id = ?;
                    """,
                        (event_timestamp_min, variance, task_id, self.run_id),
                    )
                    if variance > 60.0:
                        trigger_reschedule = True

            elif event_type == "MACHINE_DOWN":
                trigger_reschedule = True

            result = {
                "status": "RECORDED",
                "event_id": event_id,
                "event_type": event_type,
                "variance_min": variance,
                "trigger_reschedule": trigger_reschedule,
                "reschedule_required": trigger_reschedule,
            }
            if external:
                result.update(
                    {
                        "source_system": source_system,
                        "external_message_id": external_message_id,
                        "run_id": self.run_id,
                        "reschedule_intent_status": "PENDING" if trigger_reschedule else "NONE",
                    }
                )
                if outage_duration_min is not None:
                    result["outage_duration_min"] = outage_duration_min
                if trigger_reschedule:
                    cur.execute(
                        "INSERT INTO mes_reschedule_outbox (event_id, run_id, status) VALUES (?, ?, 'PENDING')",
                        (event_id, self.run_id),
                    )
                cur.execute(
                    "INSERT INTO mes_external_inbox "
                    "(source_system, external_message_id, payload_sha256, run_id, event_id, outcome_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        source_system,
                        external_message_id,
                        payload_sha256,
                        self.run_id,
                        event_id,
                        json.dumps(result, sort_keys=True, ensure_ascii=False),
                    ),
                )
            self.conn.commit()
            return result
        finally:
            cur.close()

    def list_pending_reschedule_intents(self) -> list[dict[str, Any]]:
        """Recover unacknowledged external MES triggers across run changes."""
        with run_mutation_lock(self.db_path):
            with get_db_connection(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                _ensure_execution_duration_column(conn)
                _ensure_reschedule_outbox(conn)
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mes_external_inbox'"
                ).fetchone():
                    return []
                rows = conn.execute(
                    """
                    SELECT o.event_id, o.run_id, e.event_type, e.machine_id,
                           e.task_id, e.event_timestamp_min, e.delay_reason,
                           e.actual_duration_min,
                           i.source_system, i.external_message_id
                    FROM mes_reschedule_outbox AS o
                    JOIN mes_execution_events AS e ON e.event_id = o.event_id
                    JOIN mes_external_inbox AS i ON i.event_id = o.event_id
                    WHERE o.status = 'PENDING'
                    ORDER BY o.event_id
                    """
                ).fetchall()
        fields = (
            "event_id",
            "run_id",
            "event_type",
            "machine_id",
            "task_id",
            "event_timestamp_min",
            "delay_reason",
            "outage_duration_min",
            "source_system",
            "external_message_id",
        )
        return [dict(zip(fields, row)) for row in rows]

    def ack_reschedule_intent(self, event_id: int, audit_id: str) -> bool:
        """Acknowledge only an audited, promoted reschedule of this MES event."""
        if not isinstance(event_id, int) or isinstance(event_id, bool) or event_id <= 0:
            raise ValueError("event_id must be a positive integer.")
        if not isinstance(audit_id, str) or not audit_id.strip():
            raise ValueError("audit_id is required.")
        with run_mutation_lock(self.db_path):
            with get_db_connection(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                _ensure_reschedule_outbox(conn)
                intent = conn.execute(
                    "SELECT run_id, status, audit_id FROM mes_reschedule_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if not intent:
                    raise ValueError("Reschedule intent not found.")
                if intent[1] == "ACKED":
                    if intent[2] != audit_id:
                        raise ValueError("Reschedule intent was acknowledged with another audit.")
                    return False
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reschedule_audit_log'"
                ).fetchone():
                    raise ValueError("No matching audit for a promoted reschedule run.")
                audit = conn.execute(
                    """
                    SELECT a.new_run_id FROM reschedule_audit_log AS a
                    JOIN pipeline_runs AS p ON p.run_id = a.new_run_id
                    WHERE a.audit_id = ? AND a.trigger_event_id = ?
                      AND a.previous_run_id = ? AND p.status IN ('ACTIVE', 'ARCHIVED')
                    """,
                    (audit_id, str(event_id), intent[0]),
                ).fetchone()
                if not audit:
                    raise ValueError("No matching audit for a promoted reschedule run.")
                conn.execute(
                    """
                    UPDATE mes_reschedule_outbox
                    SET status = 'ACKED', audit_id = ?, acknowledged_at = CURRENT_TIMESTAMP
                    WHERE event_id = ? AND status = 'PENDING'
                    """,
                    (audit_id, event_id),
                )
                return True

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
