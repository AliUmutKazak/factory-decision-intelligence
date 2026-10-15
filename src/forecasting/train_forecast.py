import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.config import (
    FORECAST_FEATURE_VERSION,
    FORECAST_HORIZON_DAYS,
    FORECAST_MODEL_VERSION,
    HOLT_WINTERS_DEFAULT_PARAMS,
    get_runtime_paths,
)
from src.utils.db import get_active_run_id, get_db_connection, persist_run_scoped_dataframe

HORIZON_DAYS = FORECAST_HORIZON_DAYS
LGBM_NUM_BOOST_ROUND = 100


class ForecastCandidateUnavailable(ValueError):
    """A candidate could not be fitted at one chronological origin."""


def load_factory_demand(db_path=None, run_id=None):
    active_db_path = db_path or get_runtime_paths()["db_path"]
    conn = get_db_connection(active_db_path)
    if run_id is not None:
        query = """
            SELECT order_date, product_id, order_qty AS demand
            FROM orders
            WHERE run_id = ?
            ORDER BY order_date, product_id
        """
        df = pd.read_sql(query, conn, params=(str(run_id),))
    else:
        query = """
            SELECT order_date, product_id, order_qty AS demand
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
        window_vals = demands[max(0, n - w) :]
        feats[f"rolling_mean_{w}"] = np.mean(window_vals)
        feats[f"rolling_std_{w}"] = np.std(window_vals) if len(window_vals) > 1 else 0.0

    return feats


def evaluate_metrics(y_true, y_pred):
    denom = float(np.sum(y_true))
    # WAPE has no denominator when the entire evaluation horizon has zero demand.
    # Returning zero here would falsely reward a model that predicts positive demand.
    wape = float(np.sum(np.abs(y_true - y_pred)) / denom) if denom > 0 else None
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
                train_df["demand"].astype(float), trend="add", seasonal="add", seasonal_periods=7
            ).fit()
            pred = np.maximum(0, hw.forecast(horizon).values)
        except Exception as exc:
            raise ForecastCandidateUnavailable("Holt-Winters fit failed") from exc
    elif model_name == "LightGBM":
        train_matrix = build_training_matrix(train_df)
        if len(train_matrix) < 20:
            raise ForecastCandidateUnavailable("LightGBM needs at least 20 lag-complete training rows")
        feature_cols = [c for c in train_matrix.columns if c != "demand"]
        lgb_train = lgb.Dataset(train_matrix[feature_cols], label=train_matrix["demand"])
        params = {
            "objective": "regression",
            "metric": "rmse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
            "seed": 42,
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
            sim_history = pd.concat(
                [sim_history, pd.DataFrame([{"order_date": target_date, "demand": p_val}])], ignore_index=True
            )
        pred = np.array(pred_lgb)
    else:
        pred = np.zeros(horizon)
    return evaluate_metrics(y_test, pred)


def run_forecast_benchmark(run_id=None, db_path=None):
    active_db_path = db_path or get_runtime_paths()["db_path"]
    df_all = load_factory_demand(active_db_path, run_id=run_id)
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
        selection_folds = num_folds - 1
        total_len = len(pdf)
        min_history = num_folds * HORIZON_DAYS + 28
        if total_len < min_history:
            raise ValueError(
                f"[FORECAST] {pid}: {num_folds} rolling-origin folds and 28-day lag "
                f"need at least {min_history} observations; received {total_len}."
            )
        candidate_models = ["Naive", "Seasonal Naive", "Moving Average", "Holt-Winters", "LightGBM"]
        model_order = {name: index for index, name in enumerate(candidate_models)}
        cv_scores = {m: {"wape": [], "rmse": [], "bias": [], "failure": None} for m in candidate_models}

        fold_cutoffs = [total_len - (num_folds - f) * HORIZON_DAYS for f in range(num_folds)]
        for f_idx, cutoff in enumerate(fold_cutoffs):
            train_sub = pdf.iloc[:cutoff].copy().reset_index(drop=True)
            test_sub = pdf.iloc[cutoff : cutoff + HORIZON_DAYS].copy().reset_index(drop=True)
            for m_name in candidate_models:
                try:
                    w, r, b = evaluate_fold_model(m_name, train_sub, test_sub, HORIZON_DAYS)
                except ForecastCandidateUnavailable as exc:
                    if cv_scores[m_name]["failure"] is None:
                        cv_scores[m_name]["failure"] = f"fold_{f_idx + 1}: {exc}"
                    w, r, b = None, None, None
                cv_scores[m_name]["wape"].append(w)
                cv_scores[m_name]["rmse"].append(r)
                cv_scores[m_name]["bias"].append(b)

        # The final chronological window is held out from model choice. Reporting
        # the same folds used for selection as a "test" would bias that estimate.
        model_performance = {}
        for m_name in candidate_models:
            if any(r is None for r in cv_scores[m_name]["rmse"][:selection_folds]):
                continue
            fold_wapes = cv_scores[m_name]["wape"][:selection_folds]
            avg_w = float(np.mean(fold_wapes)) if all(w is not None for w in fold_wapes) else None
            avg_r = float(np.mean(cv_scores[m_name]["rmse"][:selection_folds]))
            avg_b = float(np.mean(cv_scores[m_name]["bias"][:selection_folds]))
            model_performance[m_name] = (avg_w, avg_r, avg_b)

        selection_metric = "RMSE" if any(w is None for w in cv_scores["Naive"]["wape"][:selection_folds]) else "WAPE"
        best_name = min(
            model_performance,
            key=lambda k: (
                (model_performance[k][1], model_order[k])
                if selection_metric == "RMSE"
                else (model_performance[k][0], model_performance[k][1], model_order[k])
            ),
        )
        best_wape, best_rmse, best_bias = model_performance[best_name]
        holdout_wape = cv_scores[best_name]["wape"][-1]
        holdout_rmse = cv_scores[best_name]["rmse"][-1]
        holdout_bias = cv_scores[best_name]["bias"][-1]
        if holdout_rmse is None:
            raise ValueError(f"[FORECAST] {pid}: selected model {best_name} has no valid holdout evaluation")

        for m_name in candidate_models:
            w, r, b = model_performance.get(m_name, (None, None, None))
            candidate_holdout = cv_scores[m_name]["rmse"][-1]
            benchmark_summary.append(
                {
                    "SKU": pid,
                    "Model": m_name,
                    "Selection_WAPE": f"{w:.4f}" if w is not None else "n/a",
                    "Selection_RMSE": f"{r:.2f}" if r is not None else "n/a",
                    "Selection_Bias": f"{b:.1f}" if b is not None else "n/a",
                    "Holdout_RMSE": f"{candidate_holdout:.2f}" if candidate_holdout is not None else "n/a",
                    "Status": (
                        "EXCLUDED_SELECTION"
                        if r is None
                        else "HOLDOUT_UNAVAILABLE"
                        if candidate_holdout is None
                        else "EVALUATED"
                    ),
                    "Kazanan": "✓" if m_name == best_name else "",
                }
            )

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
                pdf["demand"].astype(float), trend="add", seasonal="add", seasonal_periods=7
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
                "seed": 42,
            }
            gbm_prod = lgb.train(params, lgb_prod_train, num_boost_round=LGBM_NUM_BOOST_ROUND)
            prod_sim = pdf.copy()
            future_preds_list = []
            for f_date in future_dates:
                feat_step = extract_features_for_row(prod_sim, f_date)
                feat_df = pd.DataFrame([feat_step])[feature_cols]
                p_val = max(0.0, float(gbm_prod.predict(feat_df)[0]))
                future_preds_list.append(p_val)
                prod_sim = pd.concat(
                    [prod_sim, pd.DataFrame([{"order_date": f_date, "demand": p_val}])], ignore_index=True
                )
            future_preds = np.array(future_preds_list)

        # 12. Madde: CV RMSE uzerinden belirsizlik ve dinamik Safety Stock
        sigma_uncertainty = float(best_rmse) if best_rmse > 0 else float(np.std(pdf["demand"]))
        z_90 = 1.282
        safety_stock_val = int(round(z_90 * sigma_uncertainty))

        for d, q in zip(future_dates, future_preds):
            p50_val = int(round(max(0, q)))
            p90_val = int(round(max(0, q + z_90 * sigma_uncertainty)))
            p10_val = int(round(max(0, q - z_90 * sigma_uncertainty)))

            final_forecast_records.append(
                {
                    "forecast_date": d.strftime("%Y-%m-%d"),
                    "product_id": pid,
                    "forecast_demand": p50_val,
                    "demand_p10": p10_val,
                    "demand_p50": p50_val,
                    "demand_p90": p90_val,
                    "forecast_uncertainty_sigma": round(sigma_uncertainty, 2),
                    "recommended_safety_stock": safety_stock_val,
                    "model_used": best_name,
                }
            )

        competing_scores = {}
        for m in candidate_models:
            vals = model_performance.get(m)
            candidate_holdout = cv_scores[m]["rmse"][-1]
            competing_scores[m] = {
                "status": (
                    "EXCLUDED_SELECTION"
                    if vals is None
                    else "HOLDOUT_UNAVAILABLE"
                    if candidate_holdout is None
                    else "EVALUATED"
                ),
                "failure_reason": cv_scores[m]["failure"],
                "backtest_wape": round(vals[0], 4) if vals is not None and vals[0] is not None else None,
                "backtest_rmse": round(vals[1], 2) if vals is not None else None,
                "backtest_bias": round(vals[2], 2) if vals is not None else None,
                "holdout_wape": (round(cv_scores[m]["wape"][-1], 4) if cv_scores[m]["wape"][-1] is not None else None),
                "holdout_rmse": round(candidate_holdout, 2) if candidate_holdout is not None else None,
                "holdout_bias": round(cv_scores[m]["bias"][-1], 2) if cv_scores[m]["bias"][-1] is not None else None,
                "fold_metrics": {
                    f"fold_{f_i + 1}": {
                        "role": "selection" if f_i < selection_folds else "holdout",
                        "wape": round(cv_scores[m]["wape"][f_i], 4) if cv_scores[m]["wape"][f_i] is not None else None,
                        "rmse": round(cv_scores[m]["rmse"][f_i], 2) if cv_scores[m]["rmse"][f_i] is not None else None,
                        "bias": round(cv_scores[m]["bias"][f_i], 2) if cv_scores[m]["bias"][f_i] is not None else None,
                    }
                    for f_i in range(num_folds)
                },
            }

        first_cutoff_dt = str(pdf.iloc[fold_cutoffs[0]]["order_date"])[:10]
        backtest_start_dt = first_cutoff_dt
        backtest_end_dt = str(pdf.iloc[fold_cutoffs[-1] - 1]["order_date"])[:10]
        holdout_start_dt = str(pdf.iloc[fold_cutoffs[-1]]["order_date"])[:10]
        holdout_end_dt = str(pdf["order_date"].max())[:10]

        cv_spec = {
            "cv_strategy": "rolling_origin_expanding_window",
            "selection_folds": selection_folds,
            "holdout_folds": 1,
            "horizon_days": HORIZON_DAYS,
            "selection_metric": selection_metric,
            "backtest_start": backtest_start_dt,
            "backtest_end": backtest_end_dt,
            "holdout_start": holdout_start_dt,
            "holdout_end": holdout_end_dt,
        }

        if best_name == "LightGBM":
            model_params = {
                "objective": "regression",
                "learning_rate": 0.05,
                "num_leaves": 31,
                "num_boost_round": LGBM_NUM_BOOST_ROUND,
                "lags": [1, 2, 3, 7, 14, 21, 28],
                "rolling_windows": [7, 14, 28],
                "cv_folds": selection_folds,
            }
        elif best_name == "Holt-Winters":
            model_params = dict(HOLT_WINTERS_DEFAULT_PARAMS)
        else:
            model_params = {**cv_spec, "model_family": best_name}
        model_params["evaluation_protocol"] = cv_spec
        model_params["holdout_wape"] = round(holdout_wape, 4) if holdout_wape is not None else None
        model_params["holdout_bias"] = round(holdout_bias, 2)
        model_params["uncertainty_method"] = "normal_rmse_heuristic_uncalibrated"

        model_lineage_records.append(
            {
                "product_id": pid,
                "selected_model": best_name,
                "model_version": FORECAST_MODEL_VERSION,
                "feature_version": FORECAST_FEATURE_VERSION,
                "forecast_origin": str(pdf["order_date"].max())[:10],
                "training_start": str(pdf["order_date"].min())[:10],
                "training_end": str(pdf["order_date"].max())[:10],
                "backtest_start": backtest_start_dt,
                "backtest_end": backtest_end_dt,
                "backtest_wape": round(float(best_wape), 4) if best_wape is not None else None,
                "backtest_rmse": round(float(best_rmse), 2),
                "backtest_bias": round(float(best_bias), 2),
                "validation_score_wape": round(float(best_wape), 4) if best_wape is not None else None,
                "test_score_rmse": round(float(holdout_rmse), 2),
                "hyperparameters": json.dumps(model_params),
                "competing_models": json.dumps(competing_scores),
                "selection_reason": (
                    f"Selected '{best_name}' via {selection_folds}-fold rolling-origin selection "
                    f"{selection_metric} ({best_rmse:.2f} RMSE; WAPE undefined on zero-demand fold)."
                    if selection_metric == "RMSE"
                    else f"Selected '{best_name}' via {selection_folds}-fold rolling-origin selection WAPE ({best_wape:.4f})."
                ),
            }
        )

    summary_df = pd.DataFrame(benchmark_summary)
    print(summary_df.to_string(index=False))
    print("-" * 85)

    _rt_paths = get_runtime_paths()
    processed_dir = _rt_paths["processed_dir"]
    reports_dir = _rt_paths["reports_dir"]
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    forecast_df = pd.DataFrame(final_forecast_records)
    lineage_df = pd.DataFrame(model_lineage_records)

    active_run_id = run_id
    if not active_run_id:
        try:
            with get_db_connection(active_db_path) as _conn:
                active_run_id = get_active_run_id(_conn)
        except Exception as exc:
            raise RuntimeError("[FORECAST] run_id belirtilmeli veya ACTIVE run bulunmalıdır.") from exc

    forecast_df["run_id"] = active_run_id
    lineage_df["run_id"] = active_run_id

    forecast_csv_path = processed_dir / "forecast_demand.csv"
    lineage_csv_path = processed_dir / "forecast_model_lineage.csv"

    forecast_df.to_csv(forecast_csv_path, index=False)
    lineage_df.to_csv(lineage_csv_path, index=False)

    forecast_meta = {}
    if not lineage_df.empty:
        for _, row in lineage_df.iterrows():
            pid = str(row["product_id"])
            forecast_meta[pid] = {
                "product_id": pid,
                "selected_model": row.get("selected_model"),
                "model_version": row.get("model_version", FORECAST_MODEL_VERSION),
                "feature_version": row.get("feature_version", FORECAST_FEATURE_VERSION),
                "validation_score_wape": row.get("validation_score_wape"),
                "test_score_rmse": row.get("test_score_rmse"),
                "evaluation_protocol": json.loads(row["hyperparameters"])["evaluation_protocol"],
                "holdout_wape": json.loads(row["hyperparameters"])["holdout_wape"],
                "uncertainty_method": "normal_rmse_heuristic_uncalibrated",
            }
    else:
        for pid in ["P01", "P02", "P03", "P04", "P05"]:
            forecast_meta[pid] = {
                "product_id": pid,
                "selected_model": "LightGBM",
                "model_version": FORECAST_MODEL_VERSION,
                "feature_version": FORECAST_FEATURE_VERSION,
            }

    output_forecast_path = processed_dir / "forecast_demand.csv"

    with open(reports_dir / "forecast_model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(forecast_meta, f, indent=4)

    with get_db_connection(active_db_path) as conn:
        persist_run_scoped_dataframe(conn, "forecast_demand", forecast_df, str(active_run_id))
        persist_run_scoped_dataframe(conn, "forecast_model_lineage", lineage_df, str(active_run_id))
        conn.commit()

    print(f"[OK] 28 Gunluk Gelecek Tahminleri Yazildi: {output_forecast_path}")
    print(
        "[OK] Model Governance Metadata Kaydedildi: forecast_model_lineage tablosu & reports/forecast_model_metadata.json"
    )

    return forecast_df


if __name__ == "__main__":
    run_forecast_benchmark()
