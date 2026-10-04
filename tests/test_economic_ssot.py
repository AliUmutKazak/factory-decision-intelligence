"""Tests for Economic SSOT and Unit/Currency Contracts (Faz 2 - Madde 9 & 10)."""

import pytest
from pydantic import ValidationError

from src.config import ECONOMIC_CONFIG, EconomicConfig
from src.contracts.schemas import CurrencyCode, EconomicConfigModel, EnergyUnit, MassUnit, TimeUnit


def test_economic_config_singleton_instance():
    """ECONOMIC_CONFIG'in Pydantic EconomicConfigModel örneği olduğunu doğrular."""
    assert isinstance(ECONOMIC_CONFIG, EconomicConfigModel)
    assert ECONOMIC_CONFIG.currency == CurrencyCode.EUR
    assert ECONOMIC_CONFIG.currency_symbol == "€"
    assert ECONOMIC_CONFIG.labor_rate_per_hour == 25.0
    assert ECONOMIC_CONFIG.labor_overtime_rate == 37.5


def test_economic_config_explicit_units():
    """Birim haritasının para birimiyle tutarlı açık etiketler ürettiğini doğrular."""
    units = ECONOMIC_CONFIG.units
    assert units["labor_standard_rate"] == "EUR/hour"
    assert units["energy_rate"] == "EUR/kWh"
    assert units["carbon_price"] == "EUR/tCO2e"


def test_unit_and_currency_enums():
    """Temel birim sözleşmelerinin doğruluğunu test eder."""
    assert CurrencyCode.EUR == "EUR"
    assert TimeUnit.HOUR == "hour"
    assert EnergyUnit.KWH == "kWh"
    assert MassUnit.TON == "ton"


def test_economic_config_validation_rules():
    """Geçersiz veya negatif parametrelerin ValidationError fırlattığını doğrular."""
    # Negatif veya 0 işçilik saat ücreti engellenmeli (gt=0)
    with pytest.raises(ValidationError):
        EconomicConfig(labor_rate_per_hour=-10.0)

    with pytest.raises(ValidationError):
        EconomicConfig(labor_rate_per_hour=0.0)

    # 1.0'dan küçük fazla mesai çarpanı engellenmeli (ge=1.0)
    with pytest.raises(ValidationError):
        EconomicConfig(overtime_multiplier=0.8)

    # Negatif enerji fiyatı engellenmeli (gt=0)
    with pytest.raises(ValidationError):
        EconomicConfig(energy_price_per_kwh=-0.05)
