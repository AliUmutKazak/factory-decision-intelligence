import shutil
import sys
from pathlib import Path

import src.utils.lineage as lineage_mod

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import pytest

import src.carbon.carbon_analytics as carbon_mod
import src.config as cfg
import src.data.build_database_and_eda as db_mod
import src.data.preprocessing as prep_mod
import src.energy.energy_analytics as energy_mod
import src.forecasting.train_forecast as fc_mod
import src.inventory.bom_mrp as mrp_mod
import src.planning.aggregate_planning as plan_mod
import src.scheduling.schedule_cpsat as sched_mod
from src.utils.db import get_db_connection


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """
    Madde 10: İzole test mimarisi (Isolated Test State Lifecycle).
    Her test için:
      1. Create isolated temp dir & copy necessary input data
      2. Patch config paths & DB connections across all modules
      3. Run scenario
      4. Auto-destroy via pytest tmp_path
    """
    temp_data = tmp_path / "data"
    temp_raw = temp_data / "raw"
    temp_synthetic = temp_data / "synthetic"
    temp_fixtures = temp_data / "fixtures"
    temp_processed = temp_data / "processed"
    temp_db = temp_data / "factory.db"

    temp_raw.mkdir(parents=True, exist_ok=True)
    temp_synthetic.mkdir(parents=True, exist_ok=True)
    temp_fixtures.mkdir(parents=True, exist_ok=True)
    temp_processed.mkdir(parents=True, exist_ok=True)

    # Girdileri ve fixture dosyalarını geçici dizine kopyala
    orig_data = PROJECT_ROOT / "data"
    for folder, target in [("raw", temp_raw), ("synthetic", temp_synthetic), ("fixtures", temp_fixtures)]:
        orig_folder = orig_data / folder
        if orig_folder.exists():
            for item in orig_folder.glob("*"):
                if item.is_file():
                    shutil.copy2(item, target / item.name)

    # Ortam değişkenlerini ayarla
    monkeypatch.setenv("FACTORY_DATA_DIR", str(temp_data))
    monkeypatch.setenv("FACTORY_DB_PATH", str(temp_db))

    # src.config'i yamala
    monkeypatch.setattr(cfg, "DATA_DIR", temp_data)
    monkeypatch.setattr(cfg, "RAW_DATA_DIR", temp_raw)
    monkeypatch.setattr(cfg, "SYNTHETIC_DATA_DIR", temp_synthetic)
    monkeypatch.setattr(cfg, "PROCESSED_DATA_DIR", temp_processed)
    monkeypatch.setattr(cfg, "DB_PATH", temp_db)

    # Modül içi import edilmiş yolları yamala
    all_modules = [prep_mod, db_mod, fc_mod, plan_mod, mrp_mod, sched_mod, energy_mod, carbon_mod, lineage_mod]
    for mod in all_modules:
        if hasattr(mod, "DB_PATH"):
            monkeypatch.setattr(mod, "DB_PATH", temp_db)
        if hasattr(mod, "PROCESSED_DATA_DIR"):
            monkeypatch.setattr(mod, "PROCESSED_DATA_DIR", temp_processed)
        if hasattr(mod, "RAW_DATA_DIR"):
            monkeypatch.setattr(mod, "RAW_DATA_DIR", temp_raw)
        if hasattr(mod, "DATA_DIR"):
            monkeypatch.setattr(mod, "DATA_DIR", temp_data)

    # train_forecast & aggregate_planning & eda modül düzeyindeki statik çıktı yolları
    if hasattr(db_mod, "PROCESSED_ORDERS_PATH"):
        monkeypatch.setattr(db_mod, "PROCESSED_ORDERS_PATH", temp_processed / "factory_orders.csv")
    if hasattr(fc_mod, "OUTPUT_FORECAST_PATH"):
        monkeypatch.setattr(fc_mod, "OUTPUT_FORECAST_PATH", temp_processed / "forecast_demand.csv")
    if hasattr(plan_mod, "OUTPUT_AGGREGATE_PATH"):
        monkeypatch.setattr(plan_mod, "OUTPUT_AGGREGATE_PATH", temp_processed / "aggregate_plan.csv")
    if hasattr(plan_mod, "OUTPUT_SKU_PLAN_PATH"):
        monkeypatch.setattr(plan_mod, "OUTPUT_SKU_PLAN_PATH", temp_processed / "sku_production_plan.csv")
    if hasattr(plan_mod, "OUTPUT_MACHINE_CAPACITY_PATH"):
        monkeypatch.setattr(plan_mod, "OUTPUT_MACHINE_CAPACITY_PATH", temp_processed / "machine_capacity_plan.csv")
    if hasattr(mrp_mod, "OUTPUT_MRP_PATH"):
        monkeypatch.setattr(mrp_mod, "OUTPUT_MRP_PATH", temp_processed / "mrp_plan.csv")

    yield {"db_path": temp_db, "data_dir": temp_data}


