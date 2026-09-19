import os
import pandas as pd
from src.config import RAW_DATA_DIR, PROCESSED_DATA_DIR

def run_preprocessing():
    raw_path = RAW_DATA_DIR / "train.csv"
    output_path = PROCESSED_DATA_DIR / "factory_orders.csv"

    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"Ham sipariş dosyası bulunamadı: {raw_path}")

    print("[1/3] Ham veri seti okunuyor...")
    df = pd.read_csv(raw_path)

    # 5 Pilot Ürün Eşlemesi
    product_mapping = {1: "P01", 2: "P02", 3: "P03", 4: "P04", 5: "P05"}
    pilot_df = df[df["item"].isin(product_mapping.keys())].copy()
    pilot_df["product_id"] = pilot_df["item"].map(product_mapping)
    pilot_df["order_date"] = pd.to_datetime(pilot_df["date"])

    # 10 Mağaza talebini konsolide fabrika çekme talebine dönüştür: D_{i,t} = sum(Sales)
    print("[2/3] 10 mağaza talebi tek fabrika çekme talebine konsolide ediliyor...")
    factory_demand = (
        pilot_df.groupby(["order_date", "product_id"])["sales"]
        .sum()
        .reset_index()
        .rename(columns={"sales": "order_qty"})
    )

    # Takvim öznitelikleri
    factory_demand["year"] = factory_demand["order_date"].dt.year
    factory_demand["month"] = factory_demand["order_date"].dt.month
    factory_demand["day_of_week"] = factory_demand["order_date"].dt.dayofweek
    factory_demand["is_weekend"] = factory_demand["day_of_week"].isin([5, 6]).astype(int)

    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    factory_demand.to_csv(output_path, index=False)

    print(f"[3/3] Konsolide fabrika talebi kaydedildi -> {output_path}")
    print("=" * 65)
    print(f"Toplam Günlük Fabrika Talep Kaydı : {len(factory_demand):,} gün/ürün")
    print(f"Tarih Aralığı                     : {factory_demand['order_date'].min().date()} -> {factory_demand['order_date'].max().date()}")
    print("=" * 65)

if __name__ == "__main__":
    run_preprocessing()
    