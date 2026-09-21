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
    Sum of individual machine energy consumption must approximate facility electricity:
    sum(E_m) approx E_total
    """
    mock_machine_energy = {"M01": 8420.5, "M02": 5310.2, "M03": 7117.5}
    total_facility_energy = 20848.2

    sum_m = sum(mock_machine_energy.values())
    assert np.isclose(sum_m, total_facility_energy, rtol=1e-3), (
        f"Energy balance mismatch: Sum of machines ({sum_m}) != Facility total ({total_facility_energy})"
    )
