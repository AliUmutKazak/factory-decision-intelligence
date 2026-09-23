import sqlite3
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import pandas as pd
from src.data.preprocessing import run_preprocessing
from src.data.build_database_and_eda import initialize_database
from src.forecasting.train_forecast import run_forecast_benchmark
from src.planning.aggregate_planning import run_planning_pipeline
from src.inventory.bom_mrp import run_mrp_engine
from src.scheduling.schedule_cpsat import solve_cpsat_schedule
from src.energy.energy_analytics import compute_energy_analytics
from src.carbon.carbon_analytics import compute_carbon_analytics

def test_scenario_zero_production(monkeypatch):
    """Sıfır üretim senaryosunda boş tablonun şemasının korunduğunu ve SQLite/CSV'ye yazıldığını doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_zero_production.csv")
    run_preprocessing()
    initialize_database()
    run_forecast_benchmark()
    run_planning_pipeline()
    run_mrp_engine()
    solve_cpsat_schedule()
    
    conn = sqlite3.connect(PROJECT_ROOT / "data" / "factory.db")
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()
    assert isinstance(sched, pd.DataFrame)
    assert "task_id" in sched.columns
    assert "setup_before_min" in sched.columns
    assert len(sched) == 0
    
    # Enerji ve karbon modülleri sıfır üretim tablosunda hatasız koşabilmeli
    compute_energy_analytics()
    compute_carbon_analytics()

def test_scenario_expedite_flags(monkeypatch):
    """Ani talep patlamasında MRP motorunun EXPEDITE aksiyon bayrağı ürettiğini doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_expedite.csv")
    run_preprocessing()
    initialize_database()
    run_forecast_benchmark()
    run_planning_pipeline()
    run_mrp_engine()
    
    conn = sqlite3.connect(PROJECT_ROOT / "data" / "factory.db")
    mrp = pd.read_sql("SELECT * FROM mrp_plan", conn)
    conn.close()
    expedites = mrp[mrp["action_message"].str.contains("EXPEDITE", na=False)]
    assert len(expedites) > 0

def test_scenario_normal_e2e_reconciliation(monkeypatch):
    """Nominal senaryoda tüm uçtan uca zincirin pozitif üretimle eşleştiğini doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_normal.csv")
    run_preprocessing()
    initialize_database()
    run_forecast_benchmark()
    run_planning_pipeline()
    run_mrp_engine()
    solve_cpsat_schedule()
    compute_energy_analytics()
    compute_carbon_analytics()
    
    conn = sqlite3.connect(PROJECT_ROOT / "data" / "factory.db")
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    energy = pd.read_sql("SELECT * FROM energy_kpis", conn)
    carbon = pd.read_sql("SELECT * FROM carbon_kpis", conn)
    conn.close()
    
    assert len(sched) > 0
    assert float(energy["makespan_hours"].iloc[0]) > 0
    assert float(carbon["total_tco2e"].iloc[0]) >= 0

def test_scenario_capacity_stress(monkeypatch):
    """Aşırı talep / stres senaryosunda agrega planlamanın fazla mesai sınırlarını zorladığını ve darboğaz oluştuğunu doğrular."""
    monkeypatch.setenv("USE_FIXTURE", "fixture_capacity_stress.csv")
    run_preprocessing()
    initialize_database()
    run_forecast_benchmark()
    run_planning_pipeline()
    run_mrp_engine()
    solve_cpsat_schedule()
    compute_energy_analytics()
    from src.carbon.carbon_analytics import compute_carbon_analytics
    compute_carbon_analytics()

    conn = sqlite3.connect(PROJECT_ROOT / "data" / "factory.db")
    agg_plan = pd.read_sql("SELECT * FROM aggregate_plan", conn)
    sched = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    # 1. Aşırı talep altında fazla mesai (overtime) sıfırdan büyük olmalı
    assert "max_machine_overtime_hours" in agg_plan.columns
    assert agg_plan["max_machine_overtime_hours"].max() > 0.0

    # 2. Operasyonel çizelgede görevlerin başarıyla yerleştirildiği doğrulanmalı
    assert len(sched) > 0
    assert "start_min" in sched.columns
    assert "end_min" in sched.columns    