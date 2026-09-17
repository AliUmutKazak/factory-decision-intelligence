import os
import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/factory.db"
PROCESSED_ORDERS_PATH = "data/processed/factory_orders.csv"
SYNTHETIC_DIR = "data/synthetic"

def analyze_demand_characteristics(orders_df: pd.DataFrame) -> pd.DataFrame:
    daily_product_demand = (
        orders_df.groupby(["order_date", "product_id"])["order_qty"]
        .sum()
        .reset_index()
    )

    stats = (
        daily_product_demand.groupby("product_id")["order_qty"]
        .agg(
            gunluk_ortalama="mean",
            gunluk_std="std",
            min_talep="min",
            max_talep="max",
            toplam_talep="sum"
        )
        .reset_index()
    )

    # Varyasyon Katsayisi (CV = sigma / mu)
    stats["cv_volatilite"] = (stats["gunluk_std"] / stats["gunluk_ortalama"]).round(3)
    stats["talep_profili"] = np.where(
        stats["cv_volatilite"] < 0.5, "Düzenli (Smooth)", "Dalgalı (Erratic)"
    )
    
    stats["gunluk_ortalama"] = stats["gunluk_ortalama"].round(1)
    stats["gunluk_std"] = stats["gunluk_std"].round(1)

    return stats

def initialize_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Islenmis siparis verisini aktar
    orders_df = pd.read_csv(PROCESSED_ORDERS_PATH)
    orders_df.to_sql("orders", conn, index=False, if_exists="replace")

    # 2. Sentetik fabrika ana veri tablolarini aktar
    synthetic_tables = [
        "machines",
        "products",
        "materials",
        "bom",
        "routing",
        "changeover_matrix",
    ]

    for table in synthetic_tables:
        csv_file = os.path.join(SYNTHETIC_DIR, f"{table}.csv")
        if os.path.exists(csv_file):
            tdf = pd.read_csv(csv_file)
            tdf.to_sql(table, conn, index=False, if_exists="replace")

    conn.commit()

    # 3. EDA Ozet Tablosu
    eda_summary = analyze_demand_characteristics(orders_df)

    print("=" * 70)
    print("      FABRİKA VERİTABANI & TALEP EDA RAPORU      ")
    print("=" * 70)
    print(eda_summary.to_string(index=False))
    print("-" * 70)

    # 4. Veritabani Dogrulama Sorgusu
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    print("SQLITE VERİTABANI DOĞRULAMASI:")
    print(f"Konum: {DB_PATH}")
    print(f"Yüklenen Tablolar ({len(tables)} adet): {', '.join(tables)}")

    for t in tables:
        count = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  - {t:<20}: {count:>6} satır")

    conn.close()
    print("=" * 70)

if __name__ == "__main__":
    initialize_database()