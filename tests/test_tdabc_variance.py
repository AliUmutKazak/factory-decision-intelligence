"""Tests for Time-Driven Activity-Based Costing (TDABC) and Variance Analysis (Madde 33)."""

from src.economics.cost_to_serve import compute_tdabc_variance


def test_tdabc_variance_with_downtime():
    """Downtime kaynaklı süre aşımında maliyet sapması ve neden teşhisini doğrular."""
    result = compute_tdabc_variance(
        order_id="ORD-101",
        planned_runtime_hours=10.0,
        actual_runtime_hours=14.0,
        capacity_cost_rate_per_hour=50.0,
        downtime_hours=4.0,
    )

    assert result.order_id == "ORD-101"
    assert result.planned_cost == 500.0
    assert result.actual_cost == 700.0
    assert result.variance == 200.0
    assert "downtime" in result.primary_reason


def test_tdabc_variance_speed_loss():
    """Arıza olmaksızın yavaş çalışma durumunda mikro duruş / hız kaybı teşhisini doğrular."""
    result = compute_tdabc_variance(
        order_id="ORD-102",
        planned_runtime_hours=8.0,
        actual_runtime_hours=9.5,
        capacity_cost_rate_per_hour=40.0,
        downtime_hours=0.0,
    )

    assert result.variance == 60.0
    assert result.primary_reason == "speed_loss / micro_stops"


def test_tdabc_variance_efficiency_gain():
    """Planlanandan erken tamamlanan operasyonlarda verimlilik kazancını doğrular."""
    result = compute_tdabc_variance(
        order_id="ORD-103",
        planned_runtime_hours=12.0,
        actual_runtime_hours=10.0,
        capacity_cost_rate_per_hour=45.0,
        downtime_hours=0.0,
    )

    assert result.variance == -90.0
    assert result.primary_reason == "efficiency_gain"
