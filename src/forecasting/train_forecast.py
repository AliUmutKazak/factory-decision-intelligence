import json
import os
import sqlite3
import pandas as pd
import numpy as np
import lightgbm as lgb
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    FORECAST_HORIZON_DAYS,
)

OUTPUT_FORECAST_PATH = PROCESSED_DATA_DIR / "forecast_demand.csv"
HORIZON_DAYS = FORECAST_HORIZON_DAYS

def load_factory_demand():
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT order_date, product_id, order_qty as demand
        FROM orders
        ORDER BY order_date, product_id
    """
    df = pd.read_sql(query, conn)
    conn.close()
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df

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

def run_forecast_benchmark():
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

        # Kronolojik Train / Test Ayrımı
        train_raw = pdf.iloc[:-HORIZON_DAYS].copy().reset_index(drop=True)
        test_raw = pdf.iloc[-HORIZON_DAYS:].copy().reset_index(drop=True)
        y_test = test_raw["demand"].values

        # 1. Naive Model (Son günün talebi)
        pred_naive = np.repeat(train_raw["demand"].iloc[-1], HORIZON_DAYS)
        w_naive, r_naive, b_naive = evaluate_metrics(y_test, pred_naive)

        # 2. Seasonal Naive Model (Son 7 günün haftalık döngüsü)
        last_7_days = train_raw["demand"].iloc[-7:].values
        pred_snaive = np.tile(last_7_days, int(np.ceil(HORIZON_DAYS / 7)))[:HORIZON_DAYS]
        w_snaive, r_snaive, b_snaive = evaluate_metrics(y_test, pred_snaive)

        # 3. Moving Average (Son 7 gün ortalaması)
        pred_ma = np.repeat(train_raw["demand"].iloc[-7:].mean(), HORIZON_DAYS)
        w_ma, r_ma, b_ma = evaluate_metrics(y_test, pred_ma)

        # 4. Holt-Winters (Exponential Smoothing)
        hw_model = ExponentialSmoothing(
            train_raw["demand"].astype(float),
            trend="add",
            seasonal="add",
            seasonal_periods=7
        ).fit()
        pred_hw = hw_model.forecast(HORIZON_DAYS).values
        pred_hw = np.maximum(0, pred_hw)
        w_hw, r_hw, b_hw = evaluate_metrics(y_test, pred_hw)

        # 5. LightGBM (Sızıntısız, Özyinelemeli / Recursive Çok Adımlı Tahmin)
        train_matrix = build_training_matrix(train_raw)
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
        gbm = lgb.train(params, lgb_train, num_boost_round=150)

        # 28 Günlük Özyinelemeli (Autoregressive) Simülasyon Döngüsü
        sim_history = train_raw.copy()
        pred_lgb = []

        for step in range(HORIZON_DAYS):
            target_date = test_raw["order_date"].iloc[step]
            feat_step = extract_features_for_row(sim_history, target_date)
            feat_df = pd.DataFrame([feat_step])[feature_cols]
            pred_val = max(0.0, float(gbm.predict(feat_df)[0]))
            pred_lgb.append(pred_val)

            # Bir sonraki günün lag hesapları için kendi tahminini geçmişe ekler
            sim_history = pd.concat([
                sim_history,
                pd.DataFrame([{"order_date": target_date, "product_id": pid, "demand": pred_val}])
            ], ignore_index=True)

        pred_lgb = np.array(pred_lgb)
        w_lgb, r_lgb, b_lgb = evaluate_metrics(y_test, pred_lgb)

        # Model Kıyaslama Havuzu
        models = {
            "Naive": (w_naive, r_naive, b_naive, pred_naive),
            "Seasonal Naive": (w_snaive, r_snaive, b_snaive, pred_snaive),
            "Moving Average": (w_ma, r_ma, b_ma, pred_ma),
            "Holt-Winters": (w_hw, r_hw, b_hw, pred_hw),
            "LightGBM": (w_lgb, r_lgb, b_lgb, pred_lgb)
        }

        # En düşük WAPE'e sahip adil kazananı seç
        best_name = min(models, key=lambda k: models[k][0])

        for m_name, (w, r, b, _) in models.items():
            benchmark_summary.append({
                "SKU": pid,
                "Model": m_name,
                "WAPE": f"{w:.4f}",
                "RMSE": f"{r:.2f}",
                "Bias": f"{b:.1f}",
                "Kazanan": "✓" if m_name == best_name else ""
            })

        # --- OPERASYONEL GELECEK TAHMİNİ (PRODUCTION REFIT & OUT-OF-SAMPLE FORECAST) ---
        # Kazanan modeli tüm geçmiş veriyle (pdf) refit edip gerçek geleceğe tahmin üretiyoruz
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
            lgb_prod_train = lgb.Dataset(prod_train_matrix[feature_cols], label=prod_train_matrix["demand"])
            gbm_prod = lgb.train(params, lgb_prod_train, num_boost_round=150)

            prod_sim_history = pdf.copy()
            future_preds_list = []
            for f_date in future_dates:
                feat_step = extract_features_for_row(prod_sim_history, f_date)
                feat_df = pd.DataFrame([feat_step])[feature_cols]
                p_val = max(0.0, float(gbm_prod.predict(feat_df)[0]))
                future_preds_list.append(p_val)
                prod_sim_history = pd.concat([
                    prod_sim_history,
                    pd.DataFrame([{"order_date": f_date, "product_id": pid, "demand": p_val}])
                ], ignore_index=True)
            future_preds = np.array(future_preds_list)

        # Gerçek operasyonel gelecek kayıtlarını yaz
        for d, q in zip(future_dates, future_preds):
            final_forecast_records.append({
                "forecast_date": d.strftime("%Y-%m-%d"),
                "product_id": pid,
                "forecast_demand": int(round(max(0, q))),
                "model_used": best_name
            })

        # Model Governance / Lineage Kaydı (Madde 23)
        competing_scores = {
            m_name: {"wape": round(float(vals[0]), 4), "rmse": round(float(vals[1]), 2), "bias": round(float(vals[2]), 2)}
            for m_name, vals in models.items()
        }
        
        model_params = {}
        if best_name == "LightGBM":
            model_params = params
        elif best_name == "Holt-Winters":
            model_params = {"trend": "add", "seasonal": "add", "seasonal_periods": 7}
        elif best_name == "Moving Average":
            model_params = {"window": 7}
        elif best_name in ["Naive", "Seasonal Naive"]:
            model_params = {"lag": 7 if best_name == "Seasonal Naive" else 1}

        best_wape_val = models[best_name][0]
        best_rmse_val = models[best_name][1]

        model_lineage_records.append({
            "product_id": pid,
            "selected_model": best_name,
            "model_version": "v2.0-recursive",
            "feature_version": "v1.2-lag-calendar",
            "forecast_origin": str(pdf["order_date"].max())[:10],
            "training_start": str(pdf["order_date"].min())[:10],
            "training_end": str(pdf["order_date"].max())[:10],
            "backtest_start": str(test_raw["order_date"].min())[:10] if 'test_raw' in locals() else "2017-12-04",
            "backtest_end": str(test_raw["order_date"].max())[:10] if 'test_raw' in locals() else "2017-12-31",
            "validation_score_wape": round(float(best_wape_val), 4),
            "test_score_rmse": round(float(best_rmse_val), 2),
            "hyperparameters": json.dumps(model_params),
            "competing_models": json.dumps(competing_scores),
            "selection_reason": f"Selected '{best_name}' due to minimum out-of-sample holdout WAPE ({best_wape_val:.4f})."
        })

    # Benchmark Raporunu Ekrana Bas
    summary_df = pd.DataFrame(benchmark_summary)

    # Benchmark Raporunu Ekrana Bas
    summary_df = pd.DataFrame(benchmark_summary)
    print(summary_df.to_string(index=False))
    print("-" * 85)

    # SQLite, Lineage ve CSV'ye Kaydetme
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    
    forecast_df = pd.DataFrame(final_forecast_records)
    forecast_df.to_csv(OUTPUT_FORECAST_PATH, index=False)

    lineage_df = pd.DataFrame(model_lineage_records)
    lineage_df.to_csv(os.path.join(PROCESSED_DATA_DIR, "forecast_model_lineage.csv"), index=False)
    
    with open("reports/forecast_model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(model_lineage_records, f, indent=2, ensure_ascii=False)

    conn = sqlite3.connect(DB_PATH)
    forecast_df.to_sql("forecast_demand", conn, index=False, if_exists="replace")
    lineage_df.to_sql("forecast_model_lineage", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] 28 Günlük Gelecek Tahminleri Yazıldı: {OUTPUT_FORECAST_PATH}")
    print(f"[OK] Model Governance Metadata Kaydedildi: forecast_model_lineage tablosu & reports/forecast_model_metadata.json")

    print(f"[OK] 28 Günlük Tahminler Dosyaya Yazıldı: {OUTPUT_FORECAST_PATH}")
    print(f"[OK] SQLite 'forecast_demand' tablosu güncellendi.")
    print("=" * 85)

if __name__ == "__main__":
    run_forecast_benchmark()