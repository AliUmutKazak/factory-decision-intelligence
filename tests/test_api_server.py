"""API Servis Uç Noktaları Entegrasyon Testleri."""

from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"


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
    response = client.post("/api/v1/schedule/what-if/breakdown", json=payload)
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
    response = client.post("/api/v1/schedule/what-if/hot-order", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["scenario_type"] == "HOT_ORDER_INJECTION"


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
