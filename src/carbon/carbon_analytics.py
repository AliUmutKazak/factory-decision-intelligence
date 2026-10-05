"""
===============================================================================
CORPORATE CARBON ANALYTICS & GHG PROTOCOL ACCOUNTING ENGINE
===============================================================================
Metodolojik Kapsam ve Entegrasyon Mimarisi (Denetim Madde 24):
Kurumsal karbon ayak izi hesaplaması üç ana fabrika veri katmanına dayanır:

  1. Kapsam 1 (Doğrudan Emisyonlar - Forklift & İç Lojistik):
     - Endüstriyel Entegrasyon (Production Deployment Activity Drivers):
       * ERP Akaryakıt İşlemleri (Fuel Transactions / İrsaliye)
       * Telemetrik Forklift Çalışma Saatleri (Forklift Hours)
       * MES Malzeme Taşıma Hareketleri (Material Moves / Logistics Trips)
     - Analitik Taban Kestirimi (Baseline Fallback):
       * Çizelge makespan süresine endeksli haftalık operasyonel taban tüketim
         modeli (85 L/hafta takvim çarpanı).

  2. Kapsam 2 (Dolaylı Emisyonlar - Şebeke Elektriği):
     - Enerji simülasyonu ve akıllı sayaç (Smart Meter / Energy Meter) aktif
       güç integralleri.

Gerçek Sistem Bağlantı Mimarisi:
  [Energy Meter] + [Fuel Transactions] + [Production Execution (MES/MRP Moves)]
===============================================================================
"""

import os

import pandas as pd

from src.config import (
    CARBON_PRICE_SCENARIOS_EUR,
    DEFAULT_FORKLIFT_LITERS,
    DIESEL_EMISSION_FACTOR,
    GRID_EMISSION_FACTOR,
)
from src.config import get_runtime_paths
from src.utils.db import get_db_connection



