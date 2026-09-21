import os
import sqlite3
import pandas as pd
import numpy as np
from src.config import PROCESSED_DATA_DIR, DB_PATH

OUTPUT_ENERGY_KPI_PATH = PROCESSED_DATA_DIR / "energy_kpis.csv"
OUTPUT_PROFILE_PATH = PROCESSED_DATA_DIR / "energy_profile_15min.csv"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    schedule_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    machines_df = pd.read_sql("SELECT * FROM machines", conn)
    routing_df = pd.read_sql("SELECT product_id, operation_seq, machine_id, variable_kwh_per_unit FROM routing", conn)
    conn.close()

    # Routing tablosundaki variable_kwh_per_unit'i operasyon bazında birleştir
    schedule_df = schedule_df.merge(
        routing_df,
        on=["product_id", "operation_seq", "machine_id"],
        how="left"
    )
    schedule_df["kwh_unit"] = schedule_df["variable_kwh_per_unit"].fillna(0.0)

    return schedule_df, machines_df

def load_machine_specs() -> dict:
    conn = sqlite3.connect(DB_PATH)
    df_m = pd.read_sql("SELECT * FROM machines", conn)
    conn.close()

    specs = {}
    for _, row in df_m.iterrows():
        m_id = str(row["machine_id"])
        base_kw = float(row.get("base_power_kw", row.get("power_kw", row.get("base_kw", 0.0))))
        specs[m_id] = {
            "base_kw": base_kw,
            "setup_kw": float(row.get("setup_kw", round(base_kw * 0.45, 2))),
            "idle_kw": float(row.get("idle_kw", round(base_kw * 0.18, 2)))
        }
    return specs

