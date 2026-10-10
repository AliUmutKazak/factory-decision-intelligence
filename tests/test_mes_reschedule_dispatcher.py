"""Synthetic handoff checks for a durable MES trigger and audited schedule."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from src.integration.mes_reschedule_dispatcher import MESRescheduleDispatcher
from src.integration.mes_service import MESIntegrationService


@pytest.fixture
def mes_db(tmp_path, monkeypatch):
    path = tmp_path / "mes-dispatch.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, status TEXT, timestamp TEXT);
            INSERT INTO pipeline_runs VALUES ('RUN-A', 'ACTIVE', '2026-10-10T00:00:00');
            CREATE TABLE machines (machine_id TEXT PRIMARY KEY);
            INSERT INTO machines VALUES ('M01');
            CREATE TABLE mes_execution_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                event_type TEXT NOT NULL, machine_id TEXT NOT NULL, task_id INTEGER,
                event_timestamp_min REAL NOT NULL, delay_reason TEXT
            );
            CREATE TABLE mes_order_tracking (
                run_id TEXT, task_id INTEGER, machine_id TEXT,
                scheduled_start_min REAL, scheduled_end_min REAL,
                actual_start_min REAL, actual_end_min REAL, status TEXT, variance_min REAL
            );
            INSERT INTO mes_order_tracking VALUES ('RUN-A', 1, 'M01', 60, 80, NULL, NULL, 'SCHEDULED', 0);
            CREATE TABLE reschedule_audit_log (
                audit_id TEXT PRIMARY KEY, trigger_event_id TEXT,
                previous_run_id TEXT, new_run_id TEXT
            );
            """
        )
    monkeypatch.setenv("FACTORY_DB_PATH", str(path))
    return path


def seed_breakdown():
    return MESIntegrationService().record_event(
        event_type="MACHINE_DOWN",
        machine_id="M01",
        event_timestamp_min=120.25,
        delay_reason="synthetic stop",
        source_system="SYNTHETIC-MES",
        external_message_id="stop-1",
    )["event_id"]


def test_dispatcher_rejects_engine_for_another_database(mes_db, tmp_path):
    with pytest.raises(ValueError, match="same database"):
        MESRescheduleDispatcher(engine=AuditedEngine(tmp_path / "another.db"))


class AuditedEngine:
    def __init__(self, db_path, crash_after_promotion=False):
        self.disk_db_path = str(db_path)
        self.calls = []
        self.crash_after_promotion = crash_after_promotion

    def execute_reschedule(self, *, trigger, persist_audit):
        assert persist_audit is True
        self.calls.append(trigger)
        with sqlite3.connect(self.disk_db_path) as conn:
            conn.execute("UPDATE pipeline_runs SET status='ARCHIVED' WHERE run_id='RUN-A'")
            conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-B', 'ACTIVE', '2026-10-10T01:00:00')")
            conn.execute(
                "INSERT INTO reschedule_audit_log VALUES ('AUD-1', ?, 'RUN-A', 'RUN-B')",
                (trigger.event_id,),
            )
        if self.crash_after_promotion:
            raise RuntimeError("interrupted before outbox ACK")
        return None, None, None, None, SimpleNamespace(audit_id="AUD-1", new_run_id="RUN-B")


def test_machine_outage_requires_duration_then_dispatches_and_acks(mes_db):
    event_id = seed_breakdown()
    engine = AuditedEngine(mes_db)
    dispatcher = MESRescheduleDispatcher(engine=engine)
    assert dispatcher.dispatch_one(event_id)["status"] == "NEEDS_DURATION"
    assert engine.calls == []
    result = dispatcher.dispatch_one(event_id, outage_duration_min=45, freeze_horizon_min=30)
    assert result == {"status": "DISPATCHED", "event_id": event_id, "audit_id": "AUD-1", "new_run_id": "RUN-B"}
    trigger = engine.calls[0]
    assert trigger.event_id == str(event_id)
    assert trigger.current_time_min == 121
    assert trigger.freeze_horizon_min == 30
    assert trigger.delay_machine_id == "M01"
    assert trigger.delay_duration_min == 45
    assert dispatcher.dispatch_one(event_id)["status"] == "ALREADY_ACKED"
    assert len(engine.calls) == 1
    assert MESIntegrationService().list_pending_reschedule_intents() == []


