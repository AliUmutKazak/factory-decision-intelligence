"""External MES message identity survives service recreation and rolls back atomically."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.integration.mes_service import MESIntegrationService


@pytest.fixture
def mes_db(tmp_path, monkeypatch):
    path = tmp_path / "mes.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, status TEXT, timestamp TEXT);
            INSERT INTO pipeline_runs VALUES ('RUN-A', 'ACTIVE', '2026-10-09T00:00:00');
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
            """
        )
    monkeypatch.setenv("FACTORY_DB_PATH", str(path))
    return path


def record_start():
    return MESIntegrationService().record_event(
        event_type="TASK_START",
        machine_id="M01",
        event_timestamp_min=65,
        task_id=1,
        source_system="SYNTHETIC-MES",
        external_message_id="message-1",
    )


def test_exact_retry_after_service_recreation_does_not_write_twice(mes_db):
    first = record_start()
    assert first["status"] == "RECORDED"
    assert first["variance_min"] == 5
    second = record_start()
    assert second["status"] == "DUPLICATE_IGNORED"
    assert second["event_id"] == first["event_id"]
    assert second["trigger_reschedule"] is False
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mes_external_inbox").fetchone()[0] == 1
        assert conn.execute("SELECT actual_start_min FROM mes_order_tracking WHERE run_id='RUN-A'").fetchone()[0] == 65


