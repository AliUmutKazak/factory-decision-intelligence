"""Read-only, single-shift file pilot through the production CP-SAT engine.

Only a declared full-order, fixed-route, integer-minute laboratory subset is
mapped. Unsupported WIP, actuals and calendars fail closed rather than being
silently replaced by the sealed synthetic factory's assumptions.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sqlite3
import warnings
from collections import defaultdict
from contextlib import redirect_stdout
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

from src.integration.pilot_preflight import _inspect_pilot_package
from src.scheduling.external_jsp_benchmark import SEALED_REFERENCE_SHA256, _sha256, _source_sha256_lf
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.what_if import NoCloseConnectionWrapper

_MASTER_TABLES = (
    "routing",
    "bom",
    "changeover_matrix",
    "machine_calendar",
    "machine_maintenance",
    "machine_state",
    "machines",
    "products",
    "materials",
)
_RUN_TABLES = ("sku_production_plan", "mrp_plan", "machine_capacity_plan", "machine_state_snapshot")
_RUN_ID = "LAB-FILE-PILOT"


def _integer(value: float, name: str, *, positive: bool = False) -> int:
    if not math.isfinite(float(value)) or not float(value).is_integer() or (positive and value <= 0):
        raise ValueError(f"{name} must be a {'positive ' if positive else ''}integer model minute/unit")
    return int(value)


def _audit_candidate(
    rows: list[dict[str, Any]],
    expected: dict[tuple[str, int], dict[str, Any]],
    shifts: dict[str, tuple[int, int]],
    offset: int,
) -> dict[str, Any]:
    issues: list[str] = []
    found: set[tuple[str, int]] = set()
    by_lot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_machine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (str(row["lot_id"]), int(row["operation_seq"]))
        task = expected.get(key)
        if task is None or key in found:
            issues.append("unknown_or_duplicate_operation")
            continue
        found.add(key)
        start, end = int(row["start_min"]) - offset, int(row["end_min"]) - offset
        machine = str(row["machine_id"])
        if machine != task["machine_id"] or end - start != task["duration_min"]:
            issues.append("route_or_duration_mismatch")
        if machine not in shifts or not (shifts[machine][0] <= start < end <= shifts[machine][1]):
            issues.append("outside_declared_shift")
        canonical = {
            "lot_id": key[0],
            "operation_seq": key[1],
            "machine_id": machine,
            "start_min": start,
            "end_min": end,
        }
        by_lot[key[0]].append(canonical)
        by_machine[machine].append(canonical)
    if found != set(expected):
        issues.append("missing_operations")
    for scheduled in by_lot.values():
        ordered = sorted(scheduled, key=lambda item: item["operation_seq"])
        if any(right["start_min"] < left["end_min"] for left, right in zip(ordered, ordered[1:])):
            issues.append("precedence_violation")
    for scheduled in by_machine.values():
        ordered = sorted(scheduled, key=lambda item: item["start_min"])
        if any(right["start_min"] < left["end_min"] for left, right in zip(ordered, ordered[1:])):
            issues.append("machine_overlap")
    return {
        "status": "ACCEPTED" if not issues else "REJECTED",
        "issues": sorted(set(issues)),
        "rows": [item for scheduled in by_lot.values() for item in scheduled] if not issues else [],
    }


def solve_pilot_file_package(
    manifest_path: str | Path,
    *,
    reference_db_path: str | Path = "artifacts/reference/factory.db",
    expected_reference_sha256: str = SEALED_REFERENCE_SHA256,
    time_limit_seconds: float = 30.0,
) -> dict[str, Any]:
    """Compare a valid declared baseline with one isolated model candidate."""
    if not 0 < time_limit_seconds <= 300:
        raise ValueError("time_limit_seconds must be within (0, 300]")
    preflight, data = _inspect_pilot_package(manifest_path)
    base = {
        "dataset_id": preflight.get("dataset_id"),
        "source_type": preflight.get("source_type"),
        "manifest_sha256": preflight["manifest_sha256"],
        "file_sha256": {name: value["sha256"] for name, value in preflight["files"].items()},
        "preflight_status": preflight["status"],
        "scope": "READ_ONLY_SINGLE_SHIFT_FIXED_ROUTE_LAB_NO_ACTIVE_PUBLICATION_NO_CUSTOMER_KPI",
    }
    reasons: list[str] = []
    if preflight["status"] != "ACCEPTED":
        reasons.append("preflight_rejected")
    if preflight.get("baseline_plan_metrics", {}).get("status") != "ASSESSED":
        reasons.append("full_order_complete_baseline_required")
    if data.get("actuals"):
        reasons.append("actuals_or_wip_not_supported")
    shifts: dict[str, tuple[int, int]] = {}
    shift_pairs: set[tuple[int, int]] = set()
    for row in data.get("shifts", []):
        try:
            pair = (_integer(row["start_min"], "shift start"), _integer(row["end_min"], "shift end", positive=True))
            if row["machine_id"] in shifts or pair[1] > 1440:
                raise ValueError("one shift per machine within 24 hours is required")
            shifts[row["machine_id"]] = pair
            shift_pairs.add(pair)
        except ValueError:
            reasons.append("unsupported_shift_calendar")
    if len(shift_pairs) != 1 or set(shifts) != {row["machine_id"] for row in data.get("machines", [])}:
        reasons.append("one_common_shift_required")
    expected: dict[tuple[str, int], dict[str, Any]] = {}
    tasks: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    try:
        shift_start, shift_end = next(iter(shift_pairs))
        model_start = 1440 - (shift_end - shift_start)
        offset = model_start - shift_start
        routing = {(row["product_id"], row["operation_seq"]): row for row in data["routing"]}
        for order in data["orders"]:
            quantity = _integer(order["quantity"], "order quantity", positive=True)
            due = _integer(order["due_min"], "due date") + offset
            product, lot = order["product_id"], order["lot_id"]
            plan.append(
                {
                    "product_id": product,
                    "lot_id": lot,
                    "due_date_min": due,
                    "priority_weight": 1,
                    "planned_batches": 1,
                    "planned_units": quantity,
                }
            )
            for (route_product, sequence), route in routing.items():
                if route_product != product:
                    continue
                duration = _integer(quantity * route["duration_min_per_unit"], "operation duration", positive=True)
                item = {
                    "task_id": f"{lot}-O{sequence}",
                    "lot_id": lot,
                    "product_id": product,
                    "machine_id": route["machine_id"],
                    "operation_seq": sequence,
                    "duration_min": duration,
                    "due_date_min": due,
                    "priority_weight": 1,
                    "production_units": quantity,
                    "batch_count": 1,
                    "batch_size_units": quantity,
                    "release_time_min": model_start,
                }
                tasks.append(item)
                expected[(lot, sequence)] = item
        if len(expected) != len(tasks):
            reasons.append("duplicate_task_identity")
    except (KeyError, StopIteration, ValueError):
        reasons.append("noninteger_or_unmapped_model_input")
    if reasons:
        return {**base, "status": "UNSUPPORTED", "reasons": sorted(set(reasons)), "candidate": None}

    reference = Path(reference_db_path).resolve()
    reference_sha = _sha256(reference)
    if reference_sha != expected_reference_sha256.lower():
        raise ValueError("reference DB SHA-256 mismatch")
    conn = sqlite3.connect(":memory:")
    try:
        source = sqlite3.connect(f"{reference.as_uri()}?mode=ro", uri=True)
        try:
            source.backup(conn)
        finally:
            source.close()
        for table in (*_MASTER_TABLES, *_RUN_TABLES):
            conn.execute(f"DELETE FROM {table}")
        shift_length = shift_end - shift_start
        for row in data["machines"]:
            machine = row["machine_id"]
            conn.execute(
                "INSERT INTO machines (machine_id, machine_name, base_power_kw, "
                "operating_cost_per_hour, max_daily_hours) VALUES (?, ?, 0, 0, ?)",
                (machine, machine, shift_length / 60),
            )
            conn.execute(
                "INSERT INTO machine_capacity_plan "
                "(period_week, machine_id, regular_capacity_hours, overtime_hours, "
                "total_capacity_hours, utilized_hours, utilization_pct, "
                "shadow_price_usd_per_hr, is_bottleneck, run_id) "
                "VALUES (1, ?, ?, 0, ?, 0, 0, 0, 'NO', ?)",
                (machine, 6 * shift_length / 60, 6 * shift_length / 60, _RUN_ID),
            )
            for day in range(6):
                conn.execute(
                    "INSERT INTO machine_calendar "
                    "(machine_id, day_of_week, shift_id, start_minute, end_minute, "
                    "available_hours, exception_type, is_available) "
                    "VALUES (?, ?, 'SHIFT_REGULAR', ?, 1440, ?, 'REGULAR', 1)",
                    (machine, day, model_start, shift_length / 60),
                )
        for product in {row["product_id"] for row in data["orders"]}:
            conn.execute(
                "INSERT INTO products (product_id, family_id, product_name, unit_sale_price, "
                "holding_cost_per_week, late_penalty_per_day) VALUES (?, 'LAB', ?, 0, 0, 0)",
                (product, product),
            )
        for route in data["routing"]:
            conn.execute(
                "INSERT INTO routing (product_id, operation_seq, machine_id, "
                "processing_time_min, variable_kwh_per_unit) VALUES (?, ?, ?, ?, 0)",
                (route["product_id"], route["operation_seq"], route["machine_id"], route["duration_min_per_unit"]),
            )
        conn.commit()
        try:
            with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
                warnings.filterwarnings(
                    "ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning
                )
                metadata = run_cpsat_scheduling(
                    sku_plan=pd.DataFrame(plan),
                    run_id=_RUN_ID,
                    connection=NoCloseConnectionWrapper(conn),
                    persist_outputs=False,
                    task_override=pd.DataFrame(tasks),
                    policy="THROUGHPUT_MAX",
                    time_limit_seconds=time_limit_seconds,
                )
        except TimeoutError:
            return {
                **base,
                "status": "INCOMPLETE",
                "reasons": ["solver_timeout_without_valid_candidate"],
                "reference_db_sha256": reference_sha,
                "solver_time_limit_seconds": time_limit_seconds,
                "baseline": preflight["baseline_plan_metrics"],
                "candidate": None,
            }
        schedule = pd.read_sql(
            "SELECT lot_id, operation_seq, machine_id, start_min, end_min, setup_before_min, "
            "production_overtime_minutes, setup_overtime_minutes "
            "FROM production_schedule WHERE run_id = ? ORDER BY task_id",
            conn,
            params=(_RUN_ID,),
        )
        audit = _audit_candidate(schedule.to_dict("records"), expected, shifts, offset)
        if metadata.total_setup_min != 0 or (not schedule.empty and (schedule.setup_before_min != 0).any()):
            audit["issues"].append("unexpected_setup")
        if not schedule.empty and (
            (schedule.production_overtime_minutes != 0).any() or (schedule.setup_overtime_minutes != 0).any()
        ):
            audit["issues"].append("unexpected_overtime")
        if audit["issues"]:
            audit["status"] = "REJECTED"
            audit["rows"] = []
        if metadata.status.value not in {"OPTIMAL", "FEASIBLE"} or audit["status"] != "ACCEPTED":
            candidate = {
                "status": "UNASSESSED",
                "solver_status": metadata.status.value,
                "independent_check": audit["status"],
                "issues": audit["issues"],
            }
            status = "INCOMPLETE"
        else:
            due_by_lot = {row["lot_id"]: row["due_min"] for row in data["orders"]}
            completion = {
                lot: max(row["end_min"] for row in audit["rows"] if row["lot_id"] == lot) for lot in due_by_lot
            }
            tardiness = [max(0, completion[lot] - due) for lot, due in due_by_lot.items()]
            candidate = {
                "status": "ASSESSED",
                "solver_status": metadata.status.value,
                "proven_optimal_for_model": metadata.proven_optimal,
                "independent_check": audit["status"],
                "operation_count": len(audit["rows"]),
                "lot_count": len(due_by_lot),
                "late_lots": sum(value > 0 for value in tardiness),
                "total_tardiness_min": sum(tardiness),
                "last_completion_min": max(completion.values()),
                "schedule": sorted(audit["rows"], key=lambda row: (row["start_min"], row["lot_id"])),
            }
            status = "ASSESSED"
        code_root = Path(__file__).resolve().parents[2]
        code_hashes = {
            name: _source_sha256_lf(code_root / name)
            for name in (
                "src/integration/pilot_preflight.py",
                "src/integration/pilot_file_solve.py",
                "src/scheduling/schedule_cpsat.py",
                "src/scheduling/calendar_service.py",
                "src/config.py",
            )
        }
        return {
            **base,
            "status": status,
            "reasons": [] if status == "ASSESSED" else audit["issues"],
            "reference_db_sha256": reference_sha,
            "code_hashes_normalized_lf": code_hashes,
            "solver_version": version("ortools"),
            "solver_time_limit_seconds": time_limit_seconds,
            "model_origin_offset_min": offset,
            "model_policy": "THROUGHPUT_MAX",
            "baseline": preflight["baseline_plan_metrics"],
            "candidate": candidate,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only single-shift G4-T/G8-T file pilot solve")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--reference-db", type=Path, default=Path("artifacts/reference/factory.db"))
    parser.add_argument("--reference-sha256", default=SEALED_REFERENCE_SHA256)
    parser.add_argument("--time-limit", type=float, default=30.0)
    args = parser.parse_args()
    report = solve_pilot_file_package(
        args.manifest,
        reference_db_path=args.reference_db,
        expected_reference_sha256=args.reference_sha256,
        time_limit_seconds=args.time_limit,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "ASSESSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
