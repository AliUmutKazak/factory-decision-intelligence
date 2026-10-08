"""
===============================================================================
OPERATIONAL ENERGY SIMULATION & ANALYTICAL ESTIMATION ENGINE
===============================================================================
Metodolojik Kapsam ve Mimari Ayrım (Madde 23):
Bu modüldeki enerji ve yük profili hesaplamaları doğrudan fiziksel sayaçlardan
(SCADA, Smart Meter, Power Meter, PLC) toplanan telemetri verisi DEĞİLDİR.

Mevcut çıktı bir "Operational Energy Simulation / Analytical Estimate"dir:
- CP-SAT detaylı çizelge zaman damgaları (start_min, end_min, duration_min)
- İki bileşenli termo-elektrik yük modeli (Base Machine kW + Variable kWh/unit)
- Makine durum makineleri (Processing, Explicit Setup, Idle, Calendar Off)
kullanılarak 15 dakikalık dilimlerde analitik olarak integralize edilmiştir.

Üretim Dağıtımı (Production Deployment) Entegrasyon Notu:
Gerçek fabrika devreye alımlarında, bu simülasyon profili referans baseline
olarak saklanır; SCADA/IoT edge gateway'lerinden (Modbus TCP / MQTT) gelen
gerçek zamanlı aktif güç (kW) telemetrisi ile karşılaştırılarak enerji sapma
(Energy Variance & OEE-Energy) analizine girdi oluşturur.
===============================================================================
"""

from contextlib import closing
from pathlib import Path

import pandas as pd

from src.config import get_runtime_paths
from src.scheduling.calendar_service import MachineCalendarService
from src.utils.db import get_active_run_id, get_db_connection, persist_run_scoped_dataframe


def load_data(db_path=None, run_id=None):
    active_db_path = db_path or get_runtime_paths()["db_path"]
    conn = get_db_connection(active_db_path)
    if run_id is not None:
        schedule_df = pd.read_sql("SELECT * FROM production_schedule WHERE run_id = ?", conn, params=(str(run_id),))
    else:
        schedule_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    machines_df = pd.read_sql("SELECT * FROM machines", conn)
    routing_df = pd.read_sql("SELECT product_id, operation_seq, machine_id, variable_kwh_per_unit FROM routing", conn)
    conn.close()

    # Routing tablosundaki variable_kwh_per_unit'i operasyon bazında birleştir
    schedule_df = schedule_df.merge(routing_df, on=["product_id", "operation_seq", "machine_id"], how="left")
    schedule_df["kwh_unit"] = schedule_df["variable_kwh_per_unit"].fillna(0.0)

    return schedule_df, machines_df


def load_machine_specs(db_path=None) -> dict:
    active_db_path = db_path or get_runtime_paths()["db_path"]
    conn = get_db_connection(active_db_path)
    df_m = pd.read_sql("SELECT * FROM machines", conn)
    conn.close()

    specs = {}
    for _, row in df_m.iterrows():
        m_id = str(row["machine_id"])
        base_kw = float(row.get("base_power_kw", row.get("power_kw", row.get("base_kw", 0.0))))
        specs[m_id] = {
            "base_kw": base_kw,
            "setup_kw": float(row.get("setup_kw", round(base_kw * 0.45, 2))),
            "idle_kw": float(row.get("idle_kw", round(base_kw * 0.18, 2))),
        }
    return specs


