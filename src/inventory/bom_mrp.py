import os
import sqlite3
import pandas as pd
import numpy as np
from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    MRP_SERVICE_LEVEL_Z,
    INITIAL_INVENTORY,
)

OUTPUT_MRP_PATH = PROCESSED_DATA_DIR / "mrp_plan.csv"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    sku_plan = pd.read_sql("SELECT * FROM sku_production_plan", conn)
    bom = pd.read_sql("SELECT * FROM bom", conn)
    materials = pd.read_sql("SELECT * FROM materials", conn)
    conn.close()
    return sku_plan, bom, materials

def calculate_gross_requirements(sku_plan, bom):
    # Gross Requirement: GR_{m,t} = sum(BOM_{m,i} * PlannedUnits_{i,t})
    merged = sku_plan.merge(bom, on="product_id")
    merged["material_req"] = merged["planned_units"] * merged["qty_per_unit"]

    gross_req = (
        merged.groupby(["period_week", "material_id"])["material_req"]
        .sum()
        .reset_index()
        .rename(columns={"material_req": "gross_requirement"})
    )
    return gross_req

def run_mrp_engine():
    sku_plan, bom, materials = load_data()
    gross_df = calculate_gross_requirements(sku_plan, bom)

    periods = sorted(gross_df["period_week"].unique())
    mat_ids = materials["material_id"].unique()

    mrp_records = []

    print("=" * 95)
    print("           AŞAMA 5: BOM PATLATMA & ZAMAN FAZLI MRP-I (MALZEME PLANLAMA) RAPORU           ")
    print("=" * 95)

    for mid in mat_ids:
        mat_info = materials[materials["material_id"] == mid].iloc[0]
        lead_time_weeks = max(1, int(round(mat_info["lead_time_days"] / 7.0)))
        moq = float(mat_info["min_order_qty"])
        unit_cost = float(mat_info["unit_cost"])

        mat_gross = gross_df[gross_df["material_id"] == mid]
        sigma_w = mat_gross["gross_requirement"].std() if len(mat_gross) > 1 else 100.0
        safety_stock = int(round(MRP_SERVICE_LEVEL_Z * sigma_w * np.sqrt(lead_time_weeks)))

        current_inv = INITIAL_INVENTORY.get(mid, 0.0)

        for t in periods:
            req_row = mat_gross[mat_gross["period_week"] == t]
            gross_req = float(req_row["gross_requirement"].values[0]) if len(req_row) > 0 else 0.0

            # Dönem başı stok düşüşü
            inv_before_receipt = current_inv - gross_req

            # Net ihtiyaç: Stok emniyet stoğu altına inerse sipariş tetiklenir
            if inv_before_receipt < safety_stock:
                net_req = safety_stock - inv_before_receipt
            else:
                net_req = 0.0

            # Lot Boyutlandırma (MOQ katları)
            if net_req > 0:
                planned_receipt = int(np.ceil(net_req / moq) * moq)
            else:
                planned_receipt = 0

            # Dönem sonu projeksiyon stoğu
            current_inv = inv_before_receipt + planned_receipt

            # Sipariş Açma Zamanı (Release Week) & MRP İstisna Yönetimi (Action Message)
            release_week = t - lead_time_weeks
            if planned_receipt > 0:
                if release_week <= 0:
                    action_message = "EXPEDITE (Past Due)"
                else:
                    action_message = "RELEASE ORDER"
            else:
                action_message = "NONE"

            order_cost = planned_receipt * unit_cost

            mrp_records.append({
                "period_week": t,
                "material_id": mid,
                "material_name": mat_info["material_name"],
                "gross_req": round(gross_req, 1),
                "safety_stock": safety_stock,
                "projected_avail": round(current_inv, 1),
                "net_req": round(net_req, 1),
                "planned_receipt": planned_receipt,
                "planned_release_week": release_week,
                "planned_release_qty": planned_receipt,
                "action_message": action_message,
                "order_cost": round(order_cost, 2)
            })

    mrp_df = pd.DataFrame(mrp_records)

    # Detay Tablo Çıktısı
    display_cols = [
        "period_week", "material_id", "gross_req", "safety_stock",
        "projected_avail", "net_req", "planned_receipt", "planned_release_week", "action_message"
    ]
    print(mrp_df[display_cols].to_string(index=False))
    print("-" * 95)

    # Satınalma Bütçe Özeti
    summary_df = (
        mrp_df.groupby(["material_id", "material_name"])
        .agg(
            total_ordered=("planned_receipt", "sum"),
            total_procurement_cost=("order_cost", "sum")
        )
        .reset_index()
    )
    print("SATINALMA BÜTÇESİ & TOPLAM MALZEME TAAHHÜT ÖZETİ:")
    print(summary_df.to_string(index=False))
    total_mrp_spend = summary_df["total_procurement_cost"].sum()
    print(f"\nToplam Planlanan Satınalma Maliyeti: {total_mrp_spend:,.2f} TL")
    print("=" * 95)

    # SQLite ve CSV'ye Aktar
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    mrp_df.to_csv(OUTPUT_MRP_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    mrp_df.to_sql("mrp_plan", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Zaman Fazlı MRP Planı Kaydedildi: {OUTPUT_MRP_PATH}")
    print(f"[OK] SQLite 'mrp_plan' tablosu güncellendi.")

if __name__ == "__main__":
    run_mrp_engine()