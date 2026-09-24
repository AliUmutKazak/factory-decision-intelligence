import os
import sqlite3
import pandas as pd
from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    GRID_EMISSION_FACTOR,
    DIESEL_EMISSION_FACTOR,
    DEFAULT_FORKLIFT_LITERS,
    CARBON_PRICE_SCENARIOS_EUR,
)

OUTPUT_CARBON_PATH = PROCESSED_DATA_DIR / "carbon_analytics.csv"
OUTPUT_MACHINE_CARBON_PATH = PROCESSED_DATA_DIR / "carbon_machine_kpis.csv"

def compute_carbon_analytics(run_id=None):
    conn = sqlite3.connect(DB_PATH)
    energy_kpi = pd.read_sql("SELECT * FROM energy_kpis", conn).iloc[0]
    machine_kpis_df = pd.read_sql("SELECT * FROM energy_machine_kpis", conn)
    conn.close()

    total_kwh = float(energy_kpi["grand_total_kwh"])
    total_units = int(energy_kpi["total_units_produced"])

    # 1. Kapsam 1 Doğrudan Emisyonlar (Tesis İçi Forklift / Lojistik)
    scope_1_tco2e = DEFAULT_FORKLIFT_LITERS * DIESEL_EMISSION_FACTOR

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
        scenario_records.append({
            "carbon_price_eur_per_ton": price,
            "total_carbon_exposure_eur": round(exposure_eur, 2),
            "carbon_cost_per_unit_eur": round(exposure_eur / total_units, 4) if total_units > 0 else 0.0
        })

    scen_df = pd.DataFrame(scenario_records)

    # Rapor Çıktısı
    print("=" * 80)
    print("            AŞAMA 7B: KURUMSAL KARBON ANALİTİĞİ (GHG PROTOCOL)            ")
    print("=" * 80)
    print(f"Kapsam 1 Doğrudan Emisyonlar (Scope 1) : {scope_1_tco2e:.3f} tCO2e (Dizel Lojistik)")
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
        "kgco2e_per_unit": round(kgco2e_per_unit, 4)
    }

    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    carbon_kpis_df = pd.DataFrame([carbon_summary])

    if run_id:
        carbon_kpis_df["run_id"] = run_id
        machine_kpis_df["run_id"] = run_id
        scen_df["run_id"] = run_id

    carbon_kpis_df.to_csv(OUTPUT_CARBON_PATH, index=False)
    machine_kpis_df.to_csv(OUTPUT_MACHINE_CARBON_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    carbon_kpis_df.to_sql("carbon_kpis", conn, index=False, if_exists="replace")
    machine_kpis_df.to_sql("carbon_machine_kpis", conn, index=False, if_exists="replace")
    scen_df.to_sql("carbon_price_scenarios", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Karbon KPI'ları Kaydedildi: {OUTPUT_CARBON_PATH}")
    print(f"[OK] Makine Karbon KPI'ları Kaydedildi: {OUTPUT_MACHINE_CARBON_PATH}")
    print(f"[OK] SQLite 'carbon_kpis', 'carbon_machine_kpis' ve 'carbon_price_scenarios' tabloları güncellendi.")

if __name__ == "__main__":
    compute_carbon_analytics()