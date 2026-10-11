import json

import numpy as np
import pandas as pd
import pytest

from src.forecasting import train_forecast as forecast
from src.utils.db import get_db_connection


def test_wape_is_undefined_when_actual_horizon_is_zero():
    wape, rmse, bias = forecast.evaluate_metrics(np.zeros(3), np.array([0, 2, 0]))
    assert wape is None
    assert rmse > 0
    assert bias == 2


def test_short_history_fails_before_publishing_forecast(tmp_path, monkeypatch):
    history = pd.DataFrame(
        {
            "order_date": pd.date_range("2025-01-01", periods=30),
            "product_id": "P01",
            "demand": 1,
        }
    )
    monkeypatch.setattr(forecast, "load_factory_demand", lambda *args, **kwargs: history)
    monkeypatch.setenv("FACTORY_PROCESSED_DIR", str(tmp_path / "processed"))
    with pytest.raises(ValueError, match="rolling-origin folds"):
        forecast.run_forecast_benchmark(run_id="SHORT", db_path=tmp_path / "test.db")
    assert not (tmp_path / "processed" / "forecast_demand.csv").exists()


def test_all_zero_demand_uses_rmse_and_keeps_json_finite(tmp_path, monkeypatch):
    n = 4 * forecast.HORIZON_DAYS + 28
    history = pd.DataFrame(
        {
            "order_date": pd.date_range("2025-01-01", periods=n),
            "product_id": "P01",
            "demand": 0,
        }
    )
    monkeypatch.setattr(forecast, "load_factory_demand", lambda *args, **kwargs: history)
    monkeypatch.setenv("FACTORY_PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("FACTORY_REPORTS_DIR", str(tmp_path / "reports"))
    result = forecast.run_forecast_benchmark(run_id="ZERO", db_path=tmp_path / "test.db")

    with get_db_connection(tmp_path / "test.db") as conn:
        row = conn.execute(
            "SELECT selected_model, backtest_wape, selection_reason, competing_models, hyperparameters "
            "FROM forecast_model_lineage WHERE run_id = 'ZERO'"
        ).fetchone()
    assert row[0] == "Naive"
    assert row[1] is None
    assert "RMSE" in row[2]
    assert json.loads(row[3])["Naive"]["backtest_wape"] is None
    assert json.loads(row[4])["uncertainty_method"] == "normal_rmse_heuristic_uncalibrated"
    assert (result["forecast_demand"] == 0).all()
