import json
import os
import sqlite3
import pandas as pd
import numpy as np
import lightgbm as lgb
import statsmodels
from pathlib import Path
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.utils.db import get_db_connection
from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    FORECAST_HORIZON_DAYS,
)

OUTPUT_FORECAST_PATH = PROCESSED_DATA_DIR / "forecast_demand.csv"
HORIZON_DAYS = FORECAST_HORIZON_DAYS
LGBM_NUM_BOOST_ROUND = 100

def load_factory_demand():
    conn = get_db_connection(DB_PATH)
    query = """
        SELECT order_date, product_id, order_qty as demand
        FROM orders
        ORDER BY order_date, product_id
    """
    df = pd.read_sql(query, conn)
    conn.close()
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df

def build_training_matrix(df_single_sku):
    df = df_single_sku.copy().sort_values("order_date").reset_index(drop=True)
    df["dayofweek"] = df["order_date"].dt.dayofweek
    df["is_weekend"] = df["dayofweek"].isin([5, 6]).astype(int)
    df["month"] = df["order_date"].dt.month
    df["day"] = df["order_date"].dt.day

    for lag in [1, 2, 3, 7, 14, 21, 28]:
        df[f"lag_{lag}"] = df["demand"].shift(lag)

    for w in [7, 14, 28]:
        df[f"rolling_mean_{w}"] = df["demand"].shift(1).rolling(w).mean()
        df[f"rolling_std_{w}"] = df["demand"].shift(1).rolling(w).std()

    df = df.dropna().reset_index(drop=True)
    drop_cols = ["order_date", "product_id"] if "product_id" in df.columns else ["order_date"]
    return df.drop(columns=[c for c in drop_cols if c in df.columns])

def extract_features_for_row(history_df, target_date):
    feats = {}
    feats["dayofweek"] = target_date.dayofweek
    feats["is_weekend"] = 1 if feats["dayofweek"] in [5, 6] else 0
    feats["month"] = target_date.month
    feats["day"] = target_date.day

    hist = history_df.sort_values("order_date").reset_index(drop=True)
    demands = hist["demand"].values
    n = len(demands)

    for lag in [1, 2, 3, 7, 14, 21, 28]:
        feats[f"lag_{lag}"] = demands[n - lag] if n >= lag else demands[-1]

    for w in [7, 14, 28]:
        window_vals = demands[max(0, n - w):]
        feats[f"rolling_mean_{w}"] = np.mean(window_vals)
        feats[f"rolling_std_{w}"] = np.std(window_vals) if len(window_vals) > 1 else 0.0

    return feats

def evaluate_metrics(y_true, y_pred):
    denom = np.sum(y_true)
    wape = float(np.sum(np.abs(y_true - y_pred)) / denom) if denom > 0 else 0.0
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    bias = float(np.sum(y_pred - y_true))
    return wape, rmse, bias

def evaluate_fold_model(model_name, train_df, test_df, horizon):
    y_test = test_df["demand"].values
    if model_name == "Naive":
        pred = np.repeat(train_df["demand"].iloc[-1], horizon)
    elif model_name == "Seasonal Naive":
        last_7 = train_df["demand"].iloc[-7:].values
        pred = np.tile(last_7, int(np.ceil(horizon / 7)))[:horizon]
    elif model_name == "Moving Average":
        pred = np.repeat(train_df["demand"].iloc[-7:].mean(), horizon)
    elif model_name == "Holt-Winters":
        try:
            hw = ExponentialSmoothing(
                train_df["demand"].astype(float),
                trend="add",
                seasonal="add",
                seasonal_periods=7
            ).fit()
            pred = np.maximum(0, hw.forecast(horizon).values)
        except Exception:
            pred = np.repeat(train_df["demand"].mean(), horizon)
    elif model_name == "LightGBM":
        train_matrix = build_training_matrix(train_df)
        if len(train_matrix) < 20:
            pred = np.repeat(train_df["demand"].iloc[-7:].mean(), horizon)
            return evaluate_metrics(y_test, pred)
        feature_cols = [c for c in train_matrix.columns if c != "demand"]
        lgb_train = lgb.Dataset(train_matrix[feature_cols], label=train_matrix["demand"])
        params = {
            "objective": "regression",
            "metric": "rmse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
            "seed": 42
        }
        gbm = lgb.train(params, lgb_train, num_boost_round=LGBM_NUM_BOOST_ROUND)
        sim_history = train_df.copy()
        pred_lgb = []
        for i in range(horizon):
            target_date = test_df["order_date"].iloc[i]
            feat_step = extract_features_for_row(sim_history, target_date)
            feat_df = pd.DataFrame([feat_step])[feature_cols]
            p_val = max(0.0, float(gbm.predict(feat_df)[0]))
            pred_lgb.append(p_val)
            sim_history = pd.concat([
                sim_history,
                pd.DataFrame([{"order_date": target_date, "demand": p_val}])
            ], ignore_index=True)
        pred = np.array(pred_lgb)
    else:
        pred = np.zeros(horizon)
    return evaluate_metrics(y_test, pred)