def compute_carbon_analytics(run_id=None, db_path=None):
    runtime = get_runtime_paths()
    active_db_path = db_path or runtime["db_path"]
    processed_dir = runtime["processed_dir"]
    output_carbon_path = processed_dir / "carbon_analytics.csv"
    output_machine_carbon_path = processed_dir / "carbon_machine_kpis.csv"
    conn = get_db_connection(active_db_path)
    energy_kpi = pd.read_sql("SELECT * FROM energy_kpis", conn).iloc[0]
    machine_kpis_df = pd.read_sql("SELECT * FROM energy_machine_kpis", conn)
    conn.close()

    total_kwh = float(energy_kpi["grand_total_kwh"])
    total_units = int(energy_kpi["total_units_produced"])
    makespan_hours = float(energy_kpi.get("makespan_hours", 0.0))

    # 1. Kapsam 1 Doğrudan Emisyonlar (GHG Protocol Scope 1: Lojistik / Forklift Tüketimi)
    # Madde 24: Activity Driver Modellemesi (Fallback Baseline: 85 L/hafta @ makespan scaling)
    # Gerçek sistem entegrasyonu: Forklift Hours / Trips / Material Moves / Fuel Transactions
    activity_driver_label = "SCHEDULE_SCALED_BASELINE (85 L/week fallback)"
    run_weeks = (makespan_hours / 168.0) if makespan_hours > 0 else 1.0
    actual_forklift_liters = (DEFAULT_FORKLIFT_LITERS * run_weeks) if total_units > 0 else 0.0
    scope_1_tco2e = actual_forklift_liters * DIESEL_EMISSION_FACTOR

    # 2. Kapsam 2 Dolaylı Emisyonlar (Satın Alınan Elektrik & Makine Ayrıştırması)
    total_mwh = total_kwh / 1000.0
    scope_2_tco2e = total_mwh * GRID_EMISSION_FACTOR

    # Ham hassasiyetle hesapla (Raw Precision - First-Law Closed Loop)
    machine_total_kwh = float(machine_kpis_df["total_kwh"].sum())
    raw_scope_2 = (machine_kpis_df["total_kwh"] / 1000.0) * GRID_EMISSION_FACTOR

    if machine_total_kwh > 0:
        machine_kpis_df["carbon_share_pct"] = ((machine_kpis_df["total_kwh"] / machine_total_kwh) * 100.0).round(2)
    else:
        machine_kpis_df["carbon_share_pct"] = 0.0

    machine_kpis_df["scope_2_tco2e"] = raw_scope_2.round(4)

    total_tco2e = scope_1_tco2e + scope_2_tco2e
    kgco2e_per_unit = (total_tco2e * 1000.0) / total_units if total_units > 0 else 0.0

    # 3. Dahili Karbon Fiyatlandırma Senaryoları (€/tCO2e - Internal Carbon Pricing)
    scenario_records = []
    for price in CARBON_PRICE_SCENARIOS_EUR:
        exposure_eur = total_tco2e * price
        scenario_records.append(
            {
                "carbon_price_eur_per_ton": price,
                "total_carbon_exposure_eur": round(exposure_eur, 2),
                "carbon_cost_per_unit_eur": round(exposure_eur / total_units, 4) if total_units > 0 else 0.0,
            }
        )

    scen_df = pd.DataFrame(scenario_records)

    # Rapor Çıktısı
    print("=" * 80)
    print("            AŞAMA 7B: KURUMSAL KARBON ANALİTİĞİ (GHG PROTOCOL)            ")
    print("=" * 80)
    print(
        f"Kapsam 1 Doğrudan Emisyonlar (Scope 1) : {scope_1_tco2e:.3f} tCO2e (Dizel Lojistik - {actual_forklift_liters:.1f} L)"
    )
    print(f"  -> Activity Driver Modeli            : {activity_driver_label}")
    print(f"Kapsam 2 Dolaylı Emisyonlar (Scope 2)   : {scope_2_tco2e:.3f} tCO2e (Şebeke Elektriği)")
    print(f"Toplam Karbon Ayak İzi (Total tCO2e)   : {total_tco2e:.3f} tCO2e")
    print(f"Birim Karbon Yoğunluğu                 : {kgco2e_per_unit:.3f} kgCO2e / adet")
    print("-" * 80)
    print("MAKİNE BAZLI KAPSAM 2 KARBON DAĞILIMI:")
    print(machine_kpis_df[["machine_id", "total_kwh", "scope_2_tco2e", "carbon_share_pct"]].to_string(index=False))
    print("-" * 80)
    print("DAHİLİ KARBON FİYAT SENARYOLARI & GÖLGE MARUZİYET (INTERNAL CARBON PRICING):")
    print(scen_df.to_string(index=False))
    print("=" * 80)

    carbon_summary = {
        "scope_1_tco2e": round(scope_1_tco2e, 4),
        "scope_2_tco2e": round(scope_2_tco2e, 4),
        "total_tco2e": round(total_tco2e, 4),
        "kgco2e_per_unit": round(kgco2e_per_unit, 4),
    }

    processed_dir.mkdir(parents=True, exist_ok=True)
    carbon_kpis_df = pd.DataFrame([carbon_summary])

    if run_id:
        carbon_kpis_df["run_id"] = run_id
        machine_kpis_df["run_id"] = run_id
        scen_df["run_id"] = run_id

    carbon_kpis_df.to_csv(output_carbon_path, index=False)
    machine_kpis_df.to_csv(output_machine_carbon_path, index=False)

    conn = get_db_connection(active_db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS carbon_kpis (
            scope_1_tco2e REAL,
            scope_2_tco2e REAL,
            total_tco2e REAL,
            kgco2e_per_unit REAL,
            run_id TEXT
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS carbon_machine_kpis (
            machine_id TEXT,
            processing_hours REAL,
            setup_hours REAL,
            idle_hours REAL,
            processing_kwh REAL,
            setup_kwh REAL,
            idle_kwh REAL,
            total_kwh REAL,
            run_id TEXT,
            carbon_share_pct REAL,
            scope_2_tco2e REAL
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS carbon_price_scenarios (
            carbon_price_eur_per_ton INTEGER,
            total_carbon_exposure_eur REAL,
            carbon_cost_per_unit_eur REAL,
            run_id TEXT
        );
    """)
    cursor.execute("DELETE FROM carbon_kpis;")
    cursor.execute("DELETE FROM carbon_machine_kpis;")
    cursor.execute("DELETE FROM carbon_price_scenarios;")
    conn.commit()

    carbon_kpis_df.to_sql("carbon_kpis", conn, index=False, if_exists="append")
    if "data_source" in machine_kpis_df.columns:
        machine_kpis_df = machine_kpis_df.drop(columns=["data_source"])
    machine_kpis_df.to_sql("carbon_machine_kpis", conn, index=False, if_exists="append")
    scen_df.to_sql("carbon_price_scenarios", conn, index=False, if_exists="append")
    conn.close()

    print(f"[OK] Karbon KPI'ları Kaydedildi: {OUTPUT_CARBON_PATH}")
    print(f"[OK] Makine Karbon KPI'ları Kaydedildi: {OUTPUT_MACHINE_CARBON_PATH}")
    print("[OK] SQLite 'carbon_kpis', 'carbon_machine_kpis' ve 'carbon_price_scenarios' tabloları güncellendi.")


if __name__ == "__main__":
    compute_carbon_analytics()
