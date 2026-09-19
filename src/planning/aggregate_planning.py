import os
import sqlite3
import pandas as pd
import numpy as np
import pulp

from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    WEEKLY_HOURS_PER_MACHINE,
    LABOR_COST_STANDARD_HR,
    LABOR_COST_OVERTIME_HR,
    UNITS_PER_BATCH,
    AGGREGATE_CAPACITY_BUFFER,
    AGGREGATE_MAX_OVERTIME_HOURS,
    AGGREGATE_HOLDING_COST_PER_BATCH,
    AGGREGATE_BACKLOG_PENALTY_PER_BATCH,
    AGGREGATE_INITIAL_INVENTORY,
)

OUTPUT_AGGREGATE_PATH = PROCESSED_DATA_DIR / "aggregate_plan.csv"
OUTPUT_SKU_PLAN_PATH = PROCESSED_DATA_DIR / "sku_production_plan.csv"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    forecast_df = pd.read_sql("SELECT * FROM forecast_demand", conn)
    products_df = pd.read_sql("SELECT * FROM products", conn)
    routing_df = pd.read_sql("SELECT * FROM routing", conn)
    machines_df = pd.read_sql("SELECT * FROM machines", conn)
    conn.close()

    forecast_df["forecast_date"] = pd.to_datetime(forecast_df["forecast_date"])
    return forecast_df, products_df, routing_df, machines_df

