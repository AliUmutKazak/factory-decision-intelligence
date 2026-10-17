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


def test_failed_holt_winters_fit_is_not_scored_as_holt_winters(monkeypatch):
    def fail_fit(*_args, **_kwargs):
        raise ValueError("failed fit")

    monkeypatch.setattr(forecast, "ExponentialSmoothing", fail_fit)
    train = pd.DataFrame({"demand": [1] * 28})
    test = pd.DataFrame({"demand": [1] * 28})
    with pytest.raises(forecast.ForecastCandidateUnavailable, match="Holt-Winters fit failed"):
        forecast.evaluate_fold_model("Holt-Winters", train, test, 28)


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
            "SELECT selected_model, backtest_wape, selection_reason, competing_models, hyperparameters, "
            "test_score_rmse "
            "FROM forecast_model_lineage WHERE run_id = 'ZERO'"
        ).fetchone()
    assert row[0] == "Naive"
    assert row[1] is None
    assert "RMSE" in row[2]
    competitors = json.loads(row[3])
    assert competitors["Naive"]["backtest_wape"] is None
    assert competitors["LightGBM"]["status"] == "EXCLUDED_SELECTION"
    assert "lag-complete" in competitors["LightGBM"]["failure_reason"]
    assert json.loads(row[4])["uncertainty_method"] == "normal_rmse_heuristic_uncalibrated"
    assert json.loads(row[4])["holdout_wape"] is None
    assert row[5] == 0.0
    assert (result["forecast_demand"] == 0).all()
    assert "recommended_safety_stock" not in result.columns
    assert set(result["interval_calibrated"]) == {False}
    assert set(result["interval_method"]) == {"normal_rmse_heuristic_uncalibrated"}


def test_final_window_does_not_select_forecast_model(tmp_path, monkeypatch):
    n = 4 * forecast.HORIZON_DAYS + 28
    history = pd.DataFrame(
        {
            "order_date": pd.date_range("2025-01-01", periods=n),
            "product_id": "P01",
            "demand": 10,
        }
    )
    monkeypatch.setattr(forecast, "load_factory_demand", lambda *args, **kwargs: history)
    monkeypatch.setenv("FACTORY_PROCESSED_DIR", str(tmp_path / "processed"))
    monkeypatch.setenv("FACTORY_REPORTS_DIR", str(tmp_path / "reports"))

    def fold_result(model_name, train_df, _test_df, _horizon):
        if len(train_df) == n - forecast.HORIZON_DAYS:
            return (0.9, 9.0, 9.0) if model_name == "Naive" else (0.0, 0.0, 0.0)
        return (0.1, 1.0, 1.0) if model_name == "Naive" else (0.2, 2.0, 2.0)

    monkeypatch.setattr(forecast, "evaluate_fold_model", fold_result)
    forecast.run_forecast_benchmark(run_id="HOLDOUT", db_path=tmp_path / "test.db")

    with get_db_connection(tmp_path / "test.db") as conn:
        row = conn.execute(
            "SELECT selected_model, backtest_wape, validation_score_wape, test_score_rmse, "
            "backtest_end, hyperparameters, competing_models "
            "FROM forecast_model_lineage WHERE run_id = 'HOLDOUT'"
        ).fetchone()
    protocol = json.loads(row[5])["evaluation_protocol"]
    competitors = json.loads(row[6])
    assert row[0] == "Naive"  # A rival wins only the unseen final window.
    assert row[1] == row[2] == 0.1
    assert row[3] == 9.0
    assert protocol["selection_folds"] == 3
    assert row[4] < protocol["holdout_start"]
    assert competitors["Naive"]["fold_metrics"]["fold_4"]["role"] == "holdout"
    assert competitors["Seasonal Naive"]["holdout_rmse"] == 0.0
