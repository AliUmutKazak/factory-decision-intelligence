"""
src/aggregate_planning.py
Hax & Meal Hiyerarşik Agrega Üretim Planlama Modülü (PuLP)
- Talep Ağırlıklı Kaynak Katsayıları (Forecast-weighted coefficients - Madde 6)
- Dinamik Darboğaz Tespiti & Dual Değer Analizi (Dynamic Bottleneck Identification - Madde 13)
"""

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
OUTPUT_MACHINE_CAPACITY_PATH = PROCESSED_DATA_DIR / "machine_capacity_plan.csv"

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

def solve_aggregate_lp(sku_weekly, family_weekly, products_df, routing_df, machines_df):
    periods = sorted(family_weekly["period_week"].unique())
    families = sorted(family_weekly["family_id"].unique())
    machines = sorted(machines_df["machine_id"].unique())

    # -------------------------------------------------------------
    # MADDE 6 İYİLEŞTİRMESİ: Talep Ağırlıklı Kaynak Katsayısı (a_{f,m,t})
    # Basit aritmetik ortalama yerine, o hafta SKU talepleriyle ağırlıklandırılmış 
    # birim operasyon süreleri hesaplanır.
    # -------------------------------------------------------------
    fam_mach_hours_per_period = {}
    
    # Rota verisini ürün ve aile bilgisiyle birleştir
    routing_extended = routing_df.merge(products_df[["product_id", "family_id"]], on="product_id")

    for t in periods:
        # O haftaya ait SKU talep paylarını bulmak için sku_weekly filtrele
        w_sku = sku_weekly[sku_weekly["period_week"] == t]
        
        for f in families:
            f_skus = w_sku[w_sku["family_id"] == f]
            for m in machines:
                # Bu aile ve makine için ilgili SKU'ların routing süreleri
                m_routing = routing_extended[(routing_extended["family_id"] == f) & (routing_extended["machine_id"] == m)]
                
                if f_skus.empty or m_routing.empty:
                    fam_mach_hours_per_period[(f, m, t)] = 0.0
                    continue

                # SKU bazlı talep ve süreleri birleştir (Rotası olmayan ürünler için işlem süresi 0.0 olmalıdır)
                merged_mix = f_skus.merge(m_routing[["product_id", "processing_time_min"]], on="product_id", how="left")
                merged_mix["processing_time_min"] = merged_mix["processing_time_min"].fillna(0.0)

                # Payda tüm ailenin toplam dönemsel talep tahmini olmalıdır
                total_fam_demand = f_skus["forecast_batches"].sum()

                if total_fam_demand > 0:
                    # Talep ağırlıklı fiili makine yük katsayısı (saat/parti)
                    weighted_time_min = (merged_mix["forecast_batches"] * merged_mix["processing_time_min"]).sum() / total_fam_demand
                    fam_mach_hours_per_period[(f, m, t)] = weighted_time_min / 60.0
                else:
                    # Talep yoksa tüm aile SKU'larının ortalama süresi (rotasızlar 0.0 kabul edilerek)
                    fallback_min = merged_mix["processing_time_min"].mean()
                    fam_mach_hours_per_period[(f, m, t)] = (fallback_min / 60.0) if not pd.isna(fallback_min) else 0.0

    # İşçilik maliyeti için genel aile-makine saatleri (statik toplamlar için ortalama)
    fam_mach_hours_avg = (
        routing_extended.groupby(["family_id", "machine_id"])["processing_time_min"].mean() / 60.0
    ).to_dict()

    family_total_hours = {
        f: sum(fam_mach_hours_avg.get((f, m), 0.0) for m in machines)
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
    
    # Fazla Mesai her makine için ayrı tanımlanır (OT_{m,t})
    OT = pulp.LpVariable.dicts(
        "Overtime",
        [(m, t) for m in machines for t in periods],
        lowBound=0,
        upBound=AGGREGATE_MAX_OVERTIME_HOURS,
        cat="Continuous"
    )

    # Amaç Fonksiyonu
    model += pulp.lpSum(
        P[(f, t)] * sum(fam_mach_hours_per_period.get((f, m, t), 0.0) for m in machines) * LABOR_COST_STANDARD_HR +
        I[(f, t)] * AGGREGATE_HOLDING_COST_PER_BATCH +
        B[(f, t)] * AGGREGATE_BACKLOG_PENALTY_PER_BATCH
        for f in families for t in periods
    ) + pulp.lpSum(
        OT[(m, t)] * LABOR_COST_OVERTIME_HR for m in machines for t in periods
    )

    capacity_constraints = {}
    for t in periods:
        # 1. MAKİNE BAZLI KAPASİTE KISITI (Talep ağırlıklı a_{f,m,t} katsayısı ile)
        for m in machines:
            c_cap = pulp.lpSum(
                P[(f, t)] * fam_mach_hours_per_period.get((f, m, t), 0.0) for f in families
            ) <= effective_hours_per_machine + OT[(m, t)]
            
            model += c_cap, f"Capacity_{m}_W{t}"
            capacity_constraints[(m, t)] = c_cap

        # 2. Dinamik Envanter Denge Kısıtı
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
        # Hafta bazında maksimum fazla mesai yapan makinenin süresi
        max_overtime_w = max(OT[(m, t)].varValue for m in machines)
        for f in families:
            plan_records.append({
                "period_week": t,
                "family_id": f,
                "demand_batches": round(demand[(f, t)], 1),
                "prod_batches": round(P[(f, t)].varValue, 1),
                "end_inv_batches": round(I[(f, t)].varValue, 1),
                "backlog_batches": round(B[(f, t)].varValue, 1),
                "max_machine_overtime_hours": round(max_overtime_w, 1)  # Madde 11 terminoloji düzeltmesi
            })

    # -------------------------------------------------------------
    # MADDE 13 İYİLEŞTİRMESİ: Dinamik Darboğaz ve Gölge Fiyat Tespiti
    # Sabit M01 yerine, o hafta en yüksek negatif dual değere (pi) sahip
    # makine otomatik olarak darboğaz seçilir ve raporlanır.
    # -------------------------------------------------------------
    shadow_prices_summary = {}
    for t in periods:
        period_duals = {}
        for m in machines:
            constraint_key = (m, t)
            if constraint_key in capacity_constraints:
                pi_val = capacity_constraints[constraint_key].pi
                period_duals[m] = pi_val if pi_val is not None else 0.0
            else:
                period_duals[m] = 0.0
        
        # En bağlayıcı (en düşük/negatif pi değeri) makineyi bul
        binding_machine = min(period_duals, key=period_duals.get)
        shadow_prices_summary[t] = {
            "bottleneck_machine": binding_machine,
            "shadow_price": round(period_duals[binding_machine], 2),
            "all_duals": {m: round(val, 2) for m, val in period_duals.items()}
        }

    # -------------------------------------------------------------
    # MADDE 13 İYİLEŞTİRMESİ: Makine Kapasite, Fazla Mesai ve Darboğaz Çıktısı
    # -------------------------------------------------------------
    machine_plan_records = []
    for t in periods:
        bottleneck_m = shadow_prices_summary[t]["bottleneck_machine"]
        for m in machines:
            reg_cap = round(effective_hours_per_machine, 1)
            ot_val = round(OT[(m, t)].varValue, 1)
            tot_cap = round(reg_cap + ot_val, 1)
            utilized = round(
                sum(
                    fam_mach_hours_per_period.get((f, m, t), 0.0) * P[(f, t)].varValue
                    for f in families
                ),
                1,
            )
            util_pct = round((utilized / tot_cap * 100) if tot_cap > 0 else 0.0, 1)
            dual_val = shadow_prices_summary[t]["all_duals"][m]
            is_bneck = "YES" if (m == bottleneck_m and dual_val < -1e-4) else "NO"

            machine_plan_records.append({
                "period_week": t,
                "machine_id": m,
                "regular_capacity_hours": reg_cap,
                "overtime_hours": ot_val,
                "total_capacity_hours": tot_cap,
                "utilized_hours": utilized,
                "utilization_pct": util_pct,
                "shadow_price_usd_per_hr": dual_val,
                "is_bottleneck": is_bneck
            })

    return pd.DataFrame(plan_records), shadow_prices_summary, pd.DataFrame(machine_plan_records)

def disaggregate_to_sku(family_plan_df, sku_weekly):
    sku_plan = []
    for (week, fam), group in sku_weekly.groupby(["period_week", "family_id"]):
        fam_target_raw = family_plan_df[
            (family_plan_df["period_week"] == week) & (family_plan_df["family_id"] == fam)
        ]["prod_batches"].values[0]
        
        fam_target = int(round(fam_target_raw))
        total_fam_demand = group["forecast_batches"].sum()

        sku_allocations = []
        for _, row in group.iterrows():
            ratio = (row["forecast_batches"] / total_fam_demand) if total_fam_demand > 0 else (1.0 / len(group))
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

        total_allocated = sum(item["floor_batches"] for item in sku_allocations)
        missing_batches = fam_target - total_allocated

        sku_allocations.sort(key=lambda x: x["remainder"], reverse=True)
        for i in range(missing_batches):
            sku_allocations[i]["floor_batches"] += 1

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

    family_plan_df, shadow_prices, machine_capacity_df = solve_aggregate_lp(sku_weekly, family_weekly, products_df, routing_df, machines_df)
    sku_plan_df = disaggregate_to_sku(family_plan_df, sku_weekly)

    print("=" * 85)
    print("      AŞAMA 4: HİYERARŞİK TAKTİK PLANLAMA (LEVEL 1: FAMILY AGGREGATE LP)      ")
    print("=" * 85)
    print(family_plan_df.to_string(index=False))
    print("-" * 85)
    print("DİNAMİK DARBOĞAZ VE GÖLGE FİYAT ANALİZİ (Shadow Prices & Binding Machines):")
    for w, info in shadow_prices.items():
        print(f"  - Hafta {w}: Darboğaz Tezgâh = {info['bottleneck_machine']} | Gölge Fiyat = {info['shadow_price']} $/hour")
        print(f"            Tüm Makine Dual Değerleri: {info['all_duals']}")
    print("-" * 85)
    print("LEVEL 2: SKU AYRIŞTIRMA (DISAGGREGATION) ÖZETİ (İlk 10 Kayıt):")
    print(sku_plan_df.head(10).to_string(index=False))
    print("=" * 85)

    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    family_plan_df.to_csv(OUTPUT_AGGREGATE_PATH, index=False)
    sku_plan_df.to_csv(OUTPUT_SKU_PLAN_PATH, index=False)
    machine_capacity_df.to_csv(OUTPUT_MACHINE_CAPACITY_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    family_plan_df.to_sql("aggregate_plan", conn, index=False, if_exists="replace")
    sku_plan_df.to_sql("sku_production_plan", conn, index=False, if_exists="replace")
    machine_capacity_df.to_sql("machine_capacity_plan", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Aile Taktik Planı Kaydedildi: {OUTPUT_AGGREGATE_PATH}")
    print(f"[OK] SKU Üretim Hedefleri Kaydedildi: {OUTPUT_SKU_PLAN_PATH}")
    print(f"[OK] Makine Kapasite Planı Kaydedildi: {OUTPUT_MACHINE_CAPACITY_PATH}")
    print(f"[OK] SQLite 'aggregate_plan', 'sku_production_plan' ve 'machine_capacity_plan' güncellendi.")
    print("=" * 85)

if __name__ == "__main__":
    run_planning_pipeline()