def run_forecast_benchmark(run_id=None):
    df_all = load_factory_demand()
    products = sorted(df_all["product_id"].unique())

    benchmark_summary = []
    final_forecast_records = []
    model_lineage_records = []

    print("=" * 85)
    print("      AŞAMA 3: TALEP TAHMİNLEME & MODEL KIYASLAMA (BENCHMARK)      ")
    print("=" * 85)

    for pid in products:
        pdf = df_all[df_all["product_id"] == pid].sort_values("order_date").reset_index(drop=True)

        num_folds = 4
        total_len = len(pdf)
        candidate_models = ["Naive", "Seasonal Naive", "Moving Average", "Holt-Winters", "LightGBM"]
        cv_scores = {m: {"wape": [], "rmse": [], "bias": []} for m in candidate_models}

        fold_cutoffs = [total_len - (num_folds - f) * HORIZON_DAYS for f in range(num_folds)]
        for f_idx, cutoff in enumerate(fold_cutoffs):
            train_sub = pdf.iloc[:cutoff].copy().reset_index(drop=True)
            test_sub = pdf.iloc[cutoff:cutoff + HORIZON_DAYS].copy().reset_index(drop=True)
            for m_name in candidate_models:
                w, r, b = evaluate_fold_model(m_name, train_sub, test_sub, HORIZON_DAYS)
                cv_scores[m_name]["wape"].append(w)
                cv_scores[m_name]["rmse"].append(r)
                cv_scores[m_name]["bias"].append(b)

        model_performance = {}
        for m_name in candidate_models:
            avg_w = float(np.mean(cv_scores[m_name]["wape"]))
            avg_r = float(np.mean(cv_scores[m_name]["rmse"]))
            avg_b = float(np.mean(cv_scores[m_name]["bias"]))
            model_performance[m_name] = (avg_w, avg_r, avg_b)

        best_name = min(model_performance, key=lambda k: model_performance[k][0])
        best_wape, best_rmse, best_bias = model_performance[best_name]

        for m_name, (w, r, b) in model_performance.items():
            benchmark_summary.append({
                "SKU": pid,
                "Model": m_name,
                "Backtest_WAPE": f"{w:.4f}",
                "Backtest_RMSE": f"{r:.2f}",
                "Backtest_Bias": f"{b:.1f}",
                "Kazanan": "✓" if m_name == best_name else ""
            })

        last_date = pd.to_datetime(pdf["order_date"].max())
        future_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=HORIZON_DAYS, freq="D")

        if best_name == "Naive":
            future_preds = np.repeat(pdf["demand"].iloc[-1], HORIZON_DAYS)
        elif best_name == "Seasonal Naive":
            last_7 = pdf["demand"].iloc[-7:].values
            future_preds = np.tile(last_7, int(np.ceil(HORIZON_DAYS / 7)))[:HORIZON_DAYS]
        elif best_name == "Moving Average":
            future_preds = np.repeat(pdf["demand"].iloc[-7:].mean(), HORIZON_DAYS)
        elif best_name == "Holt-Winters":
            hw_prod = ExponentialSmoothing(
                pdf["demand"].astype(float),
                trend="add",
                seasonal="add",
                seasonal_periods=7
            ).fit()
            future_preds = hw_prod.forecast(HORIZON_DAYS).values
            future_preds = np.maximum(0, future_preds)
        elif best_name == "LightGBM":
            prod_train_matrix = build_training_matrix(pdf)
            feature_cols = [c for c in prod_train_matrix.columns if c != "demand"]
            lgb_prod_train = lgb.Dataset(prod_train_matrix[feature_cols], label=prod_train_matrix["demand"])
            params = {
                "objective": "regression",
                "metric": "rmse",
                "learning_rate": 0.05,
                "num_leaves": 31,
                "verbose": -1,
                "seed": 42
            }
            gbm_prod = lgb.train(params, lgb_prod_train, num_boost_round=LGBM_NUM_BOOST_ROUND)
            prod_sim = pdf.copy()
            future_preds_list = []
            for f_date in future_dates:
                feat_step = extract_features_for_row(prod_sim, f_date)
                feat_df = pd.DataFrame([feat_step])[feature_cols]
                p_val = max(0.0, float(gbm_prod.predict(feat_df)[0]))
                future_preds_list.append(p_val)
                prod_sim = pd.concat([
                    prod_sim,
                    pd.DataFrame([{"order_date": f_date, "demand": p_val}])
                ], ignore_index=True)
            future_preds = np.array(future_preds_list)

        # 12. Madde: CV RMSE uzerinden belirsizlik ve dinamik Safety Stock
        sigma_uncertainty = float(best_rmse) if best_rmse > 0 else float(np.std(pdf["demand"]))
        z_90 = 1.282
        safety_stock_val = int(round(z_90 * sigma_uncertainty))

        for d, q in zip(future_dates, future_preds):
            p50_val = int(round(max(0, q)))
            p90_val = int(round(max(0, q + z_90 * sigma_uncertainty)))
            p10_val = int(round(max(0, q - z_90 * sigma_uncertainty)))

            final_forecast_records.append({
                "forecast_date": d.strftime("%Y-%m-%d"),
                "product_id": pid,
                "forecast_demand": p50_val,
                "demand_p10": p10_val,
                "demand_p50": p50_val,
                "demand_p90": p90_val,
                "forecast_uncertainty_sigma": round(sigma_uncertainty, 2),
                "recommended_safety_stock": safety_stock_val,
                "model_used": best_name
            })

        competing_scores = {}
        for m, vals in model_performance.items():
            competing_scores[m] = {
                "backtest_wape": round(vals[0], 4),
                "backtest_rmse": round(vals[1], 2),
                "backtest_bias": round(vals[2], 2),
                "fold_metrics": {
                    f"fold_{f_i + 1}": {
                        "wape": round(cv_scores[m]["wape"][f_i], 4),
                        "rmse": round(cv_scores[m]["rmse"][f_i], 2),
                        "bias": round(cv_scores[m]["bias"][f_i], 2)
                    }
                    for f_i in range(num_folds)
                }
            }

        first_cutoff_dt = str(pdf.iloc[fold_cutoffs[0]]["order_date"])[:10]
        backtest_start_dt = first_cutoff_dt
        backtest_end_dt = str(pdf["order_date"].max())[:10]

        cv_spec = {
            "cv_strategy": "rolling_origin_expanding_window",
            "folds": num_folds,
            "horizon_days": HORIZON_DAYS,
            "backtest_start": backtest_start_dt,
            "backtest_end": backtest_end_dt
        }

        if best_name == "LightGBM":
            model_params = {
                "objective": "regression",
                "learning_rate": 0.05,
                "num_leaves": 31,
                "num_boost_round": LGBM_NUM_BOOST_ROUND,
                "lags": [1, 2, 3, 7, 14, 21, 28],
                "rolling_windows": [7, 14, 28],
                "cv_folds": num_folds
            }
        elif best_name == "Holt-Winters":
            model_params = {
                "trend": "add",
                "seasonal": "add",
                "seasonal_periods": 7,
                "initialization_method": "estimated"
            }
        else:
            model_params = {
                **cv_spec,
                "model_family": best_name
            }

        model_lineage_records.append({
            "product_id": pid,
            "selected_model": best_name,
            "model_version": "v3.0-rolling-origin-cv",
            "feature_version": "v1.2-lag-calendar",
            "forecast_origin": str(pdf["order_date"].max())[:10],
            "training_start": str(pdf["order_date"].min())[:10],
            "training_end": str(pdf["order_date"].max())[:10],
            "backtest_start": backtest_start_dt,
            "backtest_end": backtest_end_dt,
            "backtest_wape": round(float(best_wape), 4),
            "backtest_rmse": round(float(best_rmse), 2),
            "backtest_bias": round(float(best_bias), 2),
            "validation_score_wape": round(float(best_wape), 4),
            "test_score_rmse": round(float(best_rmse), 2),
            "hyperparameters": json.dumps(model_params),
            "competing_models": json.dumps(competing_scores),
            "selection_reason": f"Selected '{best_name}' via {num_folds}-fold rolling-origin backtest WAPE ({best_wape:.4f})."
        })

    summary_df = pd.DataFrame(benchmark_summary)
    print(summary_df.to_string(index=False))
    print("-" * 85)

    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    forecast_df = pd.DataFrame(final_forecast_records)
    lineage_df = pd.DataFrame(model_lineage_records)

    active_run_id = run_id
    if not active_run_id:
        try:
            with get_db_connection(DB_PATH) as _conn:
                row = _conn.execute("SELECT run_id FROM pipeline_runs ORDER BY id DESC LIMIT 1").fetchone()
                active_run_id = row[0] if row else "STANDALONE_RUN"
        except Exception:
            active_run_id = "STANDALONE_RUN"

    forecast_df["run_id"] = active_run_id
    lineage_df["run_id"] = active_run_id

    forecast_df.to_csv(OUTPUT_FORECAST_PATH, index=False)
    lineage_df.to_csv(os.path.join(PROCESSED_DATA_DIR, "forecast_model_lineage.csv"), index=False)

    with open("reports/forecast_model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(model_lineage_records, f, indent=2, ensure_ascii=False)

    with get_db_connection(DB_PATH) as conn:
        forecast_df.to_sql("forecast_demand", conn, index=False, if_exists="replace")
        lineage_df.to_sql("forecast_model_lineage", conn, index=False, if_exists="replace")

    print(f"[OK] 28 Gunluk Gelecek Tahminleri Yazildi: {OUTPUT_FORECAST_PATH}")
    print(f"[OK] Model Governance Metadata Kaydedildi: forecast_model_lineage tablosu & reports/forecast_model_metadata.json")

    return forecast_df

if __name__ == "__main__":
    run_forecast_benchmark()
