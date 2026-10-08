"""Tests for Scenario Engine Contracts (Faz 3 - Scenario Shock & Result Validation)."""

from contextlib import closing

import pytest
from pydantic import ValidationError

from src.contracts.schemas import ScenarioResultModel, ScenarioShockModel
from src.scenarios.scenario_engine import ScenarioResult


def test_scenario_matrix_pins_one_baseline_during_active_promotion(tmp_path, monkeypatch):
    import sqlite3

    from src.scenarios.scenario_engine import ScenarioEngine, ScenarioShock
    from src.utils.db import get_active_run_id

    db = tmp_path / "factory.db"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE pipeline_runs(run_id TEXT, status TEXT)")
        conn.execute("INSERT INTO pipeline_runs VALUES ('OLD', 'ACTIVE')")
    observed = []

    def evaluate(snapshot_engine, shock):
        with closing(sqlite3.connect(snapshot_engine.db_path)) as conn:
            observed.append(get_active_run_id(conn))
        if len(observed) == 1:
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute("UPDATE pipeline_runs SET status = 'ARCHIVED'")
                conn.execute("INSERT INTO pipeline_runs VALUES ('NEW', 'ACTIVE')")
        return ScenarioResult(shock.name, 0, 100, 0, 0, 0, 0, 0, 0)

    monkeypatch.setattr(ScenarioEngine, "_evaluate_scenario", evaluate)
    engine = ScenarioEngine(str(db))
    engine.scenarios = {"A": ScenarioShock("A"), "B": ScenarioShock("B")}
    result = engine.run_all_scenarios()
    assert observed == ["OLD", "OLD"]
    assert set(result["Baseline Run"]) == {"OLD"}
    with closing(sqlite3.connect(db)) as conn:
        assert get_active_run_id(conn) == "NEW"


def test_scenario_result_dataclass_contract_roundtrip():
    """ScenarioResult dataclass ile ScenarioResultModel sözleşmesi arasındaki dönüşüm ve validasyonu test eder."""
    dc = ScenarioResult(
        scenario="ENERGY_SHOCK",
        makespan_hours=130.0,
        on_time_delivery_pct=94.5,
        inventory_holding_cost_eur=1800.0,
        backlog_units=15,
        energy_cost_eur=8900.0,
        carbon_tco2e=14.2,
        carbon_cost_eur=1420.0,
        total_cost_eur=12120.0,
    )

    contract = dc.to_contract()
    assert isinstance(contract, ScenarioResultModel)
    assert contract.scenario == "ENERGY_SHOCK"
    assert contract.backlog_units == 15

    roundtrip = ScenarioResult.from_contract(contract)
    assert roundtrip.scenario == dc.scenario
    assert roundtrip.total_cost_eur == dc.total_cost_eur


def test_scenario_shock_valid_defaults():
    """Geçerli varsayılan değerlerle ScenarioShockModel nesnesinin başarıyla oluşturulduğunu doğrular."""
    shock = ScenarioShockModel(name="BASELINE")
    assert shock.name == "BASELINE"
    assert shock.demand_multiplier == 1.0
    assert shock.capacity_multiplier == 1.0
    assert shock.material_delay_days == 0
    assert shock.failed_machines == []


def test_scenario_shock_custom_parameters():
    """Özelleştirilmiş senaryo parametrelerinin doğru yüklendiğini test eder."""
    shock = ScenarioShockModel(
        name="CRISIS_EVENT",
        demand_multiplier=1.35,
        capacity_multiplier=0.75,
        electricity_price_multiplier=2.1,
        carbon_tax_delta_eur=15.0,
        objective_policy="CARBON_MIN",
        failed_machines=["CNC-01", "PRESS-02"],
        material_delay_days=3,
    )
    assert shock.name == "CRISIS_EVENT"
    assert shock.demand_multiplier == 1.35
    assert len(shock.failed_machines) == 2
    assert shock.material_delay_days == 3


@pytest.mark.parametrize(
    "invalid_kwargs",
    [
        {"name": "ERR_DEMAND", "demand_multiplier": -0.1},
        {"name": "ERR_CAPACITY", "capacity_multiplier": -1.0},
        {"name": "ERR_ELEC", "electricity_price_multiplier": -0.5},
        {"name": "ERR_DELAY", "material_delay_days": -1},
    ],
)
def test_scenario_shock_negative_multipliers_fail(invalid_kwargs):
    """Fiziksel olarak imkansız negatif çarpanların ve gecikmelerin ValidationError fırlattığını doğrular."""
    with pytest.raises(ValidationError):
        ScenarioShockModel(**invalid_kwargs)


def test_scenario_result_valid():
    """Geçerli metriklerle ScenarioResultModel nesnesinin örneklendiğini test eder."""
    result = ScenarioResultModel(
        scenario="BASELINE",
        makespan_hours=124.5,
        on_time_delivery_pct=98.2,
        inventory_holding_cost_eur=1500.0,
        backlog_units=0,
        energy_cost_eur=4250.75,
        carbon_tco2e=12.4,
        carbon_cost_eur=1240.0,
        total_cost_eur=6990.75,
    )
    assert result.scenario == "BASELINE"
    assert result.on_time_delivery_pct == 98.2
    assert result.backlog_units == 0


@pytest.mark.parametrize(
    "invalid_kwargs",
    [
        {"on_time_delivery_pct": 105.0},  # %100'den büyük olamaz
        {"on_time_delivery_pct": -5.0},  # %0'dan küçük olamaz
        {"makespan_hours": -1.0},
        {"inventory_holding_cost_eur": -100.0},
        {"backlog_units": -5},
        {"energy_cost_eur": -0.01},
        {"carbon_tco2e": -0.5},
        {"carbon_cost_eur": -10.0},
        {"total_cost_eur": -50.0},
    ],
)
def test_scenario_result_invalid_bounds_fail(invalid_kwargs):
    """Negatif maliyetlerin ve sınır dışı teslimat oranlarının ValidationError fırlattığını doğrular."""
    base_valid = {
        "scenario": "ERR_CHECK",
        "makespan_hours": 100.0,
        "on_time_delivery_pct": 95.0,
        "inventory_holding_cost_eur": 100.0,
        "backlog_units": 0,
        "energy_cost_eur": 100.0,
        "carbon_tco2e": 5.0,
        "carbon_cost_eur": 50.0,
        "total_cost_eur": 250.0,
    }
    payload = {**base_valid, **invalid_kwargs}
    with pytest.raises(ValidationError):
        ScenarioResultModel(**payload)
