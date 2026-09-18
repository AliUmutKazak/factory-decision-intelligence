import sqlite3
import os
import pandas as pd
import numpy as np

DB_PATH = "data/factory.db"
OUTPUT_MRP_PATH = "data/processed/mrp_plan.csv"

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
    
    # Hafta ve Malzeme Listeleri
    periods = sorted(gross_df["period_week"].unique())
    mat_ids = materials["material_id"].unique()

    # Parametre ve Başlangıç Koşulları (Sentetik Fabrika Varsayımları)
    initial_inv = {
        "RAW_STEEL_A": 4500.0,
        "RAW_STEEL_B": 8000.0,
        "RAW_ALLOY_ROD": 6000.0,
        "COATING_POWDER": 600.0
    }
    
    # Servis seviyesi z = 1.65 (%95), SS = z * sigma_w * sqrt(L_weeks)
    z_score = 1.65

    mrp_records = []

    print("=" * 90)
    print("        AŞAMA 5: BOM PATLATMA & ZAMAN FAZLI MRP-I RAPORU        ")
    print("=" * 90)

    for mid in mat_ids:
        mat_info = materials[materials["material_id"] == mid].iloc[0]
        lead_time_weeks = max(1, int(round(mat_info["lead_time_days"] / 7.0)))
        moq = mat_info["min_order_qty"]
        unit_cost = mat_info["unit_cost"]

        # Malzemenin haftalık talep varyasyonu ve Emniyet Stoğu (SS)
        mat_gross = gross_df[gross_df["material_id"] == mid]
        sigma_w = mat_gross["gross_requirement"].std() if len(mat_gross) > 1 else 100.0
        safety_stock = int(round(z_score * sigma_w * np.sqrt(lead_time_weeks)))

        current_inv = initial_inv.get(mid, 0.0)

        for t in periods:
            req_row = mat_gross[mat_gross["period_week"] == t]
            gross_req = req_row["gross_requirement"].values[0] if len(req_row) > 0 else 0.0

            # Dönem Başı Mevcut Stoktan Düşüş
            inv_before_receipt = current_inv - gross_req

            # Net İhtiyaç: SS altına inilirse sipariş tetiklenir
            if inv_before_receipt < safety_stock:
                net_req = safety_stock - inv_before_receipt
            else:
                net_req = 0.0

            # Parti Büyüklüğü (Lot-Sizing / MOQ kuralı)
            if net_req > 0:
                planned_receipt = int(np.ceil(net_req / moq) * moq)
            else:
                planned_receipt = 0

            # Dönem Sonu Projeksiyon Stoğu
            current_inv = inv_before_receipt + planned_receipt

            # Sipariş Verilme Zamanı (Planned Release = t - LeadTime)
            release_week = t - lead_time_weeks

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
                "order_cost_tl": round(planned_receipt * unit_cost, 2)
            })

    mrp_df = pd.DataFrame(mrp_records)
    
    # Ekrana Özet Tablo Bas
    display_cols = [
        "period_week", "material_id", "gross_req", "safety_stock",
        "projected_avail", "net_req", "planned_receipt", "planned_release_week"
    ]
    print(mrp_df[display_cols].to_string(index=False))
    print("-" * 90)

    # SQLite ve CSV'ye Aktar
    os.makedirs(os.path.dirname(OUTPUT_MRP_PATH), exist_ok=True)
    mrp_df.to_csv(OUTPUT_MRP_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    mrp_df.to_sql("mrp_plan", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Zaman Fazlı MRP Planı Kaydedildi: {OUTPUT_MRP_PATH}")
    print(f"[OK] SQLite 'mrp_plan' tablosu güncellendi.")
    print("=" * 90)

if __name__ == "__main__":
    run_mrp_engine()