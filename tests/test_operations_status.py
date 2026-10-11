"""Publication age must have an explicit UTC source and unknown legacy state."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.server import app
from src.utils.lineage import promote_run_to_active

READ_TOKEN = "r" * 48


@pytest.fixture
def client(monkeypatch, tmp_path):
    db = tmp_path / "factory.db"
    monkeypatch.setenv("FACTORY_DB_PATH", str(db))
    monkeypatch.setenv("FDI_API_READ_TOKEN", READ_TOKEN)
    monkeypatch.setenv("FDI_API_SCENARIO_TOKEN", "s" * 48)
    monkeypatch.setenv("FDI_API_RESCHEDULE_TOKEN", "w" * 48)
    return db, TestClient(app, headers={"Authorization": f"Bearer {READ_TOKEN}"})


def _create_run(db, published_at=None, *, legacy=False):
    with sqlite3.connect(db) as conn:
        if legacy:
            conn.execute("CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, timestamp TEXT, status TEXT)")
            conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-1', '2026-01-01', 'ACTIVE')")
        else:
            conn.execute(
                "CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, timestamp TEXT, status TEXT, published_at_utc TEXT)"
            )
            conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-1', '2026-01-01', 'ACTIVE', ?)", (published_at,))
        conn.execute("CREATE TABLE mes_reschedule_outbox (status TEXT)")
        conn.execute("INSERT INTO mes_reschedule_outbox VALUES ('PENDING')")


def test_operations_status_reports_fresh_and_stale_active(client):
    db, api = client
    moment = datetime.now(UTC) - timedelta(minutes=10)
    _create_run(db, moment.isoformat())
    current = api.get("/api/v1/operations/status?max_active_age_min=60")
    assert current.status_code == 200
    assert current.json()["status"] == "READY"
    assert current.json()["pending_mes_intents"] == 1
    stale = api.get("/api/v1/operations/status?max_active_age_min=5")
    assert stale.json()["status"] == "STALE_ACTIVE"


def test_legacy_timestamp_is_not_guessed_as_utc(client):
    db, api = client
    _create_run(db, legacy=True)
    response = api.get("/api/v1/operations/status")
    assert response.json()["status"] == "AGE_UNKNOWN"
    assert response.json()["active_age_seconds"] is None
    assert TestClient(app).get("/api/v1/operations/status").status_code == 401


def test_operations_status_returns_unavailable_when_runtime_is_missing(client):
    _, api = client
    response = api.get("/api/v1/operations/status")
    assert response.status_code == 503


def test_promotion_migrates_legacy_schema_and_records_utc_publication(tmp_path):
    db = tmp_path / "factory.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, timestamp TEXT, status TEXT)")
        conn.execute("INSERT INTO pipeline_runs VALUES ('OLD', '2026-01-01', 'ACTIVE')")
        conn.execute("INSERT INTO pipeline_runs VALUES ('NEW', '2026-01-02', 'COMPLETED')")
    promote_run_to_active("NEW", db_path=str(db))
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT run_id, status, published_at_utc FROM pipeline_runs ORDER BY run_id").fetchall()
    assert rows[0][:2] == ("NEW", "ACTIVE")
    assert datetime.fromisoformat(rows[0][2]).utcoffset() == timedelta(0)
    assert rows[1] == ("OLD", "ARCHIVED", None)


def test_rejected_promotion_does_not_migrate_or_change_active(tmp_path):
    db = tmp_path / "factory.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, timestamp TEXT, status TEXT)")
        conn.execute("INSERT INTO pipeline_runs VALUES ('OLD', '2026-01-01', 'ACTIVE')")
        conn.execute("INSERT INTO pipeline_runs VALUES ('BAD', '2026-01-02', 'RUNNING')")
    with pytest.raises(ValueError, match="COMPLETED"):
        promote_run_to_active("BAD", db_path=str(db))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM pipeline_runs WHERE run_id = 'OLD'").fetchone() == ("ACTIVE",)
        assert "published_at_utc" not in {row[1] for row in conn.execute("PRAGMA table_info(pipeline_runs)")}