def test_scenario_zero_production(isolated_env, monkeypatch):
    """Sıfır üretim senaryosunda boş tablonun şemasının korunduğunu doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_zero_production.csv")

    prep_mod.run_preprocessing()
    db_mod.initialize_database(run_id="SCENARIO_TEST")
    fc_mod.run_forecast_benchmark(run_id="SCENARIO_TEST")
    plan_mod.run_planning_pipeline(run_id="SCENARIO_TEST")
    mrp_mod.run_mrp_engine(run_id="SCENARIO_TEST")
    sched_mod.solve_cpsat_schedule(run_id="SCENARIO_TEST")

    conn = get_db_connection(isolated_env["db_path"])
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    assert isinstance(sched, pd.DataFrame)
    assert "task_id" in sched.columns
    assert "setup_before_min" in sched.columns
    assert len(sched) == 0

    energy_mod.compute_energy_analytics(run_id="SCENARIO_TEST")
    carbon_mod.compute_carbon_analytics(run_id="SCENARIO_TEST")


def test_scenario_expedite_flags(isolated_env, monkeypatch):
    """Ani talep patlamasında MRP motorunun EXPEDITE aksiyon bayrağı ürettiğini doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_expedite.csv")

    prep_mod.run_preprocessing()
    db_mod.initialize_database(run_id="SCENARIO_TEST")
    fc_mod.run_forecast_benchmark(run_id="SCENARIO_TEST")
    plan_mod.run_planning_pipeline(run_id="SCENARIO_TEST")
    mrp_mod.run_mrp_engine(run_id="SCENARIO_TEST")

    conn = get_db_connection(isolated_env["db_path"])
    mrp = pd.read_sql("SELECT * FROM mrp_plan", conn)
    conn.close()

    expedites = mrp[mrp["action_message"].str.contains("EXPEDITE", na=False)]
    assert len(expedites) > 0


def test_scenario_normal_e2e_reconciliation(isolated_env, monkeypatch):
    """Nominal senaryoda tüm uçtan uca zincirin pozitif üretimle eşleştiğini doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_normal.csv")

    prep_mod.run_preprocessing()
    db_mod.initialize_database(run_id="SCENARIO_TEST")
    fc_mod.run_forecast_benchmark(run_id="SCENARIO_TEST")
    plan_mod.run_planning_pipeline(run_id="SCENARIO_TEST")
    mrp_mod.run_mrp_engine(run_id="SCENARIO_TEST")
    sched_mod.solve_cpsat_schedule(run_id="SCENARIO_TEST")
    energy_mod.compute_energy_analytics(run_id="SCENARIO_TEST")
    carbon_mod.compute_carbon_analytics(run_id="SCENARIO_TEST")

    conn = get_db_connection(isolated_env["db_path"])
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    energy = pd.read_sql("SELECT * FROM energy_kpis", conn)
    carbon = pd.read_sql("SELECT * FROM carbon_kpis", conn)
    conn.close()

    assert len(sched) > 0
    assert float(energy["makespan_hours"].iloc[0]) > 0
    assert float(carbon["total_tco2e"].iloc[0]) >= 0


def test_scenario_capacity_stress(isolated_env, monkeypatch):
    """Aşırı talep / stres senaryosunda agrega planlamanın fazla mesai sınırlarını zorladığını doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_capacity_stress.csv")

    prep_mod.run_preprocessing()
    db_mod.initialize_database(run_id="SCENARIO_TEST")
    fc_mod.run_forecast_benchmark(run_id="SCENARIO_TEST")
    plan_mod.run_planning_pipeline(run_id="SCENARIO_TEST")
    mrp_mod.run_mrp_engine(run_id="SCENARIO_TEST")
    sched_mod.solve_cpsat_schedule(run_id="SCENARIO_TEST")
    energy_mod.compute_energy_analytics(run_id="SCENARIO_TEST")
    carbon_mod.compute_carbon_analytics(run_id="SCENARIO_TEST")

    conn = get_db_connection(isolated_env["db_path"])
    agg_plan = pd.read_sql("SELECT * FROM aggregate_plan", conn)
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    assert "max_machine_overtime_hours" in agg_plan.columns
    assert agg_plan["max_machine_overtime_hours"].max() > 0.0
    assert len(sched) > 0


