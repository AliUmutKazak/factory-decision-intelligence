"""Independent, fail-closed checks for reschedule commitments and core physics.

This module intentionally does not import the solver or its constraint builder.
It checks the published candidate against the baseline and raw calendar inputs.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Sequence
from typing import Any

import pandas as pd

from src import config as cfg
from src.contracts.schemas import RescheduleTriggerEvent
from src.scheduling.maintenance import MaintenanceWindow

_SCOPE = "RESCHEDULE_FREEZE_FLEX_CORE_INTERVALS_SETUP_CALENDAR_MAINTENANCE"

_REQUIRED = {
    "task_id",
    "lot_id",
    "product_id",
    "machine_id",
    "operation_seq",
    "start_min",
    "end_min",
    "duration_min",
    "release_time_min",
    "setup_before_min",
    "setup_start_min",
    "setup_end_min",
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
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_calendar'").fetchone() is None:
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
        sunday_rows = by_machine_day.get((machine, 6), [])
        if len(sunday_rows) > 1:
            issue("UNSUPPORTED_SUNDAY_CALENDAR", f"{machine} has {len(sunday_rows)} Sunday calendar rows")
        elif len(sunday_rows) == 1 and sunday_rows[0][5] == 1 and signatures:
            sunday_hours = _number(sunday_rows[0][3])
            if sunday_hours is None or abs(sunday_hours - signatures[0][3]) > 1e-9:
                issue("SUNDAY_HOURS_AFFECT_DAILY_AVERAGE", machine)


def _audit_core_intervals(candidate: pd.DataFrame, issue: Any) -> None:
    """Rebuild task timing, route order and machine occupancy from candidate rows."""
    by_machine: dict[str, list[tuple[float, float, str]]] = {}
    by_lot: dict[str, list[tuple[float, float, float, str]]] = {}
    for raw in candidate.to_dict("records"):
        task_id = str(raw["task_id"])
        values = {
            key: _number(raw[key])
            for key in (
                "operation_seq",
                "start_min",
                "end_min",
                "duration_min",
                "release_time_min",
                "setup_before_min",
                "setup_start_min",
                "setup_end_min",
            )
        }
        if any(value is None for value in values.values()):
            issue("NONNUMERIC_INTERVAL", task_id)
            continue
        start = values["start_min"]
        end = values["end_min"]
        duration = values["duration_min"]
        release = values["release_time_min"]
        setup = values["setup_before_min"]
        setup_start = values["setup_start_min"]
        setup_end = values["setup_end_min"]
        if start < 0 or duration <= 0 or abs(end - start - duration) > 1e-6 or start < release:
            issue("INVALID_TASK_TIMING", task_id)
        if setup < 0 or setup_start < 0 or abs(setup_end - start) > 1e-6 or abs(start - setup_start - setup) > 1e-6:
            issue("INVALID_SETUP_INTERVAL", task_id)
        if values["operation_seq"] < 0 or not values["operation_seq"].is_integer():
            issue("INVALID_OPERATION_SEQUENCE", task_id)
        by_machine.setdefault(str(raw["machine_id"]), []).append((setup_start, end, task_id))
        by_lot.setdefault(str(raw["lot_id"]), []).append((values["operation_seq"], start, end, task_id))

    for machine, operations in by_machine.items():
        previous_end = None
        for occupied_start, end, task_id in sorted(operations):
            if previous_end is not None and occupied_start < previous_end - 1e-6:
                issue("MACHINE_OCCUPANCY_OVERLAP", f"{machine}: {task_id}")
            previous_end = end if previous_end is None else max(previous_end, end)
    for lot, operations in by_lot.items():
        previous_end = None
        previous_sequence = None
        for sequence, start, end, task_id in sorted(operations):
            if previous_sequence is not None and sequence == previous_sequence:
                issue("DUPLICATE_ROUTE_OPERATION", f"{lot}: {sequence}")
            if previous_end is not None and start < previous_end - 1e-6:
                issue("ROUTE_PRECEDENCE", f"{lot}: {task_id}")
            previous_end = end
            previous_sequence = sequence


def _audit_setup_transitions(
    conn: sqlite3.Connection, candidate: pd.DataFrame, baseline_run_id: str | None, issue: Any
) -> None:
    """Recompute each setup from raw changeovers and the baseline machine state."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='changeover_matrix'").fetchone() is None:
        issue("MISSING_CHANGEOVER_MATRIX", "changeover_matrix")
        return

    machines = set(candidate["machine_id"].astype(str))
    setup: dict[tuple[str, str, str], int] = {}
    try:
        rows = conn.execute(
            "SELECT machine_id, from_product, to_product, setup_time_min FROM changeover_matrix ORDER BY rowid"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        issue("INVALID_CHANGEOVER_MATRIX", str(exc))
        return
    for machine, before, after, raw_minutes in rows:
        minutes = _number(raw_minutes)
        if minutes is None or minutes < 0 or not str(before).strip() or not str(after).strip():
            issue("INVALID_CHANGEOVER_ROW", f"{machine}: {before}->{after}={raw_minutes}")
            continue
        duration = int(round(minutes))
        key = (str(before), str(after))
        if machine in machines:
            setup[(str(machine), *key)] = duration
        elif machine == "ALL":
            for routed_machine in machines:
                setup.setdefault((routed_machine, *key), duration)

    states: dict[str, str] = {}
    try:
        if (
            baseline_run_id
            and conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_state_snapshot'"
            ).fetchone()
        ):
            states = {
                str(machine): str(product)
                for machine, product in conn.execute(
                    "SELECT machine_id, last_product_id FROM machine_state_snapshot WHERE run_id = ?",
                    (baseline_run_id,),
                )
            }
        if (
            not states
            and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_state'").fetchone()
        ):
            states = {
                str(machine): str(product)
                for machine, product in conn.execute("SELECT machine_id, last_product_id FROM machine_state")
            }
    except sqlite3.DatabaseError as exc:
        issue("INVALID_INITIAL_MACHINE_STATE", str(exc))
        return
    if not states:
        states = dict(getattr(cfg, "INITIAL_MACHINE_STATE", {}))

    for machine, group in candidate.groupby("machine_id", sort=False):
        previous_product = states.get(str(machine))
        ordered = sorted(
            group.to_dict("records"), key=lambda row: (_number(row["start_min"]) or 0, str(row["task_id"]))
        )
        for row in ordered:
            task_id = str(row["task_id"])
            actual = _number(row["setup_before_min"])
            if actual is None or _number(row["start_min"]) is None:
                continue  # The core interval audit reports malformed timing.
            product = str(row["product_id"])
            expected = setup.get((str(machine), previous_product, product), 0) if previous_product is not None else 0
            if abs(actual - expected) > 1e-6:
                issue("SETUP_TRANSITION_MISMATCH", f"{machine}: {task_id} expected={expected}, actual={actual}")
            previous_product = product


