"""API Servis Uç Noktaları Entegrasyon Testleri."""

import hashlib
import os
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from src.api.lab_auth import lab_tokens_configured, token_allows
from src.api.server import app
from src.contracts.decision_ledger import DecisionLedger, DecisionLedgerEntry

READ_TOKEN = "r" * 48
SCENARIO_TOKEN = "s" * 48
RESCHEDULE_TOKEN = "w" * 48
client = TestClient(app, headers={"Authorization": f"Bearer {RESCHEDULE_TOKEN}"})
scenario_client = TestClient(app, headers={"Authorization": f"Bearer {SCENARIO_TOKEN}"})


@pytest.fixture(autouse=True)
def lab_credentials(monkeypatch):
    monkeypatch.setenv("FDI_API_READ_TOKEN", READ_TOKEN)
    monkeypatch.setenv("FDI_API_SCENARIO_TOKEN", SCENARIO_TOKEN)
    monkeypatch.setenv("FDI_API_RESCHEDULE_TOKEN", RESCHEDULE_TOKEN)


def test_api_rejects_unconfigured_and_weak_secrets(monkeypatch):
    assert lab_tokens_configured()
    monkeypatch.setenv("FDI_API_RESCHEDULE_TOKEN", "short")
    assert not lab_tokens_configured()
    assert client.get("/api/v1/schedule/current").status_code == 503
    assert client.post("/api/v1/schedule/reschedule", json={}).status_code == 503


def test_api_deny_by_default_and_separate_roles(monkeypatch):
    called = []

    def unexpected(*args, **kwargs):
        called.append(True)
        raise AssertionError("Unauthorized solver invocation")

    monkeypatch.setattr("src.api.server.DynamicRescheduler.execute_reschedule", unexpected)
    monkeypatch.setattr("src.api.server.WhatIfEngine.simulate_breakdown", unexpected)
    anon = TestClient(app)
    read = TestClient(app, headers={"Authorization": f"Bearer {READ_TOKEN}"})
    scenario = TestClient(app, headers={"Authorization": f"Bearer {SCENARIO_TOKEN}"})
    bad = TestClient(app, headers={"Authorization": "Bearer invalid"})
    trigger = {
        "trigger": {
            "event_id": "DENY-1",
            "current_time_min": 480,
            "freeze_horizon_min": 60,
            "delay_machine_id": "M01",
            "delay_duration_min": 60,
            "reason": "Unauthorized test",
        }
    }
    breakdown = {"machine_id": "M01", "start_min": 480, "duration_min": 60, "reason": "Test"}
    for visitor in (anon, read, scenario, bad):
        assert visitor.post("/api/v1/schedule/reschedule", json=trigger).status_code == 401
    for visitor in (anon, read, bad):
        assert visitor.post("/api/v1/schedule/what-if/breakdown", json=breakdown).status_code == 401
    assert anon.get("/api/v1/schedule/current").status_code == 401
    assert read.get("/api/v1/schedule/current").status_code == 200
    assert not token_allows(READ_TOKEN, "reschedule")
    assert not called


