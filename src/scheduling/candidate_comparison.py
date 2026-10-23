"""Operation-level comparison of an audited what-if candidate and its baseline."""

from __future__ import annotations

import math

import pandas as pd


def compare_schedule_operations(baseline: pd.DataFrame, candidate: pd.DataFrame) -> dict:
    required = {"task_id", "lot_id", "machine_id", "start_min", "end_min"}
    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        if not required <= set(frame.columns) or frame.empty:
            raise ValueError(f"{name} schedule needs nonempty operation rows and {sorted(required)}")
        if frame["task_id"].isna().any() or frame["task_id"].astype(str).duplicated().any():
            raise ValueError(f"{name} schedule has missing or duplicate task IDs")
        if frame[["lot_id", "machine_id"]].isna().any().any():
            raise ValueError(f"{name} schedule has missing operation identity")
        for column in ("start_min", "end_min"):
            values = pd.to_numeric(frame[column], errors="coerce")
            if values.isna().any() or not values.map(math.isfinite).all():
                raise ValueError(f"{name} schedule has invalid {column}")

    old = baseline.set_index(baseline["task_id"].astype(str), drop=False)
    new = candidate.set_index(candidate["task_id"].astype(str), drop=False)
    missing = set(old.index) - set(new.index)
    if missing:
        raise ValueError(f"candidate omitted baseline tasks: {', '.join(sorted(missing)[:5])}")

    changes = []
    total_start_shift = 0.0
    changed_existing = 0
    new_tasks = 0
    for task_id in sorted(new.index):
        row = new.loc[task_id]
        original = old.loc[task_id] if task_id in old.index else None
        if original is None:
            new_tasks += 1
            change_type = "NEW"
            shift = None
        else:
            shift = float(row["start_min"]) - float(original["start_min"])
            total_start_shift += abs(shift)
            moved = (
                shift != 0
                or float(row["end_min"]) != float(original["end_min"])
                or str(row["machine_id"]) != str(original["machine_id"])
            )
            if not moved:
                continue
            changed_existing += 1
            change_type = "CHANGED"
        changes.append(
            {
                "task_id": task_id,
                "lot_id": str(row["lot_id"]),
                "change_type": change_type,
                "baseline_machine_id": str(original["machine_id"]) if original is not None else None,
                "candidate_machine_id": str(row["machine_id"]),
                "baseline_start_min": float(original["start_min"]) if original is not None else None,
                "candidate_start_min": float(row["start_min"]),
                "start_shift_min": shift,
                "baseline_end_min": float(original["end_min"]) if original is not None else None,
                "candidate_end_min": float(row["end_min"]),
            }
        )
    return {
        "baseline_task_count": len(old),
        "candidate_task_count": len(new),
        "changed_existing_task_count": changed_existing,
        "new_task_count": new_tasks,
        "absolute_existing_start_shift_min": total_start_shift,
        "operation_changes": changes,
    }
