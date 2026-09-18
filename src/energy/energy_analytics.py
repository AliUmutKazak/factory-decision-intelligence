import sqlite3
import os
import pandas as pd
import numpy as np

DB_PATH = "data/factory.db"
OUTPUT_ENERGY_KPI_PATH = "data/processed/energy_kpis.csv"
OUTPUT_PROFILE_PATH = "data/processed/energy_profile_15min.csv"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    schedule_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    machines_df = pd.read_sql("SELECT * FROM machines", conn)
    conn.close()
    return schedule_df, machines_df

def compute_energy_analytics():
    schedule_df, machines_df = load_data()

    # Makine Güç Parametreleri (kW) - Sentetik Fabrika Spesifikasyonu
    machine_specs = {
        "M01": {"base_kw": 4.5, "setup_kw": 2.2, "idle_kw": 0.8},
        "M02": {"base_kw": 3.2, "setup_kw": 1.5, "idle_kw": 0.6},
        "M03": {"base_kw": 8.0, "setup_kw": 3.5, "idle_kw": 1.8}
    }

    makespan_min = int(schedule_df["end_min"].max())
    total_units_produced = schedule_df[schedule_df["operation_seq"] == 1]["batch_qty"].sum()

    # 1. İşlem Enerjisi (Processing Energy)
    schedule_df["proc_hours"] = schedule_df["duration_min"] / 60.0
    schedule_df["base_energy_kwh"] = schedule_df.apply(
        lambda r: r["proc_hours"] * machine_specs[r["machine_id"]]["base_kw"], axis=1
    )
    schedule_df["variable_energy_kwh"] = schedule_df["batch_qty"] * schedule_df["kwh_unit"]
    schedule_df["total_proc_energy_kwh"] = schedule_df["base_energy_kwh"] + schedule_df["variable_energy_kwh"]

    total_proc_kwh = schedule_df["total_proc_energy_kwh"].sum()

    # 2. Hazırlık (Setup) ve Boşta Bekleme (Idle) Ayrıştırması
    machine_kpis = []
    total_setup_kwh = 0.0
    total_idle_kwh = 0.0

    for m_id, specs in machine_specs.items():
        m_tasks = schedule_df[schedule_df["machine_id"] == m_id].sort_values("start_min")
        proc_time_m = m_tasks["duration_min"].sum()
        m_proc_kwh = m_tasks["total_proc_energy_kwh"].sum()

        m_setup_time = 0
        m_idle_time = 0
        last_end = 0

        for _, task in m_tasks.iterrows():
            gap = task["start_min"] - last_end
            if gap > 0:
                setup_part = min(gap, 30)
                idle_part = gap - setup_part
                m_setup_time += setup_part
                m_idle_time += idle_part
            last_end = task["end_min"]

        if last_end < makespan_min:
            m_idle_time += (makespan_min - last_end)

        m_setup_kwh = (m_setup_time / 60.0) * specs["setup_kw"]
        m_idle_kwh = (m_idle_time / 60.0) * specs["idle_kw"]

        total_setup_kwh += m_setup_kwh
        total_idle_kwh += m_idle_kwh

        machine_kpis.append({
            "machine_id": m_id,
            "processing_hours": round(proc_time_m / 60.0, 1),
            "idle_hours": round(m_idle_time / 60.0, 1),
            "processing_kwh": round(m_proc_kwh, 1),
            "setup_kwh": round(m_setup_kwh, 1),
            "idle_kwh": round(m_idle_kwh, 1),
            "total_kwh": round(m_proc_kwh + m_setup_kwh + m_idle_kwh, 1)
        })

    grand_total_kwh = total_proc_kwh + total_setup_kwh + total_idle_kwh
    kwh_per_unit = grand_total_kwh / total_units_produced

    # 3. 15 Dakikalık Yük Profili & Peak kW
    time_steps = list(range(0, makespan_min + 15, 15))
    profile_records = []

    for t in time_steps:
        t_end = t + 15
        total_power_kw = 0.0

        for m_id, specs in machine_specs.items():
            active = schedule_df[
                (schedule_df["machine_id"] == m_id) &
                (schedule_df["start_min"] < t_end) &
                (schedule_df["end_min"] > t)
            ]
            if len(active) > 0:
                total_power_kw += specs["base_kw"]
            else:
                total_power_kw += specs["idle_kw"]

        profile_records.append({
            "time_min": t,
            "time_hour": round(t / 60.0, 2),
            "total_load_kw": round(total_power_kw, 2)
        })

    profile_df = pd.DataFrame(profile_records)
    peak_kw = profile_df["total_load_kw"].max()

    kpi_summary = {
        "makespan_hours": round(makespan_min / 60.0, 1),
        "total_units_produced": int(total_units_produced),
        "processing_kwh": round(total_proc_kwh, 1),
        "setup_kwh": round(total_setup_kwh, 1),
        "idle_kwh": round(total_idle_kwh, 1),
        "grand_total_kwh": round(grand_total_kwh, 1),
        "kwh_per_unit": round(kwh_per_unit, 3),
        "peak_load_kw": round(peak_kw, 2)
    }

    print("=" * 80)
    print("             AŞAMA 7A: ENERJİ ANALİTİĞİ VE YÜK PROFİLİ RAPORU             ")
    print("=" * 80)
    print(f"Toplam Üretim Miktarı     : {kpi_summary['total_units_produced']:,} adet")
    print(f"Toplam Enerji Tüketimi    : {kpi_summary['grand_total_kwh']:,} kWh")
    print(f"  - İşlem (Processing)    : {kpi_summary['processing_kwh']:,} kWh (%{kpi_summary['processing_kwh']/grand_total_kwh*100:.1f})")
    print(f"  - Hazırlık (Setup)      : {kpi_summary['setup_kwh']:,} kWh (%{kpi_summary['setup_kwh']/grand_total_kwh*100:.1f})")
    print(f"  - Boşta Bekleme (Idle)  : {kpi_summary['idle_kwh']:,} kWh (%{kpi_summary['idle_kwh']/grand_total_kwh*100:.1f})")
    print(f"Birim Enerji Tüketimi     : {kpi_summary['kwh_per_unit']} kWh/adet")
    print(f"Tepe Güç Çekişi (Peak kW) : {kpi_summary['peak_load_kw']} kW")
    print("-" * 80)
    print("MAKİNE BAZLI ENERJİ AYRIŞIMI:")
    print(pd.DataFrame(machine_kpis).to_string(index=False))
    print("=" * 80)

    os.makedirs(os.path.dirname(OUTPUT_ENERGY_KPI_PATH), exist_ok=True)
    pd.DataFrame([kpi_summary]).to_csv(OUTPUT_ENERGY_KPI_PATH, index=False)
    profile_df.to_csv(OUTPUT_PROFILE_PATH, index=False)

    conn = sqlite3.connect(DB_PATH)
    pd.DataFrame([kpi_summary]).to_sql("energy_kpis", conn, index=False, if_exists="replace")
    pd.DataFrame(machine_kpis).to_sql("energy_machine_kpis", conn, index=False, if_exists="replace")
    profile_df.to_sql("energy_profile_15min", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Enerji KPI'ları Kaydedildi: {OUTPUT_ENERGY_KPI_PATH}")
    print(f"[OK] 15 Dakikalık Yük Profili Kaydedildi: {OUTPUT_PROFILE_PATH}")
    print(f"[OK] SQLite 'energy_kpis' ve 'energy_profile_15min' tabloları güncellendi.")

if __name__ == "__main__":
    compute_energy_analytics()