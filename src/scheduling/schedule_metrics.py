"""Planned schedule KPIs computed from emitted operation rows."""

import math
from typing import NamedTuple

import pandas as pd


class ScheduleKpis(NamedTuple):
    makespan_min: float
    weighted_tardiness_min: float
    total_setup_min: float


def schedule_kpis(schedule: pd.DataFrame) -> ScheduleKpis:
    """Count one priority-weighted tardiness term per lot and every operation setup."""
    required = {"lot_id", "end_min", "due_date_min", "priority_weight", "setup_before_min"}
    if schedule.empty or not required.issubset(schedule.columns) or schedule["lot_id"].isna().any():
        raise RuntimeError("Schedule KPI source has no complete lot schedule")
    numeric = schedule[["end_min", "due_date_min", "priority_weight", "setup_before_min"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if not numeric.map(lambda value: math.isfinite(value) and value >= 0).all().all():
        raise RuntimeError("Schedule KPI source contains invalid time, due date, priority or setup")
    rows = numeric.assign(lot_id=schedule["lot_id"].to_numpy())
    grouped = rows.groupby("lot_id", dropna=False)
    if (grouped["due_date_min"].nunique() != 1).any() or (grouped["priority_weight"].nunique() != 1).any():
        raise RuntimeError("Schedule KPI source has conflicting lot due dates or priorities")
    lots = grouped.agg(
        completion=("end_min", "max"), due=("due_date_min", "first"), weight=("priority_weight", "first")
    )
    tardiness = (lots["completion"] - lots["due"]).clip(lower=0).mul(lots["weight"]).sum()
    return ScheduleKpis(float(rows["end_min"].max()), float(tardiness), float(rows["setup_before_min"].sum()))
