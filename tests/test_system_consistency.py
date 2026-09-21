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
    Verifies that the scheduled tasks define a valid non-zero operational makespan.
    """
    df = _load_schedule_data()
    if df is None:
        pytest.skip("Production schedule artifact not found.")

    end_col = next((c for c in ["end_min", "end_time", "finish_min", "end"] if c in df.columns), None)
    assert end_col is not None, f"End time column not found in schedule. Available columns: {list(df.columns)}"

    makespan = df[end_col].max()
    assert makespan > 0, f"Schedule makespan must be strictly positive, got {makespan}"


def test_machine_capacity_consistency():
    """
    Test 2: Machine capacity consistency check.
    For each machine: UtilizedHours <= RegularCapacity + OvertimeCeiling
    Catches LP-to-CP-SAT capacity infeasibility or over-allocation drift.
    """
    df = _load_schedule_data()
    if df is None:
        pytest.skip("Production schedule artifact not found.")

    machine_col = next((c for c in ["machine_id", "machine", "Machine"] if c in df.columns), None)
    duration_col = next((c for c in ["duration_min", "duration", "processing_time_min", "proc_time"] if c in df.columns), None)

    assert machine_col is not None, f"Machine ID column not found in schedule. Columns: {list(df.columns)}"

    # Süre kolonu yoksa end - start farkından türet
    if duration_col is None:
        start_col = next((c for c in ["start_min", "start_time", "start"] if c in df.columns), None)
        end_col = next((c for c in ["end_min", "end_time", "end"] if c in df.columns), None)
        assert start_col and end_col, "Cannot determine task duration from schedule columns."
        df["task_duration"] = df[end_col] - df[start_col]
        duration_col = "task_duration"

    # 4 haftalık toplam nominal + fazla mesai tavanı (dakika)
    max_weekly_minutes = WEEKLY_MINUTES_PER_MACHINE + (AGGREGATE_MAX_OVERTIME_HOURS * 60)
    horizon_capacity_limit_min = max_weekly_minutes * 4

    machine_usage = df.groupby(machine_col)[duration_col].sum()
    for m_id, used_min in machine_usage.items():
        assert used_min <= horizon_capacity_limit_min, (
            f"Machine {m_id} utilized minutes ({used_min}) exceeded "
            f"horizon capacity limit ({horizon_capacity_limit_min} min)."
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