def test_message_without_duration_preserves_original_payload_hash(mes_db):
    record_start()
    legacy_payload = {
        "event_type": "TASK_START",
        "machine_id": "M01",
        "event_timestamp_min": 65.0,
        "task_id": 1,
        "delay_reason": None,
    }
    encoded = json.dumps(legacy_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with sqlite3.connect(mes_db) as conn:
        saved_hash = conn.execute("SELECT payload_sha256 FROM mes_external_inbox").fetchone()[0]
    assert saved_hash == hashlib.sha256(encoded).hexdigest()


def test_conflicting_retry_is_rejected_and_identity_is_global_across_runs(mes_db):
    first = record_start()
    with pytest.raises(ValueError, match="Conflicting"):
        MESIntegrationService().record_event(
            event_type="TASK_START",
            machine_id="M01",
            event_timestamp_min=66,
            task_id=1,
            source_system="SYNTHETIC-MES",
            external_message_id="message-1",
        )
    with sqlite3.connect(mes_db) as conn:
        conn.execute("UPDATE pipeline_runs SET status='HISTORICAL' WHERE run_id='RUN-A'")
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-B', 'ACTIVE', '2026-10-09T01:00:00')")
    retry = record_start()
    assert retry["status"] == "DUPLICATE_IGNORED"
    assert retry["run_id"] == first["run_id"] == "RUN-A"
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1


def test_event_tracking_and_inbox_roll_back_together_on_update_failure(mes_db):
    with sqlite3.connect(mes_db) as conn:
        conn.execute(
            "CREATE TRIGGER fail_tracking BEFORE UPDATE ON mes_order_tracking "
            "BEGIN SELECT RAISE(FAIL, 'tracking unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="tracking unavailable"):
        record_start()
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 0
        assert (
            conn.execute("SELECT actual_start_min FROM mes_order_tracking WHERE run_id='RUN-A'").fetchone()[0] is None
        )
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='mes_external_inbox'").fetchone() is None


def test_inbox_insert_failure_rolls_back_event_and_tracking_update(mes_db):
    first = record_start()
    with sqlite3.connect(mes_db) as conn:
        conn.execute(
            "CREATE TRIGGER fail_inbox BEFORE INSERT ON mes_external_inbox "
            "BEGIN SELECT RAISE(FAIL, 'inbox unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="inbox unavailable"):
        MESIntegrationService().record_event(
            event_type="TASK_START",
            machine_id="M01",
            event_timestamp_min=66,
            task_id=1,
            source_system="SYNTHETIC-MES",
            external_message_id="message-2",
        )
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mes_external_inbox").fetchone()[0] == 1
        assert conn.execute("SELECT actual_start_min FROM mes_order_tracking WHERE run_id='RUN-A'").fetchone()[0] == 65
        assert conn.execute("SELECT event_id FROM mes_execution_events").fetchone()[0] == first["event_id"]


def test_concurrent_same_message_keeps_one_event(mes_db):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: record_start(), range(2)))
    assert {item["status"] for item in results} == {"RECORDED", "DUPLICATE_IGNORED"}
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mes_external_inbox").fetchone()[0] == 1


def deliver_breakdown():
    return MESIntegrationService().record_event(
        event_type="MACHINE_DOWN",
        machine_id="M01",
        event_timestamp_min=120,
        delay_reason="synthetic stop",
        source_system="SYNTHETIC-MES",
        external_message_id="stop-1",
    )


def test_breakdown_retry_remains_pending_until_audited_reschedule(mes_db):
    first = deliver_breakdown()
    assert first["reschedule_required"] is True
    assert first["reschedule_intent_status"] == "PENDING"
    retry = deliver_breakdown()
    assert retry["status"] == "DUPLICATE_IGNORED"
    assert retry["event_id"] == first["event_id"]
    assert retry["original_trigger_reschedule"] is True
    assert retry["reschedule_required"] is True
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mes_reschedule_outbox").fetchone()[0] == 1
        conn.execute("UPDATE pipeline_runs SET status='HISTORICAL' WHERE run_id='RUN-A'")
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-B', 'ACTIVE', '2026-10-09T01:00:00')")
    pending = MESIntegrationService().list_pending_reschedule_intents()
    assert len(pending) == 1
    assert pending[0]["event_id"] == first["event_id"]
    assert pending[0]["run_id"] == "RUN-A"
    assert deliver_breakdown()["reschedule_required"] is True


def test_ack_requires_matching_audit_and_promoted_run(mes_db):
    event_id = deliver_breakdown()["event_id"]
    service = MESIntegrationService()
    with pytest.raises(ValueError, match="No matching audit"):
        service.ack_reschedule_intent(event_id, "audit-1")
    with sqlite3.connect(mes_db) as conn:
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-B', 'RUNNING', '2026-10-09T01:00:00')")
        conn.execute(
            "CREATE TABLE reschedule_audit_log (audit_id TEXT PRIMARY KEY, trigger_event_id TEXT, "
            "previous_run_id TEXT, new_run_id TEXT)"
        )
        conn.execute(
            "INSERT INTO reschedule_audit_log VALUES ('audit-1', ?, 'RUN-A', 'RUN-B')",
            (str(event_id),),
        )
    with pytest.raises(ValueError, match="No matching audit"):
        service.ack_reschedule_intent(event_id, "audit-1")
    with sqlite3.connect(mes_db) as conn:
        conn.execute("UPDATE pipeline_runs SET status='ACTIVE' WHERE run_id='RUN-B'")
    with pytest.raises(ValueError, match="No matching audit"):
        service.ack_reschedule_intent(event_id, "other-audit")
    assert service.ack_reschedule_intent(event_id, "audit-1") is True
    assert service.ack_reschedule_intent(event_id, "audit-1") is False
    with pytest.raises(ValueError, match="another audit"):
        service.ack_reschedule_intent(event_id, "other-audit")
    assert service.list_pending_reschedule_intents() == []
    retry = deliver_breakdown()
    assert retry["reschedule_required"] is False
    assert retry["reschedule_intent_status"] == "ACKED"


def test_large_task_delay_creates_pending_intent(mes_db):
    result = MESIntegrationService().record_event(
        event_type="TASK_COMPLETE",
        machine_id="M01",
        event_timestamp_min=141,
        task_id=1,
        source_system="SYNTHETIC-MES",
        external_message_id="late-task-1",
    )
    assert result["variance_min"] == 61
    assert result["reschedule_intent_status"] == "PENDING"
    assert MESIntegrationService().list_pending_reschedule_intents()[0]["event_id"] == result["event_id"]


def test_outage_duration_is_durable_and_part_of_message_identity(mes_db):
    def deliver(duration):
        return MESIntegrationService().record_event(
            event_type="MACHINE_DOWN",
            machine_id="M01",
            event_timestamp_min=120,
            source_system="SYNTHETIC-MES",
            external_message_id="duration-1",
            outage_duration_min=duration,
        )

    first = deliver(45)
    assert first["outage_duration_min"] == 45
    assert deliver(45)["status"] == "DUPLICATE_IGNORED"
    with pytest.raises(ValueError, match="Conflicting"):
        deliver(60)
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT actual_duration_min FROM mes_execution_events").fetchone()[0] == 45
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1
    pending = MESIntegrationService().list_pending_reschedule_intents()
    assert pending[0]["outage_duration_min"] == 45


def test_outage_duration_rejects_invalid_or_unidentified_values(mes_db):
    service = MESIntegrationService()
    for invalid in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="outage_duration_min"):
            service.record_event(
                event_type="MACHINE_DOWN",
                machine_id="M01",
                event_timestamp_min=120,
                source_system="SYNTHETIC-MES",
                external_message_id="invalid-duration",
                outage_duration_min=invalid,
            )
    with pytest.raises(ValueError, match="only valid for MACHINE_DOWN"):
        service.record_event(
            event_type="TASK_START",
            machine_id="M01",
            event_timestamp_min=65,
            task_id=1,
            source_system="SYNTHETIC-MES",
            external_message_id="task-duration",
            outage_duration_min=45,
        )
    with pytest.raises(ValueError, match="requires external"):
        service.record_event("MACHINE_DOWN", "M01", 120, outage_duration_min=45)
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 0


