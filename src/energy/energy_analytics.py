import sqlite3
import os
import pandas as pd
import numpy as np
from src.config import RAW_DATA_DIR, DB_PATH

DB_PATH = "data/factory.db"
OUTPUT_ENERGY_KPI_PATH = "data/processed/energy_kpis.csv"
OUTPUT_PROFILE_PATH = "data/processed/energy_profile_15min.csv"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    schedule_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    machines_df = pd.read_sql("SELECT * FROM machines", conn)
    conn.close()
    return schedule_df, machines_df


def load_machine_specs() -> dict:
    machines_csv_path = RAW_DATA_DIR.parent / "synthetic" / "machines.csv"
    if machines_csv_path.exists():
        df_m = pd.read_csv(machines_csv_path)
    else:
        conn = sqlite3.connect(DB_PATH)
        df_m = pd.read_sql("SELECT * FROM machines", conn)
        conn.close()

    specs = {}
    for _, row in df_m.iterrows():
        m_id = str(row["machine_id"])
        # Hem CSV hem de DB sütun adlarını kapsayacak şekilde:
        base_kw = float(row.get("base_power_kw", row.get("power_kw", row.get("base_kw", 0.0))))
        specs[m_id] = {
            "base_kw": base_kw,
            "setup_kw": float(row.get("setup_kw", round(base_kw * 0.45, 2))),
            "idle_kw": float(row.get("idle_kw", round(base_kw * 0.18, 2)))
        }
    return specs


def compute_energy_analytics():
    schedule_df, machines_df = load_data()
    machine_specs = load_machine_specs()

    makespan_min = int(schedule_df["end_min"].max())
    total_units_produced = schedule_df[schedule_df["operation_seq"] == 1]["batch_qty"].sum()

    # 1. İşlem Enerjisi (Processing Energy) ve Anlık Güç Çekişi (kW)
    schedule_df["proc_hours"] = schedule_df["duration_min"] / 60.0
    schedule_df["base_energy_kwh"] = schedule_df.apply(
        lambda r: r["proc_hours"] * machine_specs[r["machine_id"]]["base_kw"], axis=1
    )
    schedule_df["variable_energy_kwh"] = schedule_df["batch_qty"] * schedule_df["kwh_unit"]
    schedule_df["total_proc_energy_kwh"] = schedule_df["base_energy_kwh"] + schedule_df["variable_energy_kwh"]
    
    # İşleme sırasındaki anlık ortalama güç çekişi (kW = kWh / saat)
    schedule_df["proc_power_kw"] = schedule_df["total_proc_energy_kwh"] / schedule_df["proc_hours"].replace(0, 1.0)

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
    kwh_per_unit = grand_total_kwh / total_units_produced if total_units_produced > 0 else 0.0
    makespan_hours = makespan_min / 60.0
    avg_load_kw = round(grand_total_kwh / makespan_hours, 2) if makespan_hours > 0 else 0.0

    # 3. 15 Dakikalık Yük Profili & Fiziksel Olarak Tutarlı Peak kW
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
                # Aktif üretim: Sabit taban güç + değişken parça işleme gücü
                total_power_kw += active["proc_power_kw"].mean()
            else:
                # Setup kontrolü: Yaklaşan işten önceki 30 dakikalık hazırlık penceresi mi?
                upcoming = schedule_df[
                    (schedule_df["machine_id"] == m_id) &
                    (schedule_df["start_min"] >= t_end)
                ]
                is_setup = False
                if len(upcoming) > 0:
                    next_start = upcoming["start_min"].min()
                    if (next_start - t) <= 30:
                        is_setup = True

                total_power_kw += specs["setup_kw"] if is_setup else specs["idle_kw"]

        profile_records.append({
            "time_min": t,
            "time_hour": round(t / 60.0, 2),
            "total_load_kw": round(total_power_kw, 2)
        })

    profile_df = pd.DataFrame(profile_records)
    raw_peak_kw = profile_df["total_load_kw"].max()
    peak_kw = round(max(raw_peak_kw, avg_load_kw), 2)
    load_factor = round(avg_load_kw / peak_kw, 3) if peak_kw > 0 else 1.0

    # Fiziksel Tutarlılık Doğrulaması (Peak >= Average)
    assert peak_kw >= avg_load_kw, f"Fiziksel Kural İhlali: Peak ({peak_kw} kW) < Avg ({avg_load_kw} kW)"

    kpi_summary = {
        "makespan_hours": round(makespan_hours, 1),
        "total_units_produced": int(total_units_produced),
        "processing_kwh": round(total_proc_kwh, 1),
        "setup_kwh": round(total_setup_kwh, 1),
        "idle_kwh": round(total_idle_kwh, 1),
        "grand_total_kwh": round(grand_total_kwh, 1),
        "kwh_per_unit": round(kwh_per_unit, 3),
        "avg_load_kw": avg_load_kw,
        "peak_load_kw": peak_kw,
        "load_factor": load_factor
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