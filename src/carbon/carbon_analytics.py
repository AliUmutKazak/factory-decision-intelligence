import sqlite3
import os
import pandas as pd

DB_PATH = "data/factory.db"
OUTPUT_CARBON_PATH = "data/processed/carbon_analytics.csv"

def compute_carbon_analytics():
    conn = sqlite3.connect(DB_PATH)
    energy_kpi = pd.read_sql("SELECT * FROM energy_kpis", conn).iloc[0]
    schedule_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    total_kwh = energy_kpi["grand_total_kwh"]
    total_units = energy_kpi["total_units_produced"]

    # Emisyon Faktörleri (GHG Protocol Standardı)
    GRID_EMISSION_FACTOR = 0.440      # tCO2e / MWh (Şebeke faktörü)
    DIESEL_EMISSION_FACTOR = 0.00268 # tCO2e / Litre dizel

    # Scope 1 (Forklift / Tesis İçi Yakıt)
    forklift_liters = 85.0
    scope_1_tco2e = forklift_liters * DIESEL_EMISSION_FACTOR

    # Scope 2 (Satın Alınan Elektrik)
    total_mwh = total_kwh / 1000.0
    scope_2_tco2e = total_mwh * GRID_EMISSION_FACTOR

    total_tco2e = scope_1_tco2e + scope_2_tco2e
    kgco2e_per_unit = (total_tco2e * 1000.0) / total_units

    # EU ETS Dahili Karbon Fiyatlandırma Senaryoları (€/tCO2e)
    carbon_prices_eur = [0, 50, 80, 100, 120]
    scenario_records = []
    for price in carbon_prices_eur:
        exposure_eur = total_tco2e * price
        scenario_records.append({
            "carbon_price_eur_per_ton": price,
            "total_carbon_exposure_eur": round(exposure_eur, 2),
            "carbon_cost_per_unit_eur": round(exposure_eur / total_units, 4)
        })

    print("=" * 80)
    print("            AŞAMA 7B: KURUMSAL KARBON ANALİTİĞİ (GHG PROTOCOL)            ")
    print("=" * 80)
    print(f"Kapsam 1 Doğrudan Emisyonlar (Scope 1) : {scope_1_tco2e:.3f} tCO2e (Forklift Yakıtı)")
    print(f"Kapsam 2 Dolaylı Emisyonlar (Scope 2)   : {scope_2_tco2e:.3f} tCO2e (Şebeke Elektriği)")
    print(f"Toplam Karbon Ayak İzi (Total tCO2e)   : {total_tco2e:.3f} tCO2e")
    print(f"Birim Karbon Yoğunluğu                 : {kgco2e_per_unit:.3f} kgCO2e / adet")
    print("-" * 80)
    print("EU ETS PİYASA TAHSİSAT FİYATI & DAHİLİ KARBON MARUZİYET SENARYOLARI:")
    scen_df = pd.DataFrame(scenario_records)
    print(scen_df.to_string(index=False))
    print("=" * 80)

    carbon_summary = {
        "scope_1_tco2e": round(scope_1_tco2e, 4),
        "scope_2_tco2e": round(scope_2_tco2e, 4),
        "total_tco2e": round(total_tco2e, 4),
        "kgco2e_per_unit": round(kgco2e_per_unit, 4)
    }

    os.makedirs(os.path.dirname(OUTPUT_CARBON_PATH), exist_ok=True)
    pd.DataFrame([carbon_summary]).to_csv(OUTPUT_CARBON_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    pd.DataFrame([carbon_summary]).to_sql("carbon_kpis", conn, index=False, if_exists="replace")
    scen_df.to_sql("carbon_price_scenarios", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Karbon KPI'ları ve Senaryoları Kaydedildi: {OUTPUT_CARBON_PATH}")
    print(f"[OK] SQLite 'carbon_kpis' ve 'carbon_price_scenarios' tabloları güncellendi.")

if __name__ == "__main__":
    compute_carbon_analytics()