import pytest

from src.economics.business_case import modeled_roi


def test_roi_uses_measured_difference_and_explicit_realization():
    result = modeled_roi(
        1000, 900, cycles_per_year=50, realization_fraction=0.5, implementation_cost=1000, annual_operating_cost=500
    )
    assert result["modeled_annual_gross_benefit"] == 2500
    assert result["first_year_net_benefit"] == 1000
    assert result["payback_months"] == 6
    assert result["first_year_roi_pct"] == pytest.approx(1000 / 1500 * 100)


def test_negative_benefit_is_preserved_and_payback_not_fabricated():
    result = modeled_roi(
        900, 1000, cycles_per_year=50, realization_fraction=1, implementation_cost=1000, annual_operating_cost=500
    )
    assert result["annual_net_benefit"] == -5500
    assert result["payback_months"] is None
    with pytest.raises(ValueError):
        modeled_roi(
            1000, 900, cycles_per_year=50, realization_fraction=2, implementation_cost=0, annual_operating_cost=0
        )