def build_weekly_forecast_bridge(forecast_df, products_df):
    min_date = forecast_df["forecast_date"].min()
    forecast_df["day_index"] = (forecast_df["forecast_date"] - min_date).dt.days
    forecast_df["period_week"] = (forecast_df["day_index"] // 7) + 1  # 1..4

    merged = forecast_df.merge(products_df[["product_id", "family_id"]], on="product_id")

    # Talebi fabrika üretim partilerine / kolilerine (batches) dönüştür
    merged["forecast_batches"] = merged["forecast_demand"] / UNITS_PER_BATCH

    sku_weekly = (
        merged.groupby(["period_week", "product_id", "family_id"])
        .agg(
            forecast_units=("forecast_demand", "sum"),
            forecast_batches=("forecast_batches", "sum")
        )
        .reset_index()
    )

    family_weekly = (
        sku_weekly.groupby(["period_week", "family_id"])["forecast_batches"]
        .sum()
        .round(1)
        .reset_index()
    )

    return sku_weekly, family_weekly

def solve_aggregate_lp(family_weekly, products_df, routing_df, machines_df):
    periods = sorted(family_weekly["period_week"].unique())
    families = sorted(family_weekly["family_id"].unique())
    machines = sorted(machines_df["machine_id"].unique())

    # 1. Her ürün ailesinin her tezgâhtaki birim işleme süresi (a_{f,m} - saat/koli)
    merged_routing = routing_df.merge(products_df[["product_id", "family_id"]], on="product_id")
    fam_mach_hours = (
        merged_routing.groupby(["family_id", "machine_id"])["processing_time_min"].mean() / 60.0
    ).to_dict()

    # Toplam işçilik maliyeti için aile bazlı toplam rota süresi
    family_total_hours = {
        f: sum(fam_mach_hours.get((f, m), 0.0) for m in machines)
        for f in families
    }

    demand = {}
    for _, row in family_weekly.iterrows():
        demand[(row["family_id"], row["period_week"])] = row["forecast_batches"]

    # Makine Başına Efektif Kapasite (Buffer düşülmüş standart kapasite)
    effective_hours_per_machine = WEEKLY_HOURS_PER_MACHINE * (1.0 - AGGREGATE_CAPACITY_BUFFER)

    model = pulp.LpProblem("Industrial_Aggregate_Planning", pulp.LpMinimize)

    # Karar Değişkenleri
    P = pulp.LpVariable.dicts("Prod", [(f, t) for f in families for t in periods], lowBound=0, cat="Continuous")
    I = pulp.LpVariable.dicts("Inv", [(f, t) for f in families for t in periods], lowBound=0, cat="Continuous")
    B = pulp.LpVariable.dicts("Backlog", [(f, t) for f in families for t in periods], lowBound=0, cat="Continuous")
    
    # Fazla Mesai artık her makine için ayrı tanımlanır (OT_{m,t})
    OT = pulp.LpVariable.dicts(
        "Overtime",
        [(m, t) for m in machines for t in periods],
        lowBound=0,
        upBound=AGGREGATE_MAX_OVERTIME_HOURS,
        cat="Continuous"
    )

    # Amaç Fonksiyonu: İşçilik + Stok Tutma + Gecikme + Makine Bazlı Fazla Mesai Maliyeti
    model += pulp.lpSum(
        P[(f, t)] * family_total_hours[f] * LABOR_COST_STANDARD_HR +
        I[(f, t)] * AGGREGATE_HOLDING_COST_PER_BATCH +
        B[(f, t)] * AGGREGATE_BACKLOG_PENALTY_PER_BATCH
        for f in families for t in periods
    ) + pulp.lpSum(
        OT[(m, t)] * LABOR_COST_OVERTIME_HR for m in machines for t in periods
    )

    capacity_constraints = {}
    for t in periods:
        # 1. MAKİNE BAZLI KAPASİTE KISITI: Her tezgâhın yükü kendi kapasitesini aşamaz
        for m in machines:
            c_cap = pulp.lpSum(
                P[(f, t)] * fam_mach_hours.get((f, m), 0.0) for f in families
            ) <= effective_hours_per_machine + OT[(m, t)]
            
            model += c_cap, f"Capacity_{m}_W{t}"
            capacity_constraints[(m, t)] = c_cap

        # 2. Dinamik Envanter Denge Kısıtı: I_t - B_t = I_{t-1} - B_{t-1} + P_t - D_t
        for f in families:
            prev_inv = AGGREGATE_INITIAL_INVENTORY.get(f, 0.0) if t == 1 else I[(f, t - 1)]
            prev_backlog = 0.0 if t == 1 else B[(f, t - 1)]

            model += (
                I[(f, t)] - B[(f, t)] == prev_inv - prev_backlog + P[(f, t)] - demand[(f, t)],
                f"Balance_{f}_W{t}"
            )

    model.solve(pulp.PULP_CBC_CMD(msg=False))

    plan_records = []
    for t in periods:
        # Hafta bazında en çok fazla mesai yapan makinenin süresini (darboğaz mesaisini) özet al
        max_overtime_w = max(OT[(m, t)].varValue for m in machines)
        for f in families:
            plan_records.append({
                "period_week": t,
                "family_id": f,
                "demand_batches": round(demand[(f, t)], 1),
                "prod_batches": round(P[(f, t)].varValue, 1),
                "end_inv_batches": round(I[(f, t)].varValue, 1),
                "backlog_batches": round(B[(f, t)].varValue, 1),
                "overtime_hours": round(max_overtime_w, 1)
            })

    # Darboğaz makinenin (M01) gölge fiyatını döndür
    shadow_prices = {}
    for t in periods:
        # En kısıtlayıcı tezgâhın dual değerini al
        bottleneck_pi = capacity_constraints[("M01", t)].pi if ("M01", t) in capacity_constraints else 0.0
        shadow_prices[t] = round(bottleneck_pi, 2)

    return pd.DataFrame(plan_records), shadow_prices

def disaggregate_to_sku(family_plan_df, sku_weekly):
    sku_plan = []
    for (week, fam), group in sku_weekly.groupby(["period_week", "family_id"]):
        # 1. Aile hedef batch sayısını tam sayıya yuvarla (Örn: 249.3 -> 249)
        fam_target_raw = family_plan_df[
            (family_plan_df["period_week"] == week) & (family_plan_df["family_id"] == fam)
        ]["prod_batches"].values[0]
        
        fam_target = int(round(fam_target_raw))
        total_fam_demand = group["forecast_batches"].sum()

        sku_allocations = []
        for _, row in group.iterrows():
            ratio = (row["forecast_batches"] / total_fam_demand) if total_fam_demand > 0 else (1.0 / len(group))
            
            # Tam kısmı (floor) ve ondalık kalanı (remainder) ayır
            exact_batches = fam_target * ratio
            floor_batches = int(exact_batches) 
            remainder = exact_batches - floor_batches
            
            sku_allocations.append({
                "period_week": week,
                "product_id": row["product_id"],
                "family_id": fam,
                "weekly_forecast_units": int(round(row["forecast_units"])),
                "floor_batches": floor_batches,
                "remainder": remainder
            })

        # 2. Largest Remainder Method: Eksik kalan batch'leri dağıt
        total_allocated = sum(item["floor_batches"] for item in sku_allocations)
        missing_batches = fam_target - total_allocated

        # Kalan değerine göre büyükten küçüğe sırala
        sku_allocations.sort(key=lambda x: x["remainder"], reverse=True)

        # En büyük kalanlara sahip olanlara 1'er batch ekleyerek toplamı kilitle
        for i in range(missing_batches):
            sku_allocations[i]["floor_batches"] += 1

        # 3. Nihai listeyi oluştur (Artık %100 tam sayı garantili)
        for item in sku_allocations:
            planned_batches = item["floor_batches"]
            sku_plan.append({
                "period_week": item["period_week"],
                "product_id": item["product_id"],
                "family_id": item["family_id"],
                "weekly_forecast_units": item["weekly_forecast_units"],
                "planned_batches": planned_batches,
                "planned_units": int(planned_batches * UNITS_PER_BATCH)
            })

    return pd.DataFrame(sku_plan)

def run_planning_pipeline():
    forecast_df, products_df, routing_df, machines_df = load_data()
    sku_weekly, family_weekly = build_weekly_forecast_bridge(forecast_df, products_df)

    family_plan_df, shadow_prices = solve_aggregate_lp(family_weekly, products_df, routing_df, machines_df)
    sku_plan_df = disaggregate_to_sku(family_plan_df, sku_weekly)

    print("=" * 85)
    print("      AŞAMA 4: HİYERARŞİK TAKTİK PLANLAMA (LEVEL 1: FAMILY AGGREGATE LP)      ")
    print("=" * 85)
    print(family_plan_df.to_string(index=False))
    print("-" * 85)
    print("KAPASİTE KISITI GÖLGE FİYATLARI (Shadow Prices - $/Saat):")
    for w, sp in shadow_prices.items():
        print(f"  - Hafta {w}: {sp:.2f} $/saat")
    print("-" * 85)
    print("LEVEL 2: SKU AYRIŞTIRMA (DISAGGREGATION) ÖZETİ (İlk 10 Kayıt):")
    print(sku_plan_df.head(10).to_string(index=False))
    print("=" * 85)

    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    family_plan_df.to_csv(OUTPUT_AGGREGATE_PATH, index=False)
    sku_plan_df.to_csv(OUTPUT_SKU_PLAN_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    family_plan_df.to_sql("aggregate_plan", conn, index=False, if_exists="replace")
    sku_plan_df.to_sql("sku_production_plan", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Aile Taktik Planı Kaydedildi: {OUTPUT_AGGREGATE_PATH}")
    print(f"[OK] SKU Üretim Hedefleri Kaydedildi: {OUTPUT_SKU_PLAN_PATH}")
    print(f"[OK] SQLite 'aggregate_plan' ve 'sku_production_plan' güncellendi.")
    print("=" * 85)

if __name__ == "__main__":
    run_planning_pipeline()
    