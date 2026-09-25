import src.utils.lineage as lineage_mod
import sqlite3
import os
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import pandas as pd

import src.config as cfg
import src.data.preprocessing as prep_mod
import src.data.build_database_and_eda as db_mod
import src.forecasting.train_forecast as fc_mod
import src.planning.aggregate_planning as plan_mod
import src.inventory.bom_mrp as mrp_mod
import src.scheduling.schedule_cpsat as sched_mod
import src.energy.energy_analytics as energy_mod
import src.carbon.carbon_analytics as carbon_mod


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
    db_mod.initialize_database()
    fc_mod.run_forecast_benchmark()
    plan_mod.run_planning_pipeline()
    mrp_mod.run_mrp_engine()
    sched_mod.solve_cpsat_schedule()

    conn = sqlite3.connect(isolated_env["db_path"])
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    assert isinstance(sched, pd.DataFrame)
    assert "task_id" in sched.columns
    assert "setup_before_min" in sched.columns
    assert len(sched) == 0

    energy_mod.compute_energy_analytics()
    carbon_mod.compute_carbon_analytics()


def test_scenario_expedite_flags(isolated_env, monkeypatch):
    """Ani talep patlamasında MRP motorunun EXPEDITE aksiyon bayrağı ürettiğini doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_expedite.csv")
    
    prep_mod.run_preprocessing()
    db_mod.initialize_database()
    fc_mod.run_forecast_benchmark()
    plan_mod.run_planning_pipeline()
    mrp_mod.run_mrp_engine()

    conn = sqlite3.connect(isolated_env["db_path"])
    mrp = pd.read_sql("SELECT * FROM mrp_plan", conn)
    conn.close()

    expedites = mrp[mrp["action_message"].str.contains("EXPEDITE", na=False)]
    assert len(expedites) > 0


def test_scenario_normal_e2e_reconciliation(isolated_env, monkeypatch):
    """Nominal senaryoda tüm uçtan uca zincirin pozitif üretimle eşleştiğini doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_normal.csv")
    
    prep_mod.run_preprocessing()
    db_mod.initialize_database()
    fc_mod.run_forecast_benchmark()
    plan_mod.run_planning_pipeline()
    mrp_mod.run_mrp_engine()
    sched_mod.solve_cpsat_schedule()
    energy_mod.compute_energy_analytics()
    carbon_mod.compute_carbon_analytics()

    conn = sqlite3.connect(isolated_env["db_path"])
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
    db_mod.initialize_database()
    fc_mod.run_forecast_benchmark()
    plan_mod.run_planning_pipeline()
    mrp_mod.run_mrp_engine()
    sched_mod.solve_cpsat_schedule()
    energy_mod.compute_energy_analytics()
    carbon_mod.compute_carbon_analytics()

    conn = sqlite3.connect(isolated_env["db_path"])
    agg_plan = pd.read_sql("SELECT * FROM aggregate_plan", conn)
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    assert "max_machine_overtime_hours" in agg_plan.columns
    assert agg_plan["max_machine_overtime_hours"].max() > 0.0
    assert len(sched) > 0