"""Translate canonical operation rows into lot/job analytics without duplicating units."""

import pandas as pd


def schedule_job_summary(schedule: pd.DataFrame, orders: pd.DataFrame | None = None) -> tuple[str, pd.DataFrame]:
    group = next((key for key in ("job_id", "lot_id", "product_id") if key in schedule), None)
    if group is None:
        raise ValueError("Schedule analytics requires job_id, lot_id or product_id.")
    duration = next((key for key in ("duration_min", "duration", "run_duration") if key in schedule), None)
    if duration is None:
        raise ValueError("Schedule analytics requires an explicit processing duration.")
    df = schedule.copy()
    setup = next((key for key in ("setup_before_min", "setup_duration") if key in df), None)
    df["_setup"] = df[setup] if setup else 0.0
    df["_quantity"] = 0.0
    if "production_units" in df:
        # Each routing operation repeats the same physical units.
        first = df.groupby(group)["operation_seq"].transform("min") if "operation_seq" in df else None
        df["_quantity"] = (
            df["production_units"] if first is None else df["production_units"].where(df["operation_seq"] == first, 0)
        )
    summary = (
        df.groupby(group)
        .agg(
            completion_min=("end_min", "max"),
            start_min=("start_min", "min"),
            job_run_min=(duration, "sum"),
            job_setup_min=("_setup", "sum"),
            quantity=("_quantity", "sum"),
        )
        .reset_index()
    )
    for column in ("due_date_min", "customer_class", "priority", "priority_weight"):
        if column in df:
            if df.groupby(group)[column].nunique().gt(1).any():
                raise ValueError(f"Conflicting {column} within schedule {group}.")
            summary = summary.merge(df.groupby(group)[column].first().reset_index(), on=group, validate="one_to_one")
    # Historical demand (order_date/order_qty) is not a dispatch-order mapping.
    # Joining it by product would multiply every lot by every historical date.
    if orders is not None and not orders.empty and group in orders:
        metadata = [col for col in ("due_date_min", "customer_class", "priority", "quantity") if col in orders]
        if metadata:
            if orders[group].duplicated().any():
                raise ValueError(f"Ambiguous order metadata: duplicate {group}.")
            summary = summary.merge(
                orders[[group, *metadata]], on=group, how="left", suffixes=("", "_order"), validate="one_to_one"
            )
            for col in metadata:
                if f"{col}_order" in summary:
                    summary[col] = summary[f"{col}_order"].combine_first(summary[col])
                    summary.drop(columns=f"{col}_order", inplace=True)
    return group, summary


def calendar_overtime_minutes(start: float, end: float) -> float:
    """Actual overlap outside Mon–Sat 08:00–24:00; elapsed makespan is not labor."""
    regular = 0.0
    for day in range(int(start // 1440), int(end // 1440) + 1):
        if day % 7 < 6:
            regular += max(0.0, min(end, day * 1440 + 1440) - max(start, day * 1440 + 480))
    return max(0.0, end - start - regular)