def test_outbox_failure_rolls_back_mes_event_and_inbox(mes_db):
    assert deliver_breakdown()["reschedule_required"] is True
    with sqlite3.connect(mes_db) as conn:
        conn.execute(
            "CREATE TRIGGER fail_outbox BEFORE INSERT ON mes_reschedule_outbox "
            "BEGIN SELECT RAISE(FAIL, 'outbox unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="outbox unavailable"):
        MESIntegrationService().record_event(
            event_type="MACHINE_DOWN",
            machine_id="M01",
            event_timestamp_min=130,
            source_system="SYNTHETIC-MES",
            external_message_id="stop-2",
        )
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mes_external_inbox").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mes_reschedule_outbox").fetchone()[0] == 1


def test_pre_outbox_message_is_recovered_as_pending(mes_db):
    event_id = deliver_breakdown()["event_id"]
    with sqlite3.connect(mes_db) as conn:
        conn.execute("DROP TABLE mes_reschedule_outbox")
    assert deliver_breakdown()["reschedule_intent_status"] == "PENDING"
    pending = MESIntegrationService().list_pending_reschedule_intents()
    assert [row["event_id"] for row in pending] == [event_id]
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT status FROM mes_reschedule_outbox").fetchone()[0] == "PENDING"


def test_external_path_rejects_bad_identity_and_task_machine_mapping(mes_db):
    with pytest.raises(ValueError, match="source_system"):
        MESIntegrationService().record_event(
            event_type="TASK_START",
            machine_id="M01",
            event_timestamp_min=65,
            task_id=1,
            external_message_id="message-1",
        )
    with pytest.raises(ValueError, match="finite"):
        MESIntegrationService().record_event(
            event_type="TASK_START",
            machine_id="M01",
            event_timestamp_min=float("nan"),
            task_id=1,
            source_system="SYNTHETIC-MES",
            external_message_id="message-1",
        )
    with pytest.raises(ValueError, match="absent"):
        MESIntegrationService().record_event(
            event_type="TASK_COMPLETE",
            machine_id="M01",
            event_timestamp_min=80,
            task_id=999,
            source_system="SYNTHETIC-MES",
            external_message_id="message-1",
        )
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 0
