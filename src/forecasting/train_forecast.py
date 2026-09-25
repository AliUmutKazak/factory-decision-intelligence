import json
import os
import sqlite3
import pandas as pd
import numpy as np
import lightgbm as lgb
import statsmodels
from src.utils.db import get_db_connection
from statsmodels.tsa.holtwinters import ExponentialSmoothing

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
    df = reconcile_continuous_calendar(df)
    return df
    
def reconcile_continuous_calendar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Madde 9: Gerçek veri kalite kontrolleri ve kesintisiz günlük takvim rekonstrüksiyonu.
    - Mükerrer SKU/Tarih kayıtlarını toplulaştırır (Duplicate resolution).
    - Negatif satış/talep anormalliklerini 0 ile sınırlar (Negative demand clipping).
    - Eksik takvim günlerini tespit eder ve talep=0 olarak doldurur (Missing date imputation).
    """
    clean_records = []
    
    # Global tarih sınırları
    min_date = df["order_date"].min()
    max_date = df["order_date"].max()
    full_calendar = pd.date_range(start=min_date, end=max_date, freq="D")
    expected_days = len(full_calendar)

    print(f"\n[DATA QUALITY] Kesintisiz Takvim Denetimi ({min_date.strftime('%Y-%m-%d')} - {max_date.strftime('%Y-%m-%d')} | {expected_days} gün):")

    for pid in sorted(df["product_id"].unique()):
        sub_df = df[df["product_id"] == pid].copy()
        
        # 1. Negatif Değer Kontrolü
        neg_count = (sub_df["demand"] < 0).sum()
        if neg_count > 0:
            print(f"  [{pid}] {neg_count} adet negatif talep kaydı tespit edildi ve 0'a eşitlendi.")
            sub_df["demand"] = sub_df["demand"].clip(lower=0)
            
        # 2. Duplicate Date/SKU Toplulaştırma
        sub_df = sub_df.groupby("order_date", as_index=False)["demand"].sum()

        # 3. Kesintisiz Takvim (Missing Dates Imputation)
        sub_df = sub_df.set_index("order_date").reindex(full_calendar, fill_value=0.0).reset_index()
        sub_df.rename(columns={"index": "order_date"}, inplace=True)
        sub_df["product_id"] = pid
        
        # Denetim istatistikleri
        zero_days = (sub_df["demand"] == 0).sum()
        print(f"  [{pid}] Tam takvim: {len(sub_df)} gün | Sıfır talep günleri: {zero_days} ({(zero_days / expected_days) * 100:.1f}%)")

        clean_records.append(sub_df)

    reconciled_df = pd.concat(clean_records, ignore_index=True)
    return reconciled_df

def evaluate_metrics(actual, pred):
    actual = np.array(actual, dtype=float)
    pred = np.array(pred, dtype=float)

    wape = np.sum(np.abs(actual - pred)) / np.sum(actual) if np.sum(actual) > 0 else 0.0
    rmse = np.sqrt(np.mean((actual - pred) ** 2))
    bias = np.sum(pred - actual)

    return round(wape, 4), round(rmse, 2), round(bias, 1)

def extract_features_for_row(history_df, target_date):
    """
    Veri sızıntısını önlemek için yalnızca geçmiş verileri (history_df)
    kullanarak tek bir hedef gün için öznitelik vektörü üretir.
    """
    features = {}
    
    # 1. Gecikme (Lag) Özellikleri
    demand_series = history_df["demand"].values
    n = len(demand_series)
    for lag in [1, 7, 14, 28]:
        features[f"lag_{lag}"] = demand_series[-lag] if n >= lag else demand_series.mean()

    # 2. Kayan İstatistikler (Rolling)
    for window in [7, 14, 28]:
        sub = demand_series[-window:] if n >= window else demand_series
        features[f"rolling_mean_{window}"] = float(np.mean(sub))
    for window in [7, 28]:
        sub = demand_series[-window:] if n >= window else demand_series
        features[f"rolling_std_{window}"] = float(np.std(sub)) if len(sub) > 1 else 0.0

    # 3. Takvim Özellikleri
    features["day_of_week"] = target_date.dayofweek
    features["week_of_year"] = int(target_date.isocalendar().week)
    features["month"] = target_date.month
    features["day_of_year"] = target_date.dayofyear

    return features

def build_training_matrix(train_raw):
    """
    Eğitim seti için kronolojik öznitelik matrisi inşa eder.
    """
    records = []
    for i in range(28, len(train_raw)):
        history_sub = train_raw.iloc[:i]
        target_row = train_raw.iloc[i]
        feat = extract_features_for_row(history_sub, target_row["order_date"])
        feat["demand"] = target_row["demand"]
        records.append(feat)
    return pd.DataFrame(records)

def evaluate_fold_model(model_name, train_data, test_data, horizon):
    """
    Belirli bir CV katlamasında (fold) verilen modeli eğitir ve test seti üzerinde metrikleri döner.
    """
    y_test = test_data["demand"].values
    if model_name == "Naive":
        pred = np.repeat(train_data["demand"].iloc[-1], horizon)
    elif model_name == "Seasonal Naive":
        last_7 = train_data["demand"].iloc[-7:].values
        pred = np.tile(last_7, int(np.ceil(horizon / 7)))[:horizon]
    elif model_name == "Moving Average":
        pred = np.repeat(train_data["demand"].iloc[-7:].mean(), horizon)
    elif model_name == "Holt-Winters":
        try:
            hw = ExponentialSmoothing(
                train_data["demand"].astype(float),
                trend="add",
                seasonal="add",
                seasonal_periods=7
            ).fit()
            pred = np.maximum(0, hw.forecast(horizon).values)
        except Exception:
            pred = np.repeat(train_data["demand"].iloc[-7:].mean(), horizon)
    elif model_name == "LightGBM":
        train_matrix = build_training_matrix(train_data)
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
        sim_history = train_data.copy()
        pred_lgb = []
        for step in range(horizon):
            target_date = test_data["order_date"].iloc[step]
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

        # Rolling-Origin (Expanding Window) Cross-Validation (K=4 Katlama)
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

        # Katlamalar boyunca ortalama/dağılım performansına göre model seçimi
        model_performance = {}
        for m_name in candidate_models:
            avg_w = float(np.mean(cv_scores[m_name]["wape"]))
            avg_r = float(np.mean(cv_scores[m_name]["rmse"]))
            avg_b = float(np.mean(cv_scores[m_name]["bias"]))
            model_performance[m_name] = (avg_w, avg_r, avg_b)

        best_name = min(model_performance, key=lambda k: model_performance[k][0])

        for m_name, (w, r, b) in model_performance.items():
            benchmark_summary.append({
                "SKU": pid,
                "Model": m_name,
                "Backtest_WAPE": f"{w:.4f}",
                "Backtest_RMSE": f"{r:.2f}",
                "Backtest_Bias": f"{b:.1f}",
                "Kazanan": "✓" if m_name == best_name else ""
            })

        # --- OPERASYONEL GELECEK TAHMİNİ (PRODUCTION REFIT & OUT-OF-SAMPLE FORECAST) ---
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

        for d, q in zip(future_dates, future_preds):
            final_forecast_records.append({
                "forecast_date": d.strftime("%Y-%m-%d"),
                "product_id": pid,
                "forecast_demand": int(round(max(0, q))),
                "model_used": best_name
            })

        # Model Governance / Lineage Standartları (B. Eleştirisi: backtest_wape, backtest_rmse)
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

        best_wape, best_rmse, best_bias = model_performance[best_name]
        backtest_start_dt = str(pdf.iloc[fold_cutoffs[0]]["order_date"])[:10]
        backtest_end_dt = str(pdf.iloc[-1]["order_date"])[:10]

        # Denetim / Reproducibility: Kazanan modelin gerçek hiperparametrelerini ve kütüphane sürümünü hazırla
        cv_spec = {
    "folds": num_folds,
    "horizon": HORIZON_DAYS,
    "cv_type": "rolling_origin_expanding",
    "fold_metrics": competing_scores[best_name]["fold_metrics"]
}
        
        if best_name == "LightGBM":
            model_params = {
                **cv_spec,
                "model_family": "LightGBM",
                "library_version": getattr(lgb, "__version__", "unknown"),
                "objective": "regression",
                "metric": "rmse",
                "learning_rate": 0.05,
                "num_leaves": 31,
                "num_boost_round": LGBM_NUM_BOOST_ROUND,
                "random_seed": 42,
                "boosting_type": "gbdt"
            }
        elif best_name == "Holt-Winters":
            model_params = {
                **cv_spec,
                "model_family": "ExponentialSmoothing",
                "library_version": getattr(statsmodels, "__version__", "unknown"),
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
            # Yeni Governance Standartları
            "backtest_wape": round(float(best_wape), 4),
            "backtest_rmse": round(float(best_rmse), 2),
            "backtest_bias": round(float(best_bias), 2),
            # Mevcut test paketiyle tam geriye dönük uyumluluk
            "validation_score_wape": round(float(best_wape), 4),
            "test_score_rmse": round(float(best_rmse), 2),
            "hyperparameters": json.dumps(model_params),
            "competing_models": json.dumps(competing_scores),
            "selection_reason": f"Selected '{best_name}' via {num_folds}-fold rolling-origin backtest WAPE ({best_wape:.4f})."
        })

    # Benchmark Raporunu Ekrana Bas
    summary_df = pd.DataFrame(benchmark_summary)
    print(summary_df.to_string(index=False))
    print("-" * 85)

    # SQLite, Lineage ve CSV'ye Kaydetme
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    forecast_df = pd.DataFrame(final_forecast_records)
    lineage_df = pd.DataFrame(model_lineage_records)

    from src.utils.db import get_db_connection

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

    print(f"[OK] 28 Günlük Gelecek Tahminleri Yazıldı: {OUTPUT_FORECAST_PATH}")
    print(f"[OK] Model Governance Metadata Kaydedildi: forecast_model_lineage tablosu & reports/forecast_model_metadata.json")

    print(f"[OK] 28 Günlük Tahminler Dosyaya Yazıldı: {OUTPUT_FORECAST_PATH}")
    print(f"[OK] SQLite 'forecast_demand' tablosu güncellendi.")
    print("=" * 85)

if __name__ == "__main__":
    run_forecast_benchmark()