def _audit_maintenance_intervals(
    conn: sqlite3.Connection,
    candidate: pd.DataFrame,
    overrides: Sequence[MaintenanceWindow],
    issue: Any,
) -> None:
    """Check setup and work against raw active windows and event overrides."""
    windows: list[tuple[Any, Any, Any]] = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_maintenance'").fetchone():
        try:
            windows.extend(
                conn.execute(
                    "SELECT machine_id, start_min, end_min FROM machine_maintenance WHERE is_active = 1"
                ).fetchall()
            )
        except sqlite3.DatabaseError as exc:
            issue("INVALID_MAINTENANCE_DATA", str(exc))
    windows.extend((window.machine_id, window.start_min, window.end_min) for window in overrides)

    by_machine: dict[str, list[tuple[float, float]]] = {}
    for machine, raw_start, raw_end in windows:
        start, end = _number(raw_start), _number(raw_end)
        if not str(machine).strip() or start is None or end is None or start < 0 or end <= start:
            issue("INVALID_MAINTENANCE_WINDOW", f"{machine}: {raw_start}..{raw_end}")
            continue
        by_machine.setdefault(str(machine), []).append((start, end))

    for row in candidate.to_dict("records"):
        occupied_start = _number(row["setup_start_min"])
        occupied_end = _number(row["end_min"])
        if occupied_start is None or occupied_end is None:
            continue  # Core interval audit reports malformed task timing.
        for start, end in by_machine.get(str(row["machine_id"]), []):
            if occupied_start < end and start < occupied_end:
                issue("MAINTENANCE_OVERLAP", f"{row['machine_id']}: {row['task_id']} / {start}..{end}")


def audit_reschedule_candidate(
    conn: sqlite3.Connection,
    baseline: pd.DataFrame,
    candidate: pd.DataFrame,
    trigger: RescheduleTriggerEvent,
    completed_tasks: set[Any] | None = None,
    maintenance_overrides: Sequence[MaintenanceWindow] | None = None,
    baseline_run_id: str | None = None,
) -> dict[str, Any]:
    """Check commitments, core intervals, setup transitions, calendar and outages."""
    issues: list[dict[str, str]] = []

    def issue(code: str, detail: str) -> None:
        issues.append({"code": code, "detail": detail})

    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        missing = _REQUIRED - set(frame.columns)
        if missing:
            issue("MISSING_COLUMNS", f"{name}: {', '.join(sorted(missing))}")
    if issues:
        return {"status": "REJECTED", "scope": _SCOPE, "issues": issues}

    if baseline.empty or candidate.empty:
        issue("EMPTY_SCHEDULE", "baseline or candidate has no operations")
        return {"status": "REJECTED", "scope": _SCOPE, "issues": issues}

    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        for column in ("task_id", "lot_id", "product_id", "machine_id"):
            if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
                issue("INVALID_IDENTIFIER", f"{name}: {column}")
    if issues:
        return {"status": "REJECTED", "scope": _SCOPE, "issues": issues}

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
        if any(str(current[column]) != str(old[column]) for column in ("lot_id", "product_id")) or any(
            _number(current[column]) is None
            or _number(old[column]) is None
            or abs(_number(current[column]) - _number(old[column])) > 1e-6
            for column in ("operation_seq", "release_time_min")
        ):
            issue("TASK_INPUT_CHANGED", task_id)
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

    _audit_core_intervals(new, issue)
    _audit_setup_transitions(conn, new, baseline_run_id, issue)
    _audit_supported_calendar_shape(conn, issue)
    _audit_maintenance_intervals(conn, new, maintenance_overrides or (), issue)
    return {
        "status": "ACCEPTED" if not issues else "REJECTED",
        "scope": _SCOPE,
        "task_count": len(new),
        "issues": issues,
    }
