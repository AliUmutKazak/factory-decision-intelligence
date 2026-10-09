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


def _external_payload_hash(event_type, machine_id, event_timestamp_min, task_id, delay_reason):
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
    payload = {
        "event_type": event_type,
        "machine_id": machine_id,
        "event_timestamp_min": float(event_timestamp_min),
        "task_id": task_id,
        "delay_reason": delay_reason,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
            if external:
                if not all(
                    isinstance(value, str) and value.strip() and value == value.strip()
                    for value in (source_system, external_message_id)
                ):
                    raise ValueError(
                        "source_system and external_message_id are both required without outer whitespace."
                    )
                payload_sha256 = _external_payload_hash(
                    event_type, machine_id, event_timestamp_min, task_id, delay_reason
                )
                cur.execute("BEGIN IMMEDIATE")
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
                    self.conn.rollback()
                    return {
                        **original,
                        "status": "DUPLICATE_IGNORED",
                        "original_trigger_reschedule": original["trigger_reschedule"],
                        "trigger_reschedule": False,
                        "reschedule_required": False,
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
            cur.execute(
                """
                INSERT INTO mes_execution_events (
                    run_id, event_type, machine_id, task_id, event_timestamp_min, delay_reason
                ) VALUES (?, ?, ?, ?, ?, ?);
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
                    {"source_system": source_system, "external_message_id": external_message_id, "run_id": self.run_id}
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