def test_api_does_not_expose_internal_exception_text(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("secret database path and customer identifier")

    monkeypatch.setattr("src.api.server.WhatIfEngine.simulate_breakdown", fail)
    payload = {"machine_id": "M01", "start_min": 480, "duration_min": 60, "reason": "Test"}
    response = scenario_client.post("/api/v1/schedule/what-if/breakdown", json=payload)
    assert response.status_code == 500
    assert "secret" not in response.text


def test_solver_busy_rejects_request_without_invoking_solver(monkeypatch):
    from src.api import server

    called = []

    def unexpected(*args, **kwargs):
        called.append(True)
        raise AssertionError("solver should not run while busy")

    monkeypatch.setattr(server.WhatIfEngine, "simulate_breakdown", unexpected)
    payload = {"machine_id": "M01", "start_min": 480, "duration_min": 60, "reason": "Test"}
    assert server._solver_slots.acquire(blocking=False)
    try:
        response = scenario_client.post("/api/v1/schedule/what-if/breakdown", json=payload)
    finally:
        server._solver_slots.release()
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "SOLVER_BUSY"
    assert response.headers["Retry-After"] == "1"
    assert not called


def test_cross_process_solver_busy_maps_to_retryable_api_response(monkeypatch):
    from src.utils.solver_slot import SolverBusyError

    def busy(*args, **kwargs):
        raise SolverBusyError("runtime path must stay private")

    monkeypatch.setattr("src.api.server.WhatIfEngine.simulate_breakdown", busy)
    payload = {"machine_id": "M01", "start_min": 480, "duration_min": 60, "reason": "Test"}
    response = scenario_client.post("/api/v1/schedule/what-if/breakdown", json=payload)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "SOLVER_BUSY"
    assert "runtime path" not in response.text


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"


def test_readiness_returns_the_same_active_version_as_schedule():
    ready = client.get("/ready")
    assert ready.status_code == 200
    schedule = client.get("/api/v1/schedule/current?limit=5").json()
    assert schedule
    assert {task["run_id"] for task in schedule} == {ready.json()["run_id"]}


def test_readiness_rejects_missing_runtime_without_creating_database(tmp_path, monkeypatch):
    target = tmp_path / "absent.db"
    monkeypatch.setenv("FACTORY_DB_PATH", str(target))
    assert client.get("/ready").status_code == 503
    assert not target.exists()


def test_readiness_rejects_corrupt_database(tmp_path, monkeypatch):
    target = tmp_path / "corrupt.db"
    target.write_bytes(b"not a sqlite database")
    monkeypatch.setenv("FACTORY_DB_PATH", str(target))
    assert client.get("/ready").status_code == 503


def test_decisions_query_does_not_create_a_table(tmp_path, monkeypatch):
    target = tmp_path / "without-ledger.db"
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TABLE pipeline_runs (run_id TEXT, status TEXT)")
        conn.execute("INSERT INTO pipeline_runs VALUES ('A', 'ACTIVE')")
    monkeypatch.setenv("FACTORY_DB_PATH", str(target))
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    assert client.get("/api/v1/decisions").json() == []
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


def test_decisions_remain_on_one_snapshot_during_atomic_publication(tmp_path, monkeypatch):
    import src.api.server as server

    target = tmp_path / "canonical.db"
    replacement = tmp_path / "replacement.db"
    for path, run_id in ((target, "OLD"), (replacement, "NEW")):
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("CREATE TABLE pipeline_runs (run_id TEXT, status TEXT)")
            conn.execute("INSERT INTO pipeline_runs VALUES (?, 'ACTIVE')", (run_id,))
        DecisionLedger(path).record(
            DecisionLedgerEntry(
                decision_id=f"D-{run_id}",
                run_id=run_id,
                decision_type="RESCHEDULE",
                input_state={},
                triggered_reason="test",
                selected_action="version",
            )
        )
    monkeypatch.setenv("FACTORY_DB_PATH", str(target))
    resolve = server.require_active_run_id

    def promote_after_resolving(conn):
        active = resolve(conn)
        os.replace(replacement, target)
        return active

    monkeypatch.setattr(server, "require_active_run_id", promote_after_resolving)
    response = client.get("/api/v1/decisions")
    assert response.status_code == 200
    assert [row["decision_id"] for row in response.json()] == ["D-OLD"]
    with closing(sqlite3.connect(target)) as conn:
        assert conn.execute("SELECT run_id FROM pipeline_runs").fetchone()[0] == "NEW"


def test_get_current_schedule():
    response = client.get("/api/v1/schedule/current?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_what_if_breakdown_endpoint():
    payload = {
        "machine_id": "M01",
        "start_min": 480,
        "duration_min": 120,
        "reason": "API Breakdown Test",
    }
    response = scenario_client.post("/api/v1/schedule/what-if/breakdown", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "comparison_report" in data


def test_what_if_hot_order_endpoint():
    payload = {
        "order_id": "HOT-API-TEST-01",
        "product_id": "P01",
        "quantity": 300,
        "due_date_min": 2880,
        "priority_weight": 5.0,
    }
    response = scenario_client.post("/api/v1/schedule/what-if/hot-order", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["scenario_type"] == "HOT_ORDER_INJECTION"


@pytest.mark.parametrize(
    ("path", "method", "payload"),
    [
        (
            "/api/v1/schedule/what-if/breakdown",
            "src.api.server.WhatIfEngine.simulate_breakdown",
            {"machine_id": "M01", "start_min": 480, "duration_min": 120, "reason": "Test"},
        ),
        (
            "/api/v1/schedule/what-if/hot-order",
            "src.api.server.WhatIfEngine.simulate_hot_order",
            {
                "order_id": "HOT-TIMEOUT",
                "product_id": "P01",
                "quantity": 300,
                "due_date_min": 2880,
                "priority_weight": 5.0,
            },
        ),
        (
            "/api/v1/schedule/reschedule",
            "src.api.server.DynamicRescheduler.execute_reschedule",
            {
                "trigger": {
                    "event_id": "EVT-TIMEOUT",
                    "current_time_min": 480,
                    "freeze_horizon_min": 60,
                    "delay_machine_id": "M01",
                    "delay_duration_min": 60,
                    "reason": "Test",
                }
            },
        ),
    ],
)
def test_solver_timeout_is_explicit_and_retryable(monkeypatch, path, method, payload):
    def timeout(*args, **kwargs):
        raise TimeoutError("solver exhausted")

    monkeypatch.setattr(method, timeout)
    authorized_client = scenario_client if "/what-if/" in path else client
    response = authorized_client.post(path, json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SOLVER_TIMEOUT"


def test_dynamic_reschedule_endpoint():
    payload = {
        "trigger": {
            "event_id": "EVT-API-01",
            "current_time_min": 480,
            "freeze_horizon_min": 60,
            "delay_machine_id": "M01",
            "delay_duration_min": 60,
            "reason": "API Reschedule Integration Test",
        },
        "new_run_id": "RUN_API_TEST",
    }
    response = client.post("/api/v1/schedule/reschedule", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "audit_id" in data
    assert "nervousness_report" in data
    history = client.get("/api/v1/schedule/audit-log")
    assert history.status_code == 200
    entry = next(row for row in history.json() if row["audit_id"] == data["audit_id"])
    assert entry["new_run_id"] == data["new_run_id"]
    assert entry["created_at"]