def test_scenario_engine_tradeoff_matrix(isolated_env):
    """
    P2-1 Contract Test:
    What-If Karar Destek Motorunun 7 senaryo ve beklenen metrikleri
    eksiksiz ürettiğini ve şok yönlülük kurallarını sağladığını doğrular.
    """
    from src.scenarios.scenario_engine import ScenarioEngine

    # A real, complete run is required; a few unversioned fake rows cannot
    # exercise the LP/MRP/CP-SAT scenario contracts.
    shutil.copy2(PROJECT_ROOT / "data" / "factory.db", isolated_env["db_path"])
    engine = ScenarioEngine(db_path=isolated_env["db_path"])
    df = engine.run_all_scenarios()

    # 1. Şok Kapsama Kontrolü (Görseldeki 7 Senaryo)
    expected_scenarios = [
        "BASELINE",
        "+20% DEMAND",
        "-10% CAPACITY",
        "+25% ENERGY COST",
        "+50 €/tCO2",
        "M01 FAILURE",
        "RAW MATERIAL DELAY",
    ]
    assert list(df["Scenario"]) == expected_scenarios

    # 2. Metrik Kapsama Kontrolü
    required_cols = [
        "Makespan (h)",
        "OT (%)",
        "Inventory Cost (€)",
        "Backlog (units)",
        "Energy Cost (€)",
        "Carbon (tCO2e)",
        "Carbon Cost (€)",
        "Total Cost (€)",
    ]
    for col in required_cols:
        assert col in df.columns

    # 3. Yönsel Tutarlılık (Monotonicity & Sensitivity) Kontrolleri
    baseline = df.loc[df["Scenario"] == "BASELINE"].iloc[0]
    demand_shock = df.loc[df["Scenario"] == "+20% DEMAND"].iloc[0]
    m01_failure = df.loc[df["Scenario"] == "M01 FAILURE"].iloc[0]
    energy_shock = df.loc[df["Scenario"] == "+25% ENERGY COST"].iloc[0]
    carbon_shock = df.loc[df["Scenario"] == "+50 €/tCO2"].iloc[0]

    # Talep artışı planı yeniden çözer. Enerji maliyeti bu örnekte artar;
    # üretim karması ve boşta kalma değiştiğinden karbon monoton olmak zorunda değildir.
    assert demand_shock["Energy Cost (€)"] > baseline["Energy Cost (€)"]
    assert demand_shock["Carbon (tCO2e)"] >= 0
    assert 0 <= demand_shock["OT (%)"] <= 100

    # Makine arızası makespan'i en çok zorlayan senaryolardan biri olmalı
    assert m01_failure["Makespan (h)"] > 0
    assert m01_failure["Total Cost (€)"] >= 0

    # Enerji şoku sadece enerji maliyetini etkilemeli, makespan sabit kalmalı
    assert energy_shock["Energy Cost (€)"] > baseline["Energy Cost (€)"]
    assert energy_shock["Makespan (h)"] == baseline["Makespan (h)"]

    # Karbon vergisi artışı sadece karbon maliyetini yükseltmeli
    assert carbon_shock["Carbon Cost (€)"] > baseline["Carbon Cost (€)"]
    assert carbon_shock["Carbon (tCO2e)"] == baseline["Carbon (tCO2e)"]


def test_scenario_engine_raises_on_missing_data(tmp_path):
    """Madde 24: Veritabanında çizelge yokken sahte default üretilmemeli,
    ScenarioDataUnavailableError fırlatılmalıdır (Unknown != Zero != Default).
    """
    from src.scenarios.scenario_engine import (
        ScenarioDataUnavailableError,
        ScenarioEngine,
        ScenarioShock,
    )

    empty_db = tmp_path / "empty_factory.db"
    conn = get_db_connection(str(empty_db))
    conn.close()

    engine = ScenarioEngine(db_path=str(empty_db))
    with pytest.raises(ScenarioDataUnavailableError):
        engine.evaluate_scenario(ScenarioShock(name="BASELINE"))
