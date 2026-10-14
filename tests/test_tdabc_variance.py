"""The modeled runtime variance must not invent a cause or realized saving."""

import pytest

from src.economics.cost_to_serve import compute_tdabc_variance


def test_tdabc_variance_with_downtime():
    """Reported downtime is retained separately from causal attribution."""
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
    assert result.primary_reason == "unattributed_runtime_overrun"
    assert result.to_dict()["reported_downtime_hours"] == 4.0
    assert result.to_dict()["capacity_cost_rate_per_hour"] == 50.0


def test_tdabc_variance_speed_loss():
    """Extra runtime alone does not prove a speed loss or micro-stops."""
    result = compute_tdabc_variance(
        order_id="ORD-102",
        planned_runtime_hours=8.0,
        actual_runtime_hours=9.5,
        capacity_cost_rate_per_hour=40.0,
        downtime_hours=0.0,
    )

    assert result.variance == 60.0
    assert result.primary_reason == "unattributed_runtime_overrun"


def test_tdabc_variance_efficiency_gain():
    """Less modeled runtime cost is not a realized efficiency gain."""
    result = compute_tdabc_variance(
        order_id="ORD-103",
        planned_runtime_hours=12.0,
        actual_runtime_hours=10.0,
        capacity_cost_rate_per_hour=45.0,
        downtime_hours=0.0,
    )

    assert result.variance == -90.0
    assert result.primary_reason == "unattributed_runtime_underrun"


@pytest.mark.parametrize("invalid", [float("nan"), -1.0])
def test_tdabc_variance_rejects_invalid_rate(invalid):
    with pytest.raises(ValueError, match="capacity_cost_rate_per_hour"):
        compute_tdabc_variance("ORD-104", 8.0, 7.0, invalid)
