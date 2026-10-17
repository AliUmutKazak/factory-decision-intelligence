"""Independent, fail-closed checks for reschedule commitments and calendar shape.

This module intentionally does not import the solver or its constraint builder.
It checks the published candidate against the baseline and raw calendar inputs.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

import pandas as pd

from src.contracts.schemas import RescheduleTriggerEvent

_REQUIRED = {
    "task_id",
    "machine_id",
    "start_min",
    "end_min",
    "schedule_state",
    "freeze_until_min",
    "execution_status",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _audit_supported_calendar_shape(conn: sqlite3.Connection, issue: Any) -> None:
    """Reject day-varying shifts the current daily-hours model cannot represent."""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_calendar'"
    ).fetchone() is None:
        return

    machines = [str(row[0]) for row in conn.execute("SELECT machine_id FROM machines")]
    rows = conn.execute(
        "SELECT machine_id, day_of_week, shift_id, start_minute, end_minute, "
        "available_hours, exception_type, is_available "
        "FROM machine_calendar ORDER BY machine_id, day_of_week"
    ).fetchall()
    by_machine_day: dict[tuple[str, int], list[tuple[Any, ...]]] = {}
    for machine, day, shift, start, end, hours, exception, available in rows:
        by_machine_day.setdefault((str(machine), int(day)), []).append(
            (str(shift), start, end, hours, str(exception), int(available))
        )

    for machine in machines:
        signatures = []
        for day in range(6):  # Monday-Saturday; Sunday is independently hard-closed.
            day_rows = by_machine_day.get((machine, day), [])
            if len(day_rows) != 1:
                issue("UNSUPPORTED_DAILY_CALENDAR", f"{machine} day={day} rows={len(day_rows)}")
                continue
            signature = day_rows[0]
            shift, start, end, hours, exception, available = signature
            valid_hours = _number(hours)
            expected_start = int(round((24 - valid_hours) * 60)) if valid_hours is not None else None
            if (
                start is None
                or end is None
                or not isinstance(start, (int, float))
                or not isinstance(end, (int, float))
                or start != expected_start
                or end != 1440
                or valid_hours is None
                or not 0 < valid_hours <= 24
                or available != 1
                or exception.upper() != "REGULAR"
            ):
                issue("UNSUPPORTED_DAILY_CALENDAR", f"{machine} day={day} has an exception or invalid shift")
            signatures.append((shift, start, end, valid_hours, exception, available))
        if signatures and any(signature != signatures[0] for signature in signatures[1:]):
            issue("VARIABLE_DAILY_CALENDAR", machine)


def audit_reschedule_candidate(
    conn: sqlite3.Connection,
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    trigger: RescheduleTriggerEvent,
    completed_tasks: set[Any] | None = None,
) -> dict[str, Any]:
    """Check task identity, frozen commitments, FLEXIBLE bounds, and calendar support."""
    issues: list[dict[str, str]] = []

    def issue(code: str, detail: str) -> None:
        issues.append({"code": code, "detail": detail})

    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        missing = _REQUIRED - set(frame.columns)
        if missing:
            issue("MISSING_COLUMNS", f"{name}: {', '.join(sorted(missing))}")
    if issues:
        return {"status": "REJECTED", "scope": "RESCHEDULE_FREEZE_FLEX_CALENDAR", "issues": issues}

    if baseline.empty or candidate.empty:
        issue("EMPTY_SCHEDULE", "baseline or candidate has no operations")
        return {"status": "REJECTED", "scope": "RESCHEDULE_FREEZE_FLEX_CALENDAR", "issues": issues}

    base = baseline.copy()
    new = candidate.copy()
    base["task_id"] = base["task_id"].astype(str)
    new["task_id"] = new["task_id"].astype(str)
    if base["task_id"].duplicated().any():
        issue("DUPLICATE_BASELINE_TASK", "baseline contains duplicate task IDs")
    if new["task_id"].duplicated().any():
        issue("DUPLICATE_CANDIDATE_TASK", "candidate contains duplicate task IDs")
    base_ids, new_ids = set(base["task_id"]), set(new["task_id"])
    if base_ids != new_ids:
        issue("TASK_SET_MISMATCH", f"missing={sorted(base_ids - new_ids)}, extra={sorted(new_ids - base_ids)}")

    base_by_id = base.set_index("task_id", drop=False)
    new_by_id = new.set_index("task_id", drop=False)
    committed = {str(task_id) for task_id in (completed_tasks or set())}
    cutoff = trigger.current_time_min + trigger.freeze_horizon_min
    flexible_limit = cutoff + trigger.flexible_horizon_min
    shift_limit = trigger.max_flexible_shift_min

    for task_id in sorted(base_ids & new_ids):
        old = base_by_id.loc[task_id]
        current = new_by_id.loc[task_id]
        old_start = _number(old["start_min"])
        old_end = _number(old["end_min"])
        start = _number(current["start_min"])
        end = _number(current["end_min"])
        freeze_until = _number(current["freeze_until_min"])
        if None in (old_start, old_end, start, end, freeze_until) or old_end <= old_start or end <= start:
            issue("INVALID_INTERVAL", task_id)
            continue
        if str(current["machine_id"]) != str(old["machine_id"]):
            issue("ROUTING_CHANGED", task_id)
        if abs((end - start) - (old_end - old_start)) > 1e-6:
            issue("DURATION_CHANGED", task_id)

        old_state = str(old.get("execution_status", "SCHEDULED"))
        old_schedule_state = str(old.get("schedule_state", "FREE"))
        is_frozen = (
            old_start < cutoff
            or old_start <= trigger.current_time_min
            or task_id in committed
            or old_state in {"IN_PROGRESS", "COMPLETED"}
            or old_schedule_state == "FROZEN"
        )
        if is_frozen:
            if (
                str(current["machine_id"]) != str(old["machine_id"])
                or abs(start - old_start) > 1e-6
                or abs(end - old_end) > 1e-6
            ):
                issue("FROZEN_POSITION_CHANGED", task_id)
            if str(current["schedule_state"]) != "FROZEN":
                issue("FROZEN_STATE_MISSING", task_id)
            expected_freeze_until = trigger.current_time_min + trigger.freeze_horizon_min
            if abs(freeze_until - expected_freeze_until) > 1e-6:
                issue("FROZEN_DEADLINE_MISMATCH", task_id)
            continue

        is_flexible = old_start < flexible_limit
        if is_flexible:
            earliest = max(trigger.current_time_min, old_start - shift_limit)
            latest = old_start + shift_limit
            if str(current["machine_id"]) != str(old["machine_id"]):
                issue("FLEXIBLE_MACHINE_CHANGED", task_id)
            if start < earliest - 1e-6 or start > latest + 1e-6:
                issue("FLEXIBLE_START_OUT_OF_BOUNDS", f"{task_id}: allowed=[{earliest},{latest}], actual={start}")
            if str(current["schedule_state"]) != "FLEXIBLE":
                issue("FLEXIBLE_STATE_MISSING", task_id)

    _audit_supported_calendar_shape(conn, issue)
    return {
        "status": "ACCEPTED" if not issues else "REJECTED",
        "scope": "RESCHEDULE_FREEZE_FLEX_CALENDAR",
        "task_count": len(new),
        "issues": issues,
    }