def compute_energy_analytics(
    schedule_df=None, machines_df=None, run_id=None, db_path=None, processed_dir=None, reports_dir=None
):
    runtime = get_runtime_paths()
    active_db_path = db_path or runtime["db_path"]
    processed_dir = Path(processed_dir) if processed_dir is not None else runtime["processed_dir"]
    output_energy_kpi_path = processed_dir / "energy_kpis.csv"
    output_profile_path = processed_dir / "energy_profile_15min.csv"
    if not run_id:
        with closing(get_db_connection(active_db_path)) as run_conn:
            run_id = get_active_run_id(run_conn)

    if schedule_df is None or machines_df is None:
        loaded_sched, loaded_mach = load_data(active_db_path, run_id=run_id)
        if schedule_df is None:
            schedule_df = loaded_sched
        if machines_df is None:
            machines_df = loaded_mach
    machine_specs = load_machine_specs(active_db_path)
    with closing(get_db_connection(active_db_path)) as calendar_conn:
        daily_hours = MachineCalendarService.load_daily_hours(calendar_conn)
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
            "load_factor": 0.0,
        }
        machine_kpis = []
        for m_id in machines_df["machine_id"].unique():
            machine_kpis.append(
                {
                    "machine_id": m_id,
                    "processing_hours": 0.0,
                    "setup_hours": 0.0,
                    "idle_hours": 0.0,
                    "processing_kwh": 0.0,
                    "setup_kwh": 0.0,
                    "idle_kwh": 0.0,
                    "total_kwh": 0.0,
                }
            )

        kpi_df = pd.DataFrame([facility_kpis])
        m_kpi_df = pd.DataFrame(machine_kpis)
        profile_df = pd.DataFrame(columns=["time_min", "time_hour", "interval_min", "total_load_kw"])

        kpi_df["run_id"] = run_id
        m_kpi_df["run_id"] = run_id
        profile_df["run_id"] = run_id

        processed_dir.mkdir(parents=True, exist_ok=True)
        kpi_df.to_csv(output_energy_kpi_path, index=False)
        profile_df.to_csv(output_profile_path, index=False)

        conn = get_db_connection(active_db_path)
        persist_run_scoped_dataframe(conn, "energy_kpis", kpi_df, str(run_id))
        persist_run_scoped_dataframe(conn, "energy_profile_15min", profile_df, str(run_id))
        persist_run_scoped_dataframe(conn, "energy_machine_kpis", m_kpi_df, str(run_id))
        conn.commit()
        conn.close()

        return kpi_df, m_kpi_df, profile_df

    makespan_min = int(schedule_df["end_min"].max())
    makespan_hours = makespan_min / 60.0
    # 3. Madde: batch_qty veri sözleşmesi - Doğrudan canonical production_units kullanımı
    total_units_produced = int(
        schedule_df.sort_values("operation_seq").groupby("lot_id")["production_units"].first().sum()
    )

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
    with closing(get_db_connection(active_db_path)) as conn:
        cap_df = pd.read_sql(
            "SELECT period_week, machine_id, overtime_hours FROM machine_capacity_plan WHERE run_id = ?",
            conn,
            params=(str(run_id),),
        )
    if cap_df.empty:
        raise RuntimeError(f"[ENERGY] machine_capacity_plan bulunamadı for run_id={run_id}.")
    for _, row in cap_df.iterrows():
        weekly_machine_ot_hours[(int(row["period_week"]), str(row["machine_id"]))] = float(row["overtime_hours"])

    step_min = 15
    time_points = list(range(0, makespan_min, step_min))

    # Her makine icin kumulatif sayaclar
    m_proc_kwh = dict.fromkeys(machine_specs, 0.0)
    m_setup_kwh = dict.fromkeys(machine_specs, 0.0)
    m_idle_kwh = dict.fromkeys(machine_specs, 0.0)
    m_proc_min = dict.fromkeys(machine_specs, 0.0)
    m_setup_min = dict.fromkeys(machine_specs, 0.0)
    m_idle_min = dict.fromkeys(machine_specs, 0.0)

    profile_records = []

    for t in time_points:
        actual_interval = min(float(step_min), float(makespan_min - t))
        t_end = t + actual_interval
        total_slice_load_kw = 0.0

        for m_id, specs in machine_specs.items():
            m_sched = schedule_df[schedule_df["machine_id"] == m_id]

            # 1. İşlemde mi? (Interval overlap kontrolü: [start_min, end_min) kesişimi)
            active_proc = m_sched[(m_sched["start_min"] < t_end) & (m_sched["end_min"] > t)]

            processing_min = 0.0
            slice_kwh = 0.0
            for job in active_proc.itertuples():
                overlap = max(0.0, min(t_end, job.end_min) - max(t, job.start_min))
                processing_min += overlap
                energy = overlap / 60 * job.proc_power_kw
                slice_kwh += energy
                m_proc_min[m_id] += overlap
                m_proc_kwh[m_id] += energy
            setup_min = 0.0
            for job in m_sched.to_dict("records"):
                setup_start = job.get("setup_start_min", job["start_min"] - job.get("setup_before_min", 0))
                setup_end = job.get("setup_end_min", job["start_min"])
                setup_min += max(0.0, min(t_end, setup_end) - max(t, setup_start))
            setup_energy = setup_min / 60 * specs["setup_kw"]
            slice_kwh += setup_energy
            m_setup_min[m_id] += setup_min
            m_setup_kwh[m_id] += setup_energy
            opened = MachineCalendarService.open_minutes(
                t, t_end, daily_hours[m_id], weekly_machine_ot_hours.get((1, m_id), 0) > 0
            )
            idle_min = max(0.0, opened - processing_min - setup_min)
            idle_energy = idle_min / 60 * specs["idle_kw"]
            slice_kwh += idle_energy
            m_idle_min[m_id] += idle_min
            m_idle_kwh[m_id] += idle_energy
            slice_load_kw = slice_kwh / (actual_interval / 60)
            total_slice_load_kw += slice_load_kw

        profile_records.append(
            {
                "time_min": t,
                "time_hour": round(t / 60.0, 2),
                "interval_min": actual_interval,
                "total_load_kw": total_slice_load_kw,
            }
        )

    # Makine KPI Tablosunu dogrudan dilim integrallerinden uret
    machine_kpis = []
    total_setup_kwh = 0.0
    total_idle_kwh = 0.0
    total_proc_kwh_integrated = 0.0

    # schedule_df üzerinden kesin analitik değerler
    sched_mach_group = (
        schedule_df.groupby("machine_id")
        .agg({"proc_hours": "sum", "total_proc_energy_kwh": "sum"})
        .to_dict(orient="index")
    )

    for m_id, specs in machine_specs.items():
        actual_proc_kwh = float(sched_mach_group.get(m_id, {}).get("total_proc_energy_kwh", 0.0))
        actual_proc_hours = float(sched_mach_group.get(m_id, {}).get("proc_hours", 0.0))

        setup_kwh_val = float(m_setup_kwh[m_id])
        idle_kwh_val = float(m_idle_kwh[m_id])
        tot_kwh = actual_proc_kwh + setup_kwh_val + idle_kwh_val

        machine_kpis.append(
            {
                "machine_id": m_id,
                "processing_hours": round(actual_proc_hours, 4),
                "setup_hours": round(m_setup_min[m_id] / 60.0, 4),
                "idle_hours": round(m_idle_min[m_id] / 60.0, 4),
                "processing_kwh": round(actual_proc_kwh, 4),
                "setup_kwh": round(setup_kwh_val, 4),
                "idle_kwh": round(idle_kwh_val, 4),
                "total_kwh": round(tot_kwh, 4),
            }
        )

    # Fiziksel kuramsal toplamlar
    total_proc_kwh = sum(m["processing_kwh"] for m in machine_kpis)
    total_setup_kwh = sum(m["setup_kwh"] for m in machine_kpis)
    total_idle_kwh = sum(m["idle_kwh"] for m in machine_kpis)
    grand_total_kwh = round(total_proc_kwh + total_setup_kwh + total_idle_kwh, 4)

    # Denetim Madde 26 & test_6 Mutabakatı: 15-dk profil integrali == grand_total_kwh == sum(machines_total_kwh)
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
        "load_factor": load_factor,
        "data_source": "ANALYTICAL_SIMULATION_ESTIMATE",
        "telemetry_type": "SYNTHETIC_SCHEDULE_DERIVED",
        "power_model": "BASE_PLUS_VARIABLE_PHYSICS",
    }

    print("=" * 85)
    print(" AŞAMA 7A: OPERASYONEL ENERJİ SİMÜLASYONU VE ANALİTİK TAHMİN RAPORU ")
    print(" (Operational Energy Simulation / Analytical Estimate - Schedule Derived) ")
    print("=" * 85)
    print(f"Toplam Üretim Miktarı     : {kpi_summary['total_units_produced']:,} adet")
    print(f"Toplam Enerji Tüketimi    : {kpi_summary['grand_total_kwh']:,} kWh")
    print(
        f"  - İşlem (Processing)    : {kpi_summary['processing_kwh']:,} kWh ({kpi_summary['processing_kwh'] / grand_total_kwh * 100:.1f}%)"
    )
    print(
        f"  - Fiili Hazırlık (Setup): {kpi_summary['setup_kwh']:,} kWh ({kpi_summary['setup_kwh'] / grand_total_kwh * 100:.1f}%)"
    )
    print(
        f"  - Boşta Bekleme (Idle)  : {kpi_summary['idle_kwh']:,} kWh ({kpi_summary['idle_kwh'] / grand_total_kwh * 100:.1f}%)"
    )
    print(f"Birim Enerji Tüketimi     : {kpi_summary['kwh_per_unit']} kWh/adet")
    print(f"Ortalama Yük (Avg Load)   : {kpi_summary['avg_load_kw']} kW")
    print(f"Tepe Yük (Peak Load)      : {kpi_summary['peak_load_kw']} kW")
    print(f"Yük Faktörü (Load Factor) : {kpi_summary['load_factor']}")
    print("-" * 85)
    print("MAKİNE BAZLI ENERJİ AYRIŞIMI:")
    print(pd.DataFrame(machine_kpis).to_string(index=False))
    print("=" * 85)

    # 1. CSV Kayıtları
    processed_dir.mkdir(parents=True, exist_ok=True)
    kpi_df = pd.DataFrame([kpi_summary])
    m_kpi_df = pd.DataFrame(machine_kpis)

    if not run_id:
        try:
            conn_run = get_db_connection(active_db_path)
            cur_run = conn_run.cursor()
            cur_run.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1;")
            row_run = cur_run.fetchone()
            if not row_run:
                cur_run.execute("SELECT run_id FROM pipeline_runs ORDER BY timestamp DESC LIMIT 1;")
                row_run = cur_run.fetchone()
            run_id = row_run[0] if row_run else "RUN-DEFAULT"
            conn_run.close()
        except Exception:
            run_id = "RUN-DEFAULT"

    kpi_df["run_id"] = run_id
    m_kpi_df["run_id"] = run_id
    profile_df["run_id"] = run_id

    # Madde 23: Sentetik simülasyon ve analitik kestirim ayrımı (KPI & Profil)
    kpi_df["data_source"] = "ANALYTICAL_SIMULATION_ESTIMATE"
    profile_df["data_source"] = "ANALYTICAL_SIMULATION_ESTIMATE"

    # Normal calisma CSV kayitlari
    kpi_df.to_csv(output_energy_kpi_path, index=False)
    profile_df.to_csv(output_profile_path, index=False)

    # Normal calisma SQLite veritabani kayitlari
    conn = get_db_connection(active_db_path)
    persist_run_scoped_dataframe(conn, "energy_kpis", kpi_df, str(run_id))
    persist_run_scoped_dataframe(conn, "energy_profile_15min", profile_df, str(run_id))
    persist_run_scoped_dataframe(conn, "energy_machine_kpis", m_kpi_df, str(run_id))
    conn.commit()
    conn.close()

    print(f"[OK] Enerji KPI'lari Kaydedildi: {output_energy_kpi_path}")
    print(f"[OK] 15 Dakikalik Yuk Profili Kaydedildi: {output_profile_path}")
    print("[OK] SQLite 'energy_kpis' ve 'energy_profile_15min' tablolari guncellendi.")
    print("=" * 85)

    return kpi_summary


if __name__ == "__main__":
    compute_energy_analytics()
