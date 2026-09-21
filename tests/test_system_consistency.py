import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from src.config import (
    PROCESSED_DATA_DIR,
    SYNTHETIC_DATA_DIR,
    WEEKLY_MINUTES_PER_MACHINE,
    AGGREGATE_MAX_OVERTIME_HOURS
)

def _load_schedule_data():
    candidate_paths = [
        PROCESSED_DATA_DIR / "production_schedule.csv",
        SYNTHETIC_DATA_DIR / "production_schedule.csv",
        PROCESSED_DATA_DIR / "schedule_tasks.csv",
        SYNTHETIC_DATA_DIR / "schedule_tasks.csv",
    ]
    for p in candidate_paths:
        if p.exists():
            df = pd.read_csv(p)
            if not df.empty:
                return df
    return None

def test_schedule_makespan_energy_consistency():
    """
    Test 1: Schedule makespan <-> Energy horizon alignment.
    Strictly verifies physical alignment between CP-SAT makespan and Energy Analytics KPIs/profiles.
    """
    import pandas as pd
    from pathlib import Path
    
    df = _load_schedule_data()
    if df is None:
        pytest.skip("Production schedule artifact not found.")

    end_col = next((c for c in ["end_min", "end_time", "finish_min", "end"] if c in df.columns), None)
    assert end_col is not None, f"End time column not found in schedule. Available columns: {list(df.columns)}"

    sched_makespan_min = float(df[end_col].max())
    assert sched_makespan_min > 0, f"Schedule makespan must be strictly positive, got {sched_makespan_min}"
    sched_makespan_hr = sched_makespan_min / 60.0

    # 1. Energy KPIs Mutabakati
    kpis_path = Path("data/processed/energy_kpis.csv")
    kpis_df = pd.read_csv(kpis_path)
    
    energy_makespan_hr = float(kpis_df["makespan_hours"].iloc[0])
    diff_hr = abs(sched_makespan_hr - energy_makespan_hr)
    assert diff_hr <= 0.2, (
        f"Fiziksel tutarsizlik: Schedule makespan ({sched_makespan_hr:.2f}h) "
        f"ile Energy makespan ({energy_makespan_hr:.2f}h) uyusmuyor! Fark: {diff_hr:.3f}h"
    )

    # 2. 15-Dakikalik Enerji Profili Horizon Mutabakati
    prof_path = Path("data/processed/energy_profile_15min.csv")
    if prof_path.exists():
        prof_df = pd.read_csv(prof_path)
        if "time_min" in prof_df.columns:
            prof_max_min = float(prof_df["time_min"].max())
            # Enerji profili son 15 dakikalik araligi icerecek sekilde cizelgeyi tam kapsamali
            assert prof_max_min >= sched_makespan_min - 15.0, (
                f"Enerji profili ufku ({prof_max_min} min) "
            )


def test_machine_capacity_consistency():
    """
    Test 2: Machine capacity consistency check (HPP Tactical LP vs Operational CP-SAT).
    Verifies that for Week 1, the scheduled processing hours on each machine
    do not exceed the tactical LP capacity ceiling (total_capacity_hours)
    defined in machine_capacity_plan.csv within numerical tolerance.
    """
    import pandas as pd
    from pathlib import Path

    df = _load_schedule_data()
    if df is None:
        pytest.skip("Production schedule artifact not found.")

    cap_path = Path("data/processed/machine_capacity_plan.csv")
    assert cap_path.exists(), "machine_capacity_plan.csv dosyasi bulunamadi."
    cap_df = pd.read_csv(cap_path)
    w1_cap = cap_df[cap_df["period_week"] == 1]
    assert not w1_cap.empty, "machine_capacity_plan.csv icinde 1. hafta verisi bulunamadi."

    for m_id in sorted(df["machine_id"].unique()):
        m_sched = df[df["machine_id"] == m_id]
        m_cap_row = w1_cap[w1_cap["machine_id"] == m_id]
        assert not m_cap_row.empty, f"{m_id} icin W1 kapasite plani tanimi yok."
        
        lp_allowed_max_hr = float(m_cap_row["total_capacity_hours"].iloc[0])
        # Saf islem suresi (processing hours)
        proc_hours = round(float((m_sched["end_min"] - m_sched["start_min"]).sum() / 60.0), 2)
        
        # LP agrega modeli saf islem suresini kisitlar: proc_hours <= lp_allowed_max_hr (+ 0.05 h tolerans)
        assert proc_hours <= lp_allowed_max_hr + 0.05, (
            f"{m_id} makinesinde operasyonel islem suresi ({proc_hours:.2f}h), "
            f"taktik LP kapasite sinirini ({lp_allowed_max_hr:.2f}h) asiyor."
        )


