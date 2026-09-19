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

    # Ürün bazlı toplam standart süre (saat/koli)
    prod_routing = routing_df.groupby("product_id")["processing_time_min"].sum().reset_index()
    prod_meta = products_df.merge(prod_routing, on="product_id")

    # Ürün ailesi bazlı ağırlıklı ortalama üretim süresi (saat/koli)
    family_hours = (
        prod_meta.groupby("family_id")["processing_time_min"].mean() / 60.0
    ).to_dict()

    demand = {}
    for _, row in family_weekly.iterrows():
        demand[(row["family_id"], row["period_week"])] = row["forecast_batches"]

    # Fabrika Toplam Çalışma Kapasitesi (Makine sayısı dinamik okunur)
    active_machine_count = len(machines_df)
    nominal_weekly_hours = WEEKLY_HOURS_PER_MACHINE * float(active_machine_count)
    effective_hours = nominal_weekly_hours * (1.0 - AGGREGATE_CAPACITY_BUFFER)

    model = pulp.LpProblem("Industrial_Aggregate_Planning", pulp.LpMinimize)

    # Karar Değişkenleri (Sürekli LP)
    P = pulp.LpVariable.dicts("Prod", [(f, t) for f in families for t in periods], lowBound=0, cat="Continuous")
    I = pulp.LpVariable.dicts("Inv", [(f, t) for f in families for t in periods], lowBound=0, cat="Continuous")
    B = pulp.LpVariable.dicts("Backlog", [(f, t) for f in families for t in periods], lowBound=0, cat="Continuous")
    OT = pulp.LpVariable.dicts("Overtime", periods, lowBound=0, upBound=AGGREGATE_MAX_OVERTIME_HOURS, cat="Continuous")

    # Amaç Fonksiyonu: Üretim İşçiliği + Elde Tutma + Gecikme Cezası + Fazla Mesai
    model += pulp.lpSum(
        P[(f, t)] * family_hours[f] * LABOR_COST_STANDARD_HR +
        I[(f, t)] * AGGREGATE_HOLDING_COST_PER_BATCH +
        B[(f, t)] * AGGREGATE_BACKLOG_PENALTY_PER_BATCH
        for f in families for t in periods
    ) + pulp.lpSum(OT[t] * LABOR_COST_OVERTIME_HR for t in periods)

    capacity_constraints = {}
    for t in periods:
        # 1. Kapasite Kısıtı
        c_cap = pulp.lpSum(P[(f, t)] * family_hours[f] for f in families) <= effective_hours + OT[t]
        model += c_cap, f"Capacity_W{t}"
        capacity_constraints[t] = c_cap

        for f in families:
            prev_inv = AGGREGATE_INITIAL_INVENTORY.get(f, 0.0) if t == 1 else I[(f, t - 1)]
            prev_backlog = 0.0 if t == 1 else B[(f, t - 1)]

            # 2. Dinamik Envanter Denge Kısıtı: I_t - B_t = I_{t-1} - B_{t-1} + P_t - D_t
            model += (
                I[(f, t)] - B[(f, t)] == prev_inv - prev_backlog + P[(f, t)] - demand[(f, t)],
                f"Balance_{f}_W{t}"
            )

    model.solve(pulp.PULP_CBC_CMD(msg=False))

    plan_records = []
    for t in periods:
        for f in families:
            plan_records.append({
                "period_week": t,
                "family_id": f,
                "demand_batches": round(demand[(f, t)], 1),
                "prod_batches": round(P[(f, t)].varValue, 1),
                "end_inv_batches": round(I[(f, t)].varValue, 1),
                "backlog_batches": round(B[(f, t)].varValue, 1),
                "overtime_hours": round(OT[t].varValue, 1)
            })

    shadow_prices = {t: round(capacity_constraints[t].pi, 2) for t in periods}

    return pd.DataFrame(plan_records), shadow_prices

def disaggregate_to_sku(family_plan_df, sku_weekly):
    sku_plan = []
    for (week, fam), group in sku_weekly.groupby(["period_week", "family_id"]):
        fam_target = family_plan_df[
            (family_plan_df["period_week"] == week) & (family_plan_df["family_id"] == fam)
        ]["prod_batches"].values[0]

        total_fam_demand = group["forecast_batches"].sum()

        for _, row in group.iterrows():
            ratio = (row["forecast_batches"] / total_fam_demand) if total_fam_demand > 0 else (1.0 / len(group))
            batch_target = round(fam_target * ratio, 1)
            sku_plan.append({
                "period_week": week,
                "product_id": row["product_id"],
                "family_id": fam,
                "weekly_forecast_units": int(round(row["forecast_units"])),
                "planned_batches": batch_target,
                "planned_units": int(round(batch_target * UNITS_PER_BATCH))
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
    