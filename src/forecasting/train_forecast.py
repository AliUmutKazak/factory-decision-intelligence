import sqlite3
import os
import pandas as pd
import numpy as np
import lightgbm as lgb
from statsmodels.tsa.holtwinters import ExponentialSmoothing

DB_PATH = "data/factory.db"
OUTPUT_FORECAST_PATH = "data/processed/forecast_demand.csv"
HORIZON_DAYS = 28  # 4 haftalık taktik planlama ufku

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
    
    wape = np.sum(np.abs(actual - pred)) / np.sum(actual)
    rmse = np.sqrt(np.mean((actual - pred) ** 2))
    bias = np.sum(pred - actual)
    
    return round(wape, 4), round(rmse, 2), round(bias, 1)

def build_features(df_single):
    df_feat = df_single.copy().sort_values("order_date").reset_index(drop=True)
    
    # Lag Özellikleri (Şartname Madde 6)
    for lag in [1, 7, 14, 28]:
        df_feat[f"lag_{lag}"] = df_feat["demand"].shift(lag)
        
    # Kayan İstatistikler
    for window in [7, 14, 28]:
        df_feat[f"rolling_mean_{window}"] = df_feat["demand"].shift(1).rolling(window=window).mean()
    for window in [7, 28]:
        df_feat[f"rolling_std_{window}"] = df_feat["demand"].shift(1).rolling(window=window).std()
        
    # Takvim Özellikleri
    df_feat["day_of_week"] = df_feat["order_date"].dt.dayofweek
    df_feat["week_of_year"] = df_feat["order_date"].dt.isocalendar().week.astype(int)
    df_feat["month"] = df_feat["order_date"].dt.month
    df_feat["day_of_year"] = df_feat["order_date"].dt.dayofyear
    
    return df_feat.dropna().reset_index(drop=True)

def run_forecast_benchmark():
    df_all = load_factory_demand()
    products = sorted(df_all["product_id"].unique())
    
    benchmark_summary = []
    final_forecast_records = []

    print("=" * 85)
    print("      AŞAMA 3: TALEP TAHMİNLEME & MODEL KIYASLAMA (BENCHMARK)      ")
    print("=" * 85)

    for pid in products:
        pdf = df_all[df_all["product_id"] == pid].sort_values("order_date").reset_index(drop=True)
        
        # Kronolojik Train / Test Ayrımı (Son 28 gün Test Seti)
        train_raw = pdf.iloc[:-HORIZON_DAYS].copy()
        test_raw = pdf.iloc[-HORIZON_DAYS:].copy()
        y_test = test_raw["demand"].values

        # 1. Naive Model (Son günün talebi)
        pred_naive = np.repeat(train_raw["demand"].iloc[-1], HORIZON_DAYS)
        w_naive, r_naive, b_naive = evaluate_metrics(y_test, pred_naive)

        # 2. Seasonal Naive Model (Son 7 günün haftalık döngüsü)
        last_7_days = train_raw["demand"].iloc[-7:].values
        pred_snaive = np.tile(last_7_days, int(HORIZON_DAYS / 7))
        w_snaive, r_snaive, b_snaive = evaluate_metrics(y_test, pred_snaive)

        # 3. Moving Average (Son 7 gün ortalaması)
        pred_ma = np.repeat(train_raw["demand"].iloc[-7:].mean(), HORIZON_DAYS)
        w_ma, r_ma, b_ma = evaluate_metrics(y_test, pred_ma)

        # 4. Holt-Winters (Exponential Smoothing)
        hw_model = ExponentialSmoothing(
            train_raw["demand"],
            trend="add",
            seasonal="add",
            seasonal_periods=7
        ).fit()
        pred_hw = hw_model.forecast(HORIZON_DAYS).values
        w_hw, r_hw, b_hw = evaluate_metrics(y_test, pred_hw)

        # 5. LightGBM
        feat_df = build_features(pdf)
        train_feat = feat_df.iloc[:-HORIZON_DAYS]
        test_feat = feat_df.iloc[-HORIZON_DAYS:]
        
        feature_cols = [c for c in feat_df.columns if c not in ["order_date", "product_id", "demand"]]
        
        lgb_train = lgb.Dataset(train_feat[feature_cols], label=train_feat["demand"])
        params = {
            "objective": "regression",
            "metric": "rmse",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
            "seed": 42
        }
        gbm = lgb.train(params, lgb_train, num_boost_round=150)
        pred_lgb = gbm.predict(test_feat[feature_cols])
        w_lgb, r_lgb, b_lgb = evaluate_metrics(test_feat["demand"].values, pred_lgb)

        # Model Değerlendirme Havuzu
        models = {
            "Naive": (w_naive, r_naive, b_naive, pred_naive),
            "Seasonal Naive": (w_snaive, r_snaive, b_snaive, pred_snaive),
            "Moving Average": (w_ma, r_ma, b_ma, pred_ma),
            "Holt-Winters": (w_hw, r_hw, b_hw, pred_hw),
            "LightGBM": (w_lgb, r_lgb, b_lgb, pred_lgb)
        }

        # Şartname Kuralı: En düşük WAPE değerine sahip model seçilir
        best_name = min(models, key=lambda k: models[k][0])
        best_pred = models[best_name][3]

        for m_name, (w, r, b, _) in models.items():
            benchmark_summary.append({
                "SKU": pid,
                "Model": m_name,
                "WAPE": f"{w:.4f}",
                "RMSE": f"{r:.2f}",
                "Bias": f"{b:.1f}",
                "Kazanan": "✓" if m_name == best_name else ""
            })

        for d, q in zip(test_raw["order_date"], best_pred):
            final_forecast_records.append({
                "forecast_date": d.strftime("%Y-%m-%d"),
                "product_id": pid,
                "forecast_demand": int(round(max(0, q))),
                "model_used": best_name
            })

    # Benchmark Raporunu Ekrana Bas
    summary_df = pd.DataFrame(benchmark_summary)
    print(summary_df.to_string(index=False))
    print("-" * 85)

    # SQLite ve CSV'ye Kaydetme
    os.makedirs(os.path.dirname(OUTPUT_FORECAST_PATH), exist_ok=True)
    forecast_df = pd.DataFrame(final_forecast_records)
    forecast_df.to_csv(OUTPUT_FORECAST_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    forecast_df.to_sql("forecast_demand", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] 28 Günlük Tahminler Dosyaya Yazıldı: {OUTPUT_FORECAST_PATH}")
    print(f"[OK] SQLite 'forecast_demand' tablosu güncellendi.")
    print("=" * 85)

if __name__ == "__main__":
    run_forecast_benchmark()