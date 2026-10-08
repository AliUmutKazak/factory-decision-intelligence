"""Independent, read-only checks for the G7 synthetic hot-order schedule.

This module does not import the production solver or its constraint builders.
Its scope is quantity, routing, timing, setup and machine occupancy. Calendar,
MRP, overtime and economic optimality need separate checks.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from typing import Any

import pandas as pd

from src.config import PRODUCTION_BATCH_SIZE
from src.contracts.schemas import HotOrderInjection

_REQUIRED = {
    "task_id",
    "lot_id",
    "parent_lot_id",
    "product_id",
    "machine_id",
    "operation_seq",
    "batch_count",
    "batch_size_units",
    "production_units",
    "start_min",
    "end_min",
    "duration_min",
    "setup_before_min",
    "setup_start_min",
    "setup_end_min",
    "release_time_min",
    "due_date_min",
    "priority_weight",
}


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(number) if math.isfinite(number) and number.is_integer() else None


def audit_hot_order_schedule(
    conn: sqlite3.Connection,
    baseline_run_id: str,
    hot_order: HotOrderInjection,
    schedule: pd.DataFrame,
) -> dict[str, Any]:
    """Check one candidate against source inputs without trusting solver metadata."""
    issues: list[dict[str, str]] = []

    def issue(code: str, detail: str) -> None:
        issues.append({"code": code, "detail": detail})

    missing = _REQUIRED - set(schedule.columns)
    if missing:
        issue("MISSING_COLUMNS", ", ".join(sorted(missing)))
        return {"status": "REJECTED", "scope": "G7_HOT_ORDER_CORE_PHYSICS", "issues": issues}
    if schedule.empty:
        issue("EMPTY_SCHEDULE", "no scheduled operations")
        return {"status": "REJECTED", "scope": "G7_HOT_ORDER_CORE_PHYSICS", "issues": issues}

    routes: dict[str, dict[int, tuple[str, float]]] = defaultdict(dict)
    for product, sequence, machine, duration in conn.execute(
        "SELECT product_id, operation_seq, machine_id, processing_time_min FROM routing"
    ):
        routes[str(product)][int(sequence)] = (str(machine), float(duration))
    plan: dict[str, int] = defaultdict(int)
    for product, units in conn.execute(
        "SELECT product_id, planned_units FROM sku_production_plan WHERE run_id = ? AND period_week = 1",
        (baseline_run_id,),
    ):
        plan[str(product)] += int(units)
    plan[hot_order.product_id] += math.ceil(hot_order.quantity / PRODUCTION_BATCH_SIZE) * PRODUCTION_BATCH_SIZE

    machines = {machine for route in routes.values() for machine, _ in route.values()}
    setups: dict[tuple[str, str, str], int] = {}
    for machine, before, after, minutes in conn.execute(
        "SELECT machine_id, from_product, to_product, setup_time_min FROM changeover_matrix ORDER BY rowid"
    ):
        key = (str(before), str(after))
        duration = int(round(float(minutes)))
        if machine in machines:
            setups[(str(machine), *key)] = duration
        else:
            for routed_machine in machines:
                setups.setdefault((routed_machine, *key), duration)

    states = {
        str(machine): str(product)
        for machine, product in conn.execute(
            "SELECT machine_id, last_product_id FROM machine_state_snapshot WHERE run_id = ?",
            (baseline_run_id,),
        )
    }
    if not states:
        states = {
            str(machine): str(product)
            for machine, product in conn.execute("SELECT machine_id, last_product_id FROM machine_state")
        }

    tasks: list[dict[str, Any]] = []
    ids: set[str] = set()
    lot_ops: set[tuple[str, int]] = set()
    for index, raw in enumerate(schedule.to_dict("records")):
        row: dict[str, Any] = {
            key: str(raw[key]) for key in ("task_id", "lot_id", "parent_lot_id", "product_id", "machine_id")
        }
        for key in (
            "operation_seq",
            "batch_count",
            "batch_size_units",
            "production_units",
            "start_min",
            "end_min",
            "duration_min",
            "setup_before_min",
            "setup_start_min",
            "setup_end_min",
            "release_time_min",
            "due_date_min",
            "priority_weight",
        ):
            row[key] = _integer(raw[key])
            if row[key] is None:
                issue("NONINTEGER_VALUE", f"row {index}: {key}={raw[key]!r}")
        if any(
            row[key] is None
            for key in row
            if key not in {"task_id", "lot_id", "parent_lot_id", "product_id", "machine_id"}
        ):
            continue
        if row["task_id"] in ids:
            issue("DUPLICATE_TASK", row["task_id"])
        ids.add(row["task_id"])
        lot_key = (row["lot_id"], row["operation_seq"])
        if lot_key in lot_ops:
            issue("DUPLICATE_LOT_OPERATION", str(lot_key))
        lot_ops.add(lot_key)
        if row["start_min"] < 0 or row["duration_min"] <= 0 or row["end_min"] != row["start_min"] + row["duration_min"]:
            issue("INVALID_INTERVAL", row["task_id"])
        if row["start_min"] < row["release_time_min"]:
            issue("RELEASE_VIOLATION", row["task_id"])
        if (
            row["setup_before_min"] < 0
            or row["setup_end_min"] != row["start_min"]
            or row["setup_start_min"] != row["start_min"] - row["setup_before_min"]
        ):
            issue("SETUP_INTERVAL", row["task_id"])
        if row["batch_count"] <= 0 or row["batch_size_units"] != PRODUCTION_BATCH_SIZE:
            issue("BATCH_CONTRACT", row["task_id"])
        if row["production_units"] != row["batch_count"] * row["batch_size_units"]:
            issue("UNIT_CONSERVATION", row["task_id"])
        route = routes.get(row["product_id"], {}).get(row["operation_seq"])
        if route is None or row["machine_id"] != route[0]:
            issue("ROUTING_MISMATCH", row["task_id"])
        elif row["duration_min"] != round(row["batch_count"] * route[1]):
            issue("DURATION_MISMATCH", row["task_id"])
        tasks.append(row)

    by_lot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_machine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        by_lot[task["lot_id"]].append(task)
        by_machine[task["machine_id"]].append(task)
    actual: dict[str, int] = defaultdict(int)
    for lot, operations in by_lot.items():
        ordered = sorted(operations, key=lambda row: row["operation_seq"])
        product = ordered[0]["product_id"]
        expected_sequences = set(routes.get(product, {}))
        if {row["operation_seq"] for row in ordered} != expected_sequences or len(ordered) != len(expected_sequences):
            issue("INCOMPLETE_ROUTE", lot)
        if any(
            row["product_id"] != product
            or row["production_units"] != ordered[0]["production_units"]
            or row["parent_lot_id"] != ordered[0]["parent_lot_id"]
            or row["due_date_min"] != ordered[0]["due_date_min"]
            or row["priority_weight"] != ordered[0]["priority_weight"]
            for row in ordered
        ):
            issue("LOT_INCONSISTENT", lot)
        for previous, following in zip(ordered, ordered[1:]):
            if following["start_min"] < previous["end_min"]:
                issue("ROUTE_PRECEDENCE", lot)
        actual[product] += ordered[0]["production_units"]
    if dict(actual) != dict(plan):
        issue("PLAN_QUANTITY", f"expected={dict(plan)}, actual={dict(actual)}")

    hot_rows = [row for row in tasks if row["parent_lot_id"] == f"HOT_{hot_order.product_id}"]
    if not hot_rows or any(
        row["product_id"] != hot_order.product_id
        or row["due_date_min"] != hot_order.due_date_min
        or row["priority_weight"] != hot_order.priority_weight
        for row in hot_rows
    ):
        issue("HOT_ORDER_IDENTITY", hot_order.order_id)
    hot_units = sum(
        operations[0]["production_units"]
        for operations in by_lot.values()
        if operations[0]["parent_lot_id"] == f"HOT_{hot_order.product_id}"
    )
    expected_hot_units = math.ceil(hot_order.quantity / PRODUCTION_BATCH_SIZE) * PRODUCTION_BATCH_SIZE
    if hot_units != expected_hot_units:
        issue("HOT_ORDER_QUANTITY", f"expected={expected_hot_units}, actual={hot_units}")
    for machine, operations in by_machine.items():
        if machine not in states:
            issue("MISSING_MACHINE_STATE", machine)
            continue
        previous_product = states[machine]
        previous_end = 0
        for row in sorted(operations, key=lambda item: item["start_min"]):
            expected_setup = setups.get((machine, previous_product, row["product_id"]), 0)
            if row["setup_before_min"] != expected_setup:
                issue("SETUP_DURATION", row["task_id"])
            if row["setup_start_min"] < previous_end:
                issue("MACHINE_OVERLAP", row["task_id"])
            previous_product = row["product_id"]
            previous_end = row["end_min"]

    return {
        "status": "ACCEPTED" if not issues else "REJECTED",
        "scope": "G7_HOT_ORDER_QUANTITY_ROUTING_INTERVAL_SETUP_PRECEDENCE_ONLY",
        "task_count": len(tasks),
        "lot_count": len(by_lot),
        "issues": issues,
    }