def test_carbon_energy_balance():
    """
    Test 3: Carbon-energy balance check (First Law consistency).
    Strictly verifies that the sum of individual machine energy consumption
    from energy_machine_kpis equals grand_total_kwh in energy_kpis.
    """
    import sqlite3
    import pandas as pd
    from pathlib import Path
    from src.config import DB_PATH

    # 1. SQLite veritabanindan ya da islenmis CSV artefaktlarindan gercek verileri cek
    if Path(DB_PATH).exists():
        conn = sqlite3.connect(DB_PATH)
        m_kpis = pd.read_sql("SELECT machine_id, total_kwh FROM energy_machine_kpis", conn)
        f_kpis = pd.read_sql("SELECT grand_total_kwh FROM energy_kpis", conn)
        conn.close()
    else:
        m_path = Path("data/processed/energy_machine_kpis.csv")
        f_path = Path("data/processed/energy_kpis.csv")
        assert m_path.exists() and f_path.exists(), "Enerji KPI artefaktlari bulunamadi."
        m_kpis = pd.read_csv(m_path)
        f_kpis = pd.read_csv(f_path)

    assert not m_kpis.empty, "energy_machine_kpis tablosu bos olamaz."
    assert not f_kpis.empty, "energy_kpis tablosu bos olamaz."

    sum_machine_kwh = float(m_kpis["total_kwh"].sum())
    facility_grand_total_kwh = float(f_kpis["grand_total_kwh"].iloc[0])

    # 2. Termodinamik Enerji Korunumu Mutabakati (Sum of machines == Facility total)
    assert np.isclose(sum_machine_kwh, facility_grand_total_kwh, atol=0.5), (
        f"Enerji korunum dengesizligi: Makinelerin toplami ({sum_machine_kwh:.2f} kWh) "
        f"ile Tesis toplami ({facility_grand_total_kwh:.2f} kWh) eslesmiyor."
    )

def test_zero_production_schedule_and_energy_conservation():
    """
    Madde 12 Denetimi:
    Hafta boyunca planlanan parti/adet 0 oldugunda:
    - Hicbir hayalet task olusmamalidir (empty schedule).
    - Makespan, setup ve tuketilen toplam enerji 0.0 kWh olmalidir.
    """
    import pandas as pd
    from src.scheduling.schedule_cpsat import run_cpsat_scheduling
    from src.energy.energy_analytics import compute_energy_analytics
    
    # 1. Tum SKU talepleri sifir olan sentetik plan
    zero_sku_plan = pd.DataFrame([
        {"product_id": f"P{i:02d}", "planned_batches": 0, "planned_units": 0}
        for i in range(1, 6)
    ])
    
    # 2. Scheduler cagirilir
    empty_sched = run_cpsat_scheduling(sku_plan=zero_sku_plan)
    assert empty_sched.empty, "Sifir uretimde schedule bos DataFrame donmelidir."
    assert len(empty_sched) == 0, "Sifir uretimde hayalet task uretilmemelidir."

    # 3. Enerji analitigi bos veriyle cagirildiginda fiziksel sifir korumasi
    synthetic_machines = pd.DataFrame([
        {"machine_id": "CNC_01"},
        {"machine_id": "CNC_02"},
        {"machine_id": "ASSY_01"},
        {"machine_id": "PACK_01"}
    ])
    
    # compute_energy_analytics bos cizelgeyle cagirilir
    kpi_df, m_kpi_df, profile_df = compute_energy_analytics(
        schedule_df=empty_sched, 
        machines_df=synthetic_machines
    )
    
    assert not kpi_df.empty
    assert kpi_df["makespan_hours"].iloc[0] == 0.0
    assert kpi_df["grand_total_kwh"].iloc[0] == 0.0
    assert kpi_df["total_units_produced"].iloc[0] == 0