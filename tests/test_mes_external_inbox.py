"""External MES message identity survives service recreation and rolls back atomically."""

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


def test_breakdown_retry_does_not_trigger_reschedule_again(mes_db):
    def deliver():
        return MESIntegrationService().record_event(
            event_type="MACHINE_DOWN",
            machine_id="M01",
            event_timestamp_min=120,
            delay_reason="synthetic stop",
            source_system="SYNTHETIC-MES",
            external_message_id="stop-1",
        )

    assert deliver()["reschedule_required"] is True
    retry = deliver()
    assert retry["status"] == "DUPLICATE_IGNORED"
    assert retry["original_trigger_reschedule"] is True
    assert retry["reschedule_required"] is False
    with sqlite3.connect(mes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mes_execution_events").fetchone()[0] == 1


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