def compute_energy_analytics(schedule_df=None, machines_df=None):
    if schedule_df is None or machines_df is None:
        loaded_sched, loaded_mach = load_data()
        if schedule_df is None:
            schedule_df = loaded_sched
        if machines_df is None:
            machines_df = loaded_mach
    machine_specs = load_machine_specs()
    if schedule_df.empty or len(schedule_df) == 0:
        # Madde 12: 0 Uretim durumunda fiziksel sifir enerji dengesi
        facility_kpis = {
            "makespan_hours": 0.0,
            "total_units_produced": 0,
            "processing_kwh": 0.0,
            "setup_kwh": 0.0,
            "idle_kwh": 0.0,
            "grand_total_kwh": 0.0,
            "kwh_per_unit": 0.0,
            "avg_load_kw": 0.0,
            "peak_load_kw": 0.0,
            "load_factor": 0.0
        }
        machine_kpis = []
        for m_id in machines_df["machine_id"].unique():
            machine_kpis.append({
                "machine_id": m_id,
                "processing_hours": 0.0,
                "setup_hours": 0.0,
                "idle_hours": 0.0,
                "processing_kwh": 0.0,
                "setup_kwh": 0.0,
                "idle_kwh": 0.0,
                "total_kwh": 0.0
            })
        kpi_df = pd.DataFrame([facility_kpis])
        m_kpi_df = pd.DataFrame(machine_kpis)
        profile_df = pd.DataFrame(columns=["time_min", "time_hour", "interval_min", "total_load_kw"])
        return kpi_df, m_kpi_df, profile_df

    makespan_min = int(schedule_df["end_min"].max())
    makespan_hours = makespan_min / 60.0
    total_units_produced = schedule_df[schedule_df["operation_seq"] == 1]["batch_qty"].sum()

    # 1. İşlem Enerjisi (Processing Energy) ve Anlık Güç Çekişi (kW)
    schedule_df["proc_hours"] = schedule_df["duration_min"] / 60.0
    schedule_df["base_energy_kwh"] = schedule_df.apply(
        lambda r: r["proc_hours"] * machine_specs[r["machine_id"]]["base_kw"], axis=1
    )
    schedule_df["variable_energy_kwh"] = schedule_df["batch_qty"] * schedule_df["kwh_unit"]
    schedule_df["total_proc_energy_kwh"] = schedule_df["base_energy_kwh"] + schedule_df["variable_energy_kwh"]
    schedule_df["proc_power_kw"] = schedule_df["total_proc_energy_kwh"] / schedule_df["proc_hours"].replace(0, 1.0)

    total_proc_kwh = schedule_df["total_proc_energy_kwh"].sum()

    # 2. Fiili Setup (CP-SAT Çıktısı) ve Boşta Bekleme (Idle) Ayrıştırması
    machine_kpis = []
    total_setup_kwh = 0.0
    total_idle_kwh = 0.0

    for m_id, specs in machine_specs.items():
        m_tasks = schedule_df[schedule_df["machine_id"] == m_id]
        proc_time_m = m_tasks["duration_min"].sum()
        m_proc_kwh = m_tasks["total_proc_energy_kwh"].sum()

        m_setup_time = m_tasks["setup_before_min"].sum() if "setup_before_min" in m_tasks.columns else 0
        m_idle_time = max(0, makespan_min - (proc_time_m + m_setup_time))

        m_setup_kwh = (m_setup_time / 60.0) * specs["setup_kw"]
        m_idle_kwh = (m_idle_time / 60.0) * specs["idle_kw"]
        m_total_kwh = m_proc_kwh + m_setup_kwh + m_idle_kwh

        total_setup_kwh += m_setup_kwh
        total_idle_kwh += m_idle_kwh

        machine_kpis.append({
            "machine_id": m_id,
            "processing_hours": round(proc_time_m / 60.0, 4),
            "setup_hours": round(m_setup_time / 60.0, 4),
            "idle_hours": round(m_idle_time / 60.0, 4),
            "processing_kwh": float(m_proc_kwh),
            "setup_kwh": float(m_setup_kwh),
            "idle_kwh": float(m_idle_kwh),
            "total_kwh": float(m_total_kwh)
        })

    grand_total_kwh = total_proc_kwh + total_setup_kwh + total_idle_kwh
    avg_load_kw = round(grand_total_kwh / makespan_hours, 2) if makespan_hours > 0 else 0.0

                    # 3. 15 Dakikalık Yük Profili Simülasyonu (Exact Boundary-Condition & Float Precision)
    step_min = 15
    time_points = list(range(0, makespan_min, step_min))
    profile_records = []

    for t in time_points:
        actual_interval = min(float(step_min), float(makespan_min - t))
        t_end = t + actual_interval
        total_power_kw = 0.0

        for m_id, specs in machine_specs.items():
            m_tasks = schedule_df[schedule_df["machine_id"] == m_id]

            interval_energy_kw_min = 0.0
            accounted_min = 0.0

            for _, row in m_tasks.iterrows():
                o_start = max(float(t), float(row["start_min"]))
                o_end = min(t_end, float(row["end_min"]))
                if o_end > o_start:
                    dur = o_end - o_start
                    interval_energy_kw_min += dur * float(row["proc_power_kw"])
                    accounted_min += dur

            for _, row in m_tasks.iterrows():
                s_dur = float(row.get("setup_before_min", 0))
                if s_dur > 0:
                    # CP-SAT tarafından kesin olarak takvimlenmiş fiziksel interval
                    s_start = float(row.get("setup_start_min", float(row["start_min"]) - s_dur))
                    s_end = float(row.get("setup_end_min", float(row["start_min"])))
                    o_start = max(float(t), s_start)
                    o_end = min(t_end, s_end)
                    if o_end > o_start:
                        dur = o_end - o_start
                        interval_energy_kw_min += dur * float(specs["setup_kw"])
                        accounted_min += dur

            idle_dur = max(0.0, actual_interval - accounted_min)
            interval_energy_kw_min += idle_dur * float(specs["idle_kw"])

            if actual_interval > 0:
                total_power_kw += interval_energy_kw_min / actual_interval

        profile_records.append({
            "time_min": t,
            "time_hour": round(t / 60.0, 4),
            "interval_min": round(float(actual_interval), 2),
            "total_load_kw": float(total_power_kw)
        })





    profile_df = pd.DataFrame(profile_records)
    raw_peak_kw = profile_df["total_load_kw"].max()
    peak_kw = round(raw_peak_kw, 2)
    load_factor = round(avg_load_kw / peak_kw, 3) if peak_kw > 0 else 1.0

    assert peak_kw >= avg_load_kw, f"Fiziksel Kural İhlali: Peak ({peak_kw} kW) < Avg ({avg_load_kw} kW)"

    kpi_summary = {
        "makespan_hours": round(makespan_hours, 1),
        "total_units_produced": int(total_units_produced),
        "processing_kwh": round(total_proc_kwh, 1),
        "setup_kwh": round(total_setup_kwh, 1),
        "idle_kwh": round(total_idle_kwh, 1),
        "grand_total_kwh": round(grand_total_kwh, 1),
        "kwh_per_unit": round(grand_total_kwh / total_units_produced, 3) if total_units_produced > 0 else 0.0,
        "avg_load_kw": avg_load_kw,
        "peak_load_kw": peak_kw,
        "load_factor": load_factor
    }

    print("=" * 85)
    print("              AŞAMA 7A: ENERJİ ANALİTİĞİ VE YÜK PROFİLİ RAPORU              ")
    print("=" * 85)
    print(f"Toplam Üretim Miktarı     : {kpi_summary['total_units_produced']:,} adet")
    print(f"Toplam Enerji Tüketimi    : {kpi_summary['grand_total_kwh']:,} kWh")
    print(f"  - İşlem (Processing)    : {kpi_summary['processing_kwh']:,} kWh ({kpi_summary['processing_kwh']/grand_total_kwh*100:.1f}%)")
    print(f"  - Fiili Hazırlık (Setup): {kpi_summary['setup_kwh']:,} kWh ({kpi_summary['setup_kwh']/grand_total_kwh*100:.1f}%)")
    print(f"  - Boşta Bekleme (Idle)  : {kpi_summary['idle_kwh']:,} kWh ({kpi_summary['idle_kwh']/grand_total_kwh*100:.1f}%)")
    print(f"Birim Enerji Tüketimi     : {kpi_summary['kwh_per_unit']} kWh/adet")
    print(f"Ortalama Yük (Avg Load)   : {kpi_summary['avg_load_kw']} kW")
    print(f"Tepe Yük (Peak Load)      : {kpi_summary['peak_load_kw']} kW")
    print(f"Yük Faktörü (Load Factor) : {kpi_summary['load_factor']}")
    print("-" * 85)
    print("MAKİNE BAZLI ENERJİ AYRIŞIMI:")
    print(pd.DataFrame(machine_kpis).to_string(index=False))
    print("=" * 85)

    os.makedirs(os.path.dirname(OUTPUT_ENERGY_KPI_PATH), exist_ok=True)
    pd.DataFrame([kpi_summary]).to_csv(OUTPUT_ENERGY_KPI_PATH, index=False)
    profile_df.to_csv(OUTPUT_PROFILE_PATH, index=False)

    kpi_df = pd.DataFrame([kpi_summary])
    m_kpi_df = pd.DataFrame(machine_kpis)

    conn = sqlite3.connect(DB_PATH)
    kpi_df.to_sql("energy_kpis", conn, index=False, if_exists="replace")
    m_kpi_df.to_sql("energy_machine_kpis", conn, index=False, if_exists="replace")
    profile_df.to_sql("energy_profile_15min", conn, index=False, if_exists="replace")
    conn.close()

    print(f"[OK] Enerji KPI'ları Kaydedildi: {OUTPUT_ENERGY_KPI_PATH}")
    print(f"[OK] 15 Dakikalık Yük Profili Kaydedildi: {OUTPUT_PROFILE_PATH}")
    print(f"[OK] SQLite 'energy_kpis' ve 'energy_profile_15min' tabloları güncellendi.")
    print("=" * 85)
    return kpi_df, m_kpi_df, profile_df
if __name__ == "__main__":
    compute_energy_analytics()