def test_promoted_schedule_is_recovered_after_interrupted_ack(mes_db):
    event_id = seed_breakdown()
    engine = AuditedEngine(mes_db, crash_after_promotion=True)
    dispatcher = MESRescheduleDispatcher(engine=engine)
    with pytest.raises(RuntimeError, match="interrupted"):
        dispatcher.dispatch_one(event_id, outage_duration_min=45)
    assert len(MESIntegrationService().list_pending_reschedule_intents()) == 1
    assert dispatcher.dispatch_one(event_id) == {
        "status": "RECOVERED_ACK",
        "event_id": event_id,
        "audit_id": "AUD-1",
        "new_run_id": "RUN-B",
    }
    assert len(engine.calls) == 1


def test_stale_baseline_is_not_rescheduled(mes_db):
    event_id = seed_breakdown()
    with sqlite3.connect(mes_db) as conn:
        conn.execute("UPDATE pipeline_runs SET status='ARCHIVED' WHERE run_id='RUN-A'")
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-B', 'ACTIVE', '2026-10-10T01:00:00')")
    engine = AuditedEngine(mes_db)
    result = MESRescheduleDispatcher(engine=engine).dispatch_one(event_id, outage_duration_min=45)
    assert result["status"] == "STALE_BASELINE"
    assert result["source_run_id"] == "RUN-A"
    assert result["active_run_id"] == "RUN-B"
    assert engine.calls == []
    assert len(MESIntegrationService().list_pending_reschedule_intents()) == 1


def test_multiple_active_runs_block_dispatch(mes_db):
    event_id = seed_breakdown()
    with sqlite3.connect(mes_db) as conn:
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-B', 'ACTIVE', '2026-10-10T01:00:00')")
    engine = AuditedEngine(mes_db)
    result = MESRescheduleDispatcher(engine=engine).dispatch_one(event_id, outage_duration_min=45)
    assert result["status"] == "RUN_GOVERNANCE_BLOCKED"
    assert engine.calls == []


def test_task_delay_waits_for_event_policy(mes_db):
    event_id = MESIntegrationService().record_event(
        event_type="TASK_COMPLETE",
        machine_id="M01",
        event_timestamp_min=141,
        task_id=1,
        source_system="SYNTHETIC-MES",
        external_message_id="late-task-1",
    )["event_id"]
    engine = AuditedEngine(mes_db)
    result = MESRescheduleDispatcher(engine=engine).dispatch_one(event_id)
    assert result["status"] == "NEEDS_EVENT_POLICY"
    assert engine.calls == []


def test_failed_solve_keeps_intent_pending(mes_db):
    event_id = seed_breakdown()

    class FailedEngine(AuditedEngine):
        def execute_reschedule(self, *, trigger, persist_audit):
            self.calls.append(trigger)
            raise RuntimeError("solver failed before publication")

    engine = FailedEngine(mes_db)
    dispatcher = MESRescheduleDispatcher(engine=engine)
    with pytest.raises(RuntimeError, match="solver failed"):
        dispatcher.dispatch_one(event_id, outage_duration_min=45)
    assert len(MESIntegrationService().list_pending_reschedule_intents()) == 1
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT status FROM mes_reschedule_outbox").fetchone()[0] == "PENDING"
        assert conn.execute("SELECT status FROM pipeline_runs WHERE run_id='RUN-A'").fetchone()[0] == "ACTIVE"


def test_multiple_promoted_audits_require_review(mes_db):
    event_id = seed_breakdown()
    with sqlite3.connect(mes_db) as conn:
        conn.execute("UPDATE pipeline_runs SET status='ARCHIVED' WHERE run_id='RUN-A'")
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-B', 'ARCHIVED', '2026-10-10T01:00:00')")
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-C', 'ACTIVE', '2026-10-10T02:00:00')")
        conn.executemany(
            "INSERT INTO reschedule_audit_log VALUES (?, ?, 'RUN-A', ?)",
            [("AUD-1", str(event_id), "RUN-B"), ("AUD-2", str(event_id), "RUN-C")],
        )
    engine = AuditedEngine(mes_db)
    assert MESRescheduleDispatcher(engine=engine).dispatch_one(event_id)["status"] == "CONFLICTING_AUDITS"
    assert engine.calls == []
    assert len(MESIntegrationService().list_pending_reschedule_intents()) == 1


def test_concurrent_dispatches_do_not_run_solver_twice(mes_db):
    event_id = seed_breakdown()
    engine = AuditedEngine(mes_db)
    dispatcher = MESRescheduleDispatcher(engine=engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dispatcher.dispatch_one(event_id, outage_duration_min=45), range(2)))
    assert {result["status"] for result in results} == {"DISPATCHED", "ALREADY_ACKED"}
    assert len(engine.calls) == 1
