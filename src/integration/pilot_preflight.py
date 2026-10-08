"""Read-only G4-T preflight for a narrow, file-based scheduling pilot.

The package is deliberately smaller than the full factory model. It checks
provenance, required columns, identifiers and basic temporal/quantity rules;
it neither writes to the runtime database nor claims factory acceptance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

FILES = {
    "orders": ("order_id", "lot_id", "product_id", "quantity", "due_min"),
    "machines": ("machine_id",),
    "routing": ("product_id", "operation_seq", "machine_id", "duration_min_per_unit"),
    "shifts": ("machine_id", "start_min", "end_min"),
    "current_plan": ("lot_id", "operation_seq", "machine_id", "start_min", "end_min"),
    "actuals": (
        "lot_id",
        "operation_seq",
        "machine_id",
        "actual_start_min",
        "actual_end_min",
        "produced_qty",
        "scrap_qty",
    ),
}
REQUIRED_FILES = frozenset(FILES) - {"actuals"}
SOURCE_TYPES = {"SYNTHETIC", "OPEN", "CUSTOMER"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: str, *, positive: bool = False, integer: bool = False) -> float | int:
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError("must be finite and nonnegative" if not positive else "must be finite and positive")
    if integer:
        if not number.is_integer():
            raise ValueError("must be an integer")
        return int(number)
    return number


def _required(value: str | None, name: str) -> str:
    result = value.strip() if value is not None else ""
    if not result:
        raise ValueError(f"{name} is empty")
    return result


def _validate_row(kind: str, row: dict[str, str]) -> dict[str, Any]:
    item: dict[str, Any] = {name: _required(row[name], name) for name in FILES[kind]}
    for name in ("quantity", "duration_min_per_unit"):
        if name in item:
            item[name] = _number(item[name], positive=True)
    for name in ("due_min", "start_min", "end_min", "actual_start_min", "actual_end_min", "produced_qty", "scrap_qty"):
        if name in item:
            item[name] = _number(item[name])
    if "operation_seq" in item:
        item["operation_seq"] = _number(item["operation_seq"], positive=True, integer=True)
    for start, end in (("start_min", "end_min"), ("actual_start_min", "actual_end_min")):
        if start in item and item[end] <= item[start]:
            raise ValueError(f"{end} must be later than {start}")
    return item


def _read_csv(path: Path, kind: str, reject: Any) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        missing = set(FILES[kind]) - set(columns)
        if missing:
            reject(kind, None, "missing_columns", ", ".join(sorted(missing)))
            return rows
        if len(columns) != len(set(columns)):
            reject(kind, None, "duplicate_columns", "column names must be unique")
            return rows
        for line, row in enumerate(reader, start=2):
            if None in row:
                reject(kind, line, "extra_columns", "more values than headers")
                continue
            try:
                item = _validate_row(kind, row)
                item["_line"] = line
                rows.append(item)
            except (TypeError, ValueError, OverflowError) as exc:
                reject(kind, line, "invalid_value", str(exc))
    return rows


def inspect_pilot_package(manifest_path: str | Path) -> dict[str, Any]:
    """Return a JSON-ready report; no input file or runtime state is modified."""
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    manifest_digest = _sha256(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {
            "status": "REJECTED",
            "manifest_sha256": manifest_digest,
            "files": {},
            "rejections": [{"file": "manifest", "line": None, "code": "invalid_manifest", "detail": str(exc)}],
            "scope": "FILE_PREFLIGHT_ONLY_NO_SOLVE_NO_PUBLICATION",
        }
    rejections: list[dict[str, Any]] = []

    def reject(kind: str, line: int | None, code: str, detail: str) -> None:
        rejections.append({"file": kind, "line": line, "code": code, "detail": detail})

    dataset_id = str(manifest.get("dataset_id", "")).strip()
    if not dataset_id:
        reject("manifest", None, "missing_dataset_id", "dataset_id is required")
    source_type = str(manifest.get("source_type", "")).upper()
    if source_type not in SOURCE_TYPES:
        reject("manifest", None, "invalid_source_type", "expected SYNTHETIC, OPEN or CUSTOMER")
    if source_type == "OPEN" and not (manifest.get("source_ref") and manifest.get("usage_terms")):
        reject("manifest", None, "missing_open_provenance", "source_ref and usage_terms are required")
    if source_type == "CUSTOMER" and not (manifest.get("data_owner") and manifest.get("sharing_basis")):
        reject("manifest", None, "missing_customer_authority", "data_owner and sharing_basis are required")
    quantity_unit = str(manifest.get("quantity_unit", "")).strip()
    if not quantity_unit:
        reject("manifest", None, "missing_quantity_unit", "quantity_unit is required")
    time_unit = str(manifest.get("time_unit", ""))
    if time_unit != "minute":
        reject("manifest", None, "invalid_time_unit", "time_unit must be minute")
    origin = str(manifest.get("origin", ""))
    try:
        parsed_origin = datetime.fromisoformat(origin)
        if parsed_origin.tzinfo is None or parsed_origin.utcoffset() is None:
            raise ValueError("timezone offset is required")
    except ValueError as exc:
        reject("manifest", None, "invalid_origin", str(exc))
    supplied = manifest.get("files", {})
    if not isinstance(supplied, dict):
        supplied = {}
        reject("manifest", None, "invalid_files", "files must be a mapping")
    for unknown in supplied.keys() - FILES.keys():
        reject("manifest", None, "unknown_file_kind", str(unknown))

    data: dict[str, list[dict[str, Any]]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for kind in FILES:
        relative = supplied.get(kind)
        if relative is None:
            if kind in REQUIRED_FILES:
                reject(kind, None, "missing_file", "required file is not listed")
            continue
        if not isinstance(relative, str) or not relative.strip():
            reject(kind, None, "invalid_path", "file path must be a nonempty string")
            continue
        if Path(relative).suffix.lower() != ".csv":
            reject(kind, None, "unsupported_format", "preflight currently accepts CSV only")
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            reject(kind, None, "path_outside_package", "file must remain inside the package")
            continue
        if not path.is_file():
            reject(kind, None, "missing_file", "listed file does not exist")
            continue
        evidence[kind] = {"path": relative, "sha256": _sha256(path), "size_bytes": path.stat().st_size}
        try:
            data[kind] = _read_csv(path, kind, reject)
        except (UnicodeError, csv.Error) as exc:
            reject(kind, None, "invalid_csv", f"expected valid UTF-8 CSV: {exc}")
            data[kind] = []
        evidence[kind]["parsed_rows"] = len(data[kind])
        if kind in REQUIRED_FILES and not data[kind]:
            reject(kind, None, "empty_file", "required file has no accepted rows")

    machines = {row["machine_id"] for row in data.get("machines", [])}
    if len(machines) != len(data.get("machines", [])):
        reject("machines", None, "duplicate_machine", "machine_id must be unique")
    lots: dict[str, str] = {}
    order_ids: set[str] = set()
    for row in data.get("orders", []):
        if row["order_id"] in order_ids:
            reject("orders", row["_line"], "duplicate_order", row["order_id"])
        order_ids.add(row["order_id"])
        if row["lot_id"] in lots:
            reject("orders", row["_line"], "duplicate_lot", row["lot_id"])
        lots[row["lot_id"]] = row["product_id"]

    routing: set[tuple[str, int, str]] = set()
    operations: dict[str, set[int]] = defaultdict(set)
    route_machines: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in data.get("routing", []):
        key = (row["product_id"], row["operation_seq"], row["machine_id"])
        if key in routing:
            reject("routing", row["_line"], "duplicate_route", str(key))
        routing.add(key)
        operations[row["product_id"]].add(row["operation_seq"])
        route_machines[(row["product_id"], row["operation_seq"])].add(row["machine_id"])
        if row["machine_id"] not in machines:
            reject("routing", row["_line"], "unknown_machine", row["machine_id"])
    for key, assigned in route_machines.items():
        if len(assigned) > 1:
            reject(
                "routing",
                None,
                "unsupported_alternative_machine",
                f"{key}: current production routing allows one machine per product/operation",
            )
    for product, sequence in operations.items():
        if sequence != set(range(1, max(sequence) + 1)):
            reject("routing", None, "routing_gap", product)
    for lot, product in lots.items():
        if product not in operations:
            reject("orders", None, "unknown_product_route", lot)

    shifts: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for row in data.get("shifts", []):
        machine = row["machine_id"]
        if machine not in machines:
            reject("shifts", row["_line"], "unknown_machine", machine)
        shifts[machine].append((row["start_min"], row["end_min"], row["_line"]))
    for machine, windows in shifts.items():
        windows.sort()
        for previous, current in zip(windows, windows[1:]):
            if current[0] < previous[1]:
                reject("shifts", current[2], "overlapping_shifts", machine)
    for machine in machines - shifts.keys():
        reject("shifts", None, "machine_without_shift", machine)

    planned: set[tuple[str, int]] = set()
    for row in data.get("current_plan", []):
        lot, op, machine = row["lot_id"], row["operation_seq"], row["machine_id"]
        key = (lot, op)
        if key in planned:
            reject("current_plan", row["_line"], "duplicate_operation", str(key))
        planned.add(key)
        product = lots.get(lot)
        if product is None:
            reject("current_plan", row["_line"], "unknown_lot", lot)
        elif (product, op, machine) not in routing:
            reject("current_plan", row["_line"], "unmapped_operation", str(key))
    actual_keys: set[tuple[str, int]] = set()
    for row in data.get("actuals", []):
        lot, op, machine = row["lot_id"], row["operation_seq"], row["machine_id"]
        key = (lot, op)
        if key in actual_keys:
            reject("actuals", row["_line"], "duplicate_actual", str(key))
        actual_keys.add(key)
        if lot not in lots:
            reject("actuals", row["_line"], "unknown_lot", lot)
        elif (lots[lot], op, machine) not in routing:
            reject("actuals", row["_line"], "unmapped_operation", str((lot, op)))

    return {
        "dataset_id": dataset_id,
        "source_type": source_type,
        "origin": origin,
        "quantity_unit": quantity_unit,
        "time_unit": time_unit,
        "provenance": {
            key: str(manifest[key])
            for key in ("source_ref", "usage_terms", "data_owner", "sharing_basis")
            if key in manifest
        },
        "manifest_sha256": manifest_digest,
        "files": evidence,
        "status": "ACCEPTED" if not rejections else "REJECTED",
        "rejections": rejections,
        "scope": "FILE_PREFLIGHT_ONLY_NO_SOLVE_NO_PUBLICATION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only G4-T pilot CSV preflight")
    parser.add_argument("manifest", type=Path, help="Package manifest.json")
    args = parser.parse_args()
    report = inspect_pilot_package(args.manifest)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
