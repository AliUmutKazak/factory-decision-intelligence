import pandas as pd
import numpy as np
import os

def run_preprocessing():
    raw_path = "data/raw/train.csv"
    output_path = "data/processed/factory_orders.csv"
    
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"{raw_path} bulunamadı! Dosyayı data/raw/ klasörüne taşıyın.")

    print("[1/4] Ham Kaggle verisi okunuyor...")
    df = pd.read_csv(raw_path)

    # 1. Domain Mapping: 5 Fabrika Ürünü ve 3 Ana Müşteri / Dağıtım Merkezi Seçimi
    # Ürün eşleme: Item 1..5 -> P01..P05 (Master data ile birebir uyumlu)
    product_mapping = {
        1: "P01",
        2: "P02",
        3: "P03",
        4: "P04",
        5: "P05"
    }

    # Müşteri eşleme: Store 1..3 -> Ana Müşteriler & Dağıtım Merkezleri
    customer_mapping = {
        1: "DC_Marmara",
        2: "DC_Ege",
        3: "OEM_Automotive"
    }

    print("[2/4] Endüstriyel filtreleme ve domain mapping uygulanıyor...")
    filtered_df = df[df["item"].isin(product_mapping.keys()) & df["store"].isin(customer_mapping.keys())].copy()

    filtered_df["product_id"] = filtered_df["item"].map(product_mapping)
    filtered_df["customer_id"] = filtered_df["store"].map(customer_mapping)
    filtered_df["order_date"] = pd.to_datetime(filtered_df["date"])
    filtered_df["order_qty"] = filtered_df["sales"]

    # Gereksiz ham kolonları temizle
    clean_df = filtered_df[["order_date", "customer_id", "product_id", "order_qty"]].sort_values(by=["order_date", "product_id"])

    # 2. Tarih Özellikleri (Zaman Serisi ve Feature Engineering Hazırlığı)
    clean_df["year"] = clean_df["order_date"].dt.year
    clean_df["month"] = clean_df["order_date"].dt.month
    clean_df["day_of_week"] = clean_df["order_date"].dt.dayofweek
    clean_df["is_weekend"] = clean_df["day_of_week"].isin([5, 6]).astype(int)

    print(f"[3/4] Temizlenen veri kaydediliyor -> {output_path}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    clean_df.to_csv(output_path, index=False)

    print("=" * 60)
    print("ETL & PREPROCESSING BAŞARIYLA TAMAMLANDI")
    print("=" * 60)
    print(f"Toplam Sipariş Kaydı : {len(clean_df):,} satır")
    print(f"Tarih Aralığı        : {clean_df['order_date'].min().date()} -> {clean_df['order_date'].max().date()}")
    print("Müşteri / DC Dağılımı:")
    print(clean_df["customer_id"].value_counts().to_string())
    print("-" * 60)
    print("Ürün Dağılımı:")
    print(clean_df["product_id"].value_counts().to_string())
    print("=" * 60)

if __name__ == "__main__":
    run_preprocessing()
