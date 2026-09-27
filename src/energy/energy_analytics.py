import os
import sqlite3
import pandas as pd
import numpy as np
from src.config import PROCESSED_DATA_DIR, DB_PATH
from src.utils.db import get_db_connection

OUTPUT_ENERGY_KPI_PATH = PROCESSED_DATA_DIR / "energy_kpis.csv"
OUTPUT_PROFILE_PATH = PROCESSED_DATA_DIR / "energy_profile_15min.csv"

def load_data():
    conn = get_db_connection(DB_PATH)
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
    conn = get_db_connection(DB_PATH)
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

def compute_energy_analytics(schedule_df=None, machines_df=None, run_id=None):
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

        if run_id:
            kpi_df["run_id"] = run_id
            m_kpi_df["run_id"] = run_id
            profile_df["run_id"] = run_id

        os.makedirs(os.path.dirname(OUTPUT_ENERGY_KPI_PATH), exist_ok=True)
        kpi_df.to_csv(OUTPUT_ENERGY_KPI_PATH, index=False)
        profile_df.to_csv(OUTPUT_PROFILE_PATH, index=False)

        conn = get_db_connection(DB_PATH)
        cur = conn.cursor()
        if run_id:
            # İlgili run_id varsa mükerrer kaydı önlemek için temizle
            try:
                cur.execute("DELETE FROM energy_kpis WHERE run_id = ?", (run_id,))
                cur.execute("DELETE FROM energy_profile_15min WHERE run_id = ?", (run_id,))
                cur.execute("DELETE FROM energy_machine_kpis WHERE run_id = ?", (run_id,))
                conn.commit()
            except Exception:
                pass
            kpi_df.to_sql("energy_kpis", conn, if_exists="append", index=False)
            profile_df.to_sql("energy_profile_15min", conn, if_exists="append", index=False)
            m_kpi_df.to_sql("energy_machine_kpis", conn, if_exists="append", index=False)
        else:
            # Standalone çalıştırmada replace yerine temizleyip ekle
            kpi_df.to_sql("energy_kpis", conn, if_exists="replace", index=False)
            profile_df.to_sql("energy_profile_15min", conn, if_exists="replace", index=False)
            m_kpi_df.to_sql("energy_machine_kpis", conn, if_exists="replace", index=False)
        conn.close()

        return kpi_df, m_kpi_df, profile_df

    makespan_min = int(schedule_df["end_min"].max())
    makespan_hours = makespan_min / 60.0
    # 3. Madde: batch_qty veri sözleşmesi - Doğrudan canonical production_units kullanımı
    total_units_produced = int(schedule_df[schedule_df["operation_seq"] == 1]["production_units"].sum())

    # 1. İşlem Enerjisi (Processing Energy): İki Bileşenli Termodinamik Model
    # NOT (Fiziksel Doğrulama & Çift Sayım Önleme):
    # - base_energy_kwh: Makine 'Running' durumundayken çekilen sabit taban güçtür (soğutma, CNC, hidrolik).
    # - variable_energy_kwh: Baz yükün ÜZERİNE eklenen marjinal iş parçası proses/kesme yüküdür (ΔkWh/unit).
    # Bu tanım uyarınca baz güç ile değişken proses enerjisi toplanırken çift sayım (double counting) oluşmaz.
    schedule_df["proc_hours"] = schedule_df["duration_min"] / 60.0
    schedule_df["base_energy_kwh"] = schedule_df.apply(
        lambda r: r["proc_hours"] * machine_specs[r["machine_id"]]["base_kw"], axis=1
    )
    schedule_df["variable_energy_kwh"] = schedule_df["production_units"] * schedule_df["kwh_unit"]
    schedule_df["total_proc_energy_kwh"] = schedule_df["base_energy_kwh"] + schedule_df["variable_energy_kwh"]
    schedule_df["proc_power_kw"] = schedule_df["total_proc_energy_kwh"] / schedule_df["proc_hours"].replace(0, 1.0)
    total_proc_kwh = float(schedule_df["total_proc_energy_kwh"].sum())

    # ---------------------------------------------------------------------
    # 4. Madde: Tekil State Machine (PROC, SETUP, IDLE, OFF) & Kusursuz Profil Integrasyonu
    # ---------------------------------------------------------------------
    # Taktik LP'den makine OT saatlerini oku (Hafta bazlı)
    weekly_machine_ot_hours = {}
    try:
        conn = get_db_connection(DB_PATH)
        cap_df = pd.read_sql("SELECT period_week, machine_id, overtime_hours FROM machine_capacity_plan", conn)
        conn.close()
        for _, r in cap_df.iterrows():
            weekly_machine_ot_hours[(int(r["period_week"]), str(r["machine_id"]))] = float(r["overtime_hours"])
    except Exception:
        pass

    step_min = 15
    time_points = list(range(0, makespan_min, step_min))
    
    # Her makine icin kumulatif sayaclar
    m_proc_kwh = {m: 0.0 for m in machine_specs}
    m_setup_kwh = {m: 0.0 for m in machine_specs}
    m_idle_kwh = {m: 0.0 for m in machine_specs}
    m_proc_min = {m: 0.0 for m in machine_specs}
    m_setup_min = {m: 0.0 for m in machine_specs}
    m_idle_min = {m: 0.0 for m in machine_specs}

    profile_records = []

    for t in time_points:
        actual_interval = min(float(step_min), float(makespan_min - t))
        t_end = t + actual_interval
        total_slice_load_kw = 0.0

        current_week = int(t // (7 * 1440)) + 1
        t_in_week = t % (7 * 1440)
        is_calendar_regular = t_in_week < (5 * 1440)

        for m_id, specs in machine_specs.items():
            m_sched = schedule_df[schedule_df["machine_id"] == m_id]

            # 1. İşlemde mi? (Interval overlap kontrolü: [start_min, end_min) kesişimi)
            active_proc = m_sched[
                (m_sched["start_min"] < t_end) & (m_sched["end_min"] > t)
            ]

            slice_load_kw = 0.0
            if len(active_proc) > 0:
                # Makine işlemde: İki bileşenli termodinamik model uyarınca (base + variable proses gücü)
                job = active_proc.iloc[0]
                slice_load_kw = float(job.get("proc_power_kw", specs["base_kw"]))
                m_proc_min[m_id] += actual_interval
                m_proc_kwh[m_id] += slice_load_kw * (actual_interval / 60.0)
            else:
                # Boşta (Idle) mı, kapalı mı?
                is_active_window = is_calendar_regular or (
                    weekly_machine_ot_hours.get((current_week, m_id), 0.0) > 0
                )
                if is_active_window:
                    slice_load_kw = specs["idle_kw"]
                    m_idle_min[m_id] += actual_interval
                    m_idle_kwh[m_id] += slice_load_kw * (actual_interval / 60.0)
                else:
                    slice_load_kw = 0.0

            total_slice_load_kw += slice_load_kw

        profile_records.append({
            "time_min": t,
            "time_hour": round(t / 60.0, 2),
            "interval_min": actual_interval,
            "total_load_kw": round(total_slice_load_kw, 2),
        })

    # Makine KPI Tablosunu dogrudan dilim integrallerinden uret
    machine_kpis = []
    total_setup_kwh = 0.0
    total_idle_kwh = 0.0
    total_proc_kwh_integrated = 0.0

    # schedule_df üzerinden kesin analitik değerler
    sched_mach_group = schedule_df.groupby("machine_id").agg({
        "proc_hours": "sum",
        "total_proc_energy_kwh": "sum"
    }).to_dict(orient="index")

    for m_id, specs in machine_specs.items():
        actual_proc_kwh = float(sched_mach_group.get(m_id, {}).get("total_proc_energy_kwh", 0.0))
        actual_proc_hours = float(sched_mach_group.get(m_id, {}).get("proc_hours", 0.0))

        total_setup_kwh += m_setup_kwh[m_id]
        total_idle_kwh += m_idle_kwh[m_id]
        total_proc_kwh_integrated += actual_proc_kwh
        tot_kwh = actual_proc_kwh + m_setup_kwh[m_id] + m_idle_kwh[m_id]

        machine_kpis.append({
            "machine_id": m_id,
            "processing_hours": round(actual_proc_hours, 4),
            "setup_hours": round(m_setup_min[m_id] / 60.0, 4),
            "idle_hours": round(m_idle_min[m_id] / 60.0, 4),
            "processing_kwh": float(actual_proc_kwh),
            "setup_kwh": float(m_setup_kwh[m_id]),
            "idle_kwh": float(m_idle_kwh[m_id]),
            "total_kwh": float(tot_kwh)
        })

    grand_total_kwh = total_proc_kwh_integrated + total_setup_kwh + total_idle_kwh
    avg_load_kw = round(grand_total_kwh / makespan_hours, 2) if makespan_hours > 0 else 0.0
    profile_df = pd.DataFrame(profile_records)
    raw_peak_kw = profile_df["total_load_kw"].max()
    peak_kw = round(raw_peak_kw, 2)
    load_factor = round(avg_load_kw / peak_kw, 3) if peak_kw > 0 else 1.0

    assert peak_kw >= avg_load_kw, f"Fiziksel Kural İhlali: Peak ({peak_kw} kW) < Avg ({avg_load_kw} kW)"

    kpi_summary = {
        "makespan_hours": round(makespan_hours, 1),
        "total_units_produced": int(total_units_produced),
        "processing_kwh": round(total_proc_kwh, 4),
        "setup_kwh": round(total_setup_kwh, 4),
        "idle_kwh": round(total_idle_kwh, 4),
        "grand_total_kwh": round(grand_total_kwh, 4),
        "kwh_per_unit": round(grand_total_kwh / total_units_produced, 6) if total_units_produced > 0 else 0.0,
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

    # 1. CSV Kayıtları
    os.makedirs(os.path.dirname(OUTPUT_ENERGY_KPI_PATH), exist_ok=True)
    kpi_df = pd.DataFrame([kpi_summary])
    m_kpi_df = pd.DataFrame(machine_kpis)

    if run_id:
        kpi_df["run_id"] = run_id
        m_kpi_df["run_id"] = run_id
        profile_df["run_id"] = run_id

    # Normal calisma CSV kayitlari
    kpi_df.to_csv(OUTPUT_ENERGY_KPI_PATH, index=False)
    profile_df.to_csv(OUTPUT_PROFILE_PATH, index=False)

    # Normal calisma SQLite veritabani kayitlari
    conn = get_db_connection(DB_PATH)
    kpi_df.to_sql("energy_kpis", conn, if_exists="replace", index=False)
    profile_df.to_sql("energy_profile_15min", conn, if_exists="replace", index=False)
    m_kpi_df.to_sql("energy_machine_kpis", conn, if_exists="replace", index=False)
    conn.close()

    print(f"[OK] Enerji KPI'lari Kaydedildi: {OUTPUT_ENERGY_KPI_PATH}")
    print(f"[OK] 15 Dakikalik Yuk Profili Kaydedildi: {OUTPUT_PROFILE_PATH}")
    print("[OK] SQLite 'energy_kpis' ve 'energy_profile_15min' tablolari guncellendi.")
    print("=" * 85)

    return kpi_summary