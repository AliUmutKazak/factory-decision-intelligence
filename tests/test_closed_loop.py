import sqlite3

import pandas as pd
import pytest

from src.data.build_database_and_eda import initialize_database
from src.scenarios.closed_loop import ClosedLoopEngine
from src.utils.lineage import start_pipeline_run


def test_closed_loop_normal_execution(tmp_path, monkeypatch):
    """Tolerans limitleri içindeki üretimde replanning tetiklenmediğini doğrular."""
    db_file = tmp_path / "factory_closed_loop.db"
    monkeypatch.setenv("FACTORY_DB_PATH", str(db_file))
    initialize_database()

    # 1. Foreign Key kısıtını sağlamak için geçerli bir pipeline run kaydı oluştur
    run_id = "RUN-TEST-001"
    start_pipeline_run(run_id=run_id, db_path=str(db_file))

    engine = ClosedLoopEngine(db_path=str(db_file), slippage_threshold_pct=10.0, max_delay_hours=4.0)

    # 2. Nominal saha verisi (Plan ile neredeyse birebir)
    actuals = pd.DataFrame([
        {
            "task_id": "T01",
            "product_id": "P01",
            "machine_id": "M01",
            "planned_start_hour": 0.0,
            "planned_end_hour": 10.0,
            "actual_start_hour": 0.0,
            "actual_end_hour": 10.5,
            "actual_units": 100,
            "scrap_units": 1,
            "downtime_hours": 0.0,
            "status": "COMPLETED",
        }
    ])
    engine.ingest_mes_actuals(actuals, run_id=run_id)

    decision = engine.evaluate_variance_and_trigger(run_id)
    assert not decision.requires_replanning
    assert decision.schedule_slippage_pct < 10.0


def test_closed_loop_triggers_replanning_on_slippage(tmp_path, monkeypatch):
    """Büyük duruş veya gecikme durumunda sistemin replanning kararı aldığını doğrular."""
    db_file = tmp_path / "factory_closed_loop.db"
    monkeypatch.setenv("FACTORY_DB_PATH", str(db_file))
    initialize_database()

    # 1. Foreign Key kısıtını sağlamak için geçerli bir pipeline run kaydı oluştur
    run_id = "RUN-TEST-002"
    start_pipeline_run(run_id=run_id, db_path=str(db_file))

    engine = ClosedLoopEngine(db_path=str(db_file), slippage_threshold_pct=10.0, max_delay_hours=4.0)

    # 2. Arıza ve yüksek duruş içeren saha verisi (M01 duruşu)
    actuals = pd.DataFrame([
        {
            "task_id": "T02",
            "product_id": "P02",
            "machine_id": "M01",
            "planned_start_hour": 10.0,
            "planned_end_hour": 20.0,
            "actual_start_hour": 10.0,
            "actual_end_hour": 22.0,
            "actual_units": 80,
            "scrap_units": 10,
            "downtime_hours": 5.0,  # 5 saat duruş
            "status": "COMPLETED",
        }
    ])
    engine.ingest_mes_actuals(actuals, run_id=run_id)

    decision = engine.evaluate_variance_and_trigger(run_id)
    assert decision.requires_replanning
    assert decision.total_delay_hours >= 4.0
    assert "Schedule slippage" in decision.trigger_reason or "Total delay" in decision.trigger_reason
