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
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

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


def _validate_row(kind: str, row: dict[str, str | None]) -> dict[str, Any]:
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


def _column_mapping(kind: str, headers: list[str], configured: Any, reject: Any) -> dict[str, str] | None:
    named = [name for name in headers if name]
    if len(named) != len(set(named)):
        reject(kind, None, "duplicate_columns", "column names must be unique")
        return None
    allowed = set(FILES[kind]) | ({"reported_min"} if kind == "actuals" else set())
    if configured is None:
        mapping = {name: name for name in FILES[kind]}
        if kind == "actuals" and "reported_min" in headers:
            mapping["reported_min"] = "reported_min"
    elif not isinstance(configured, dict) or any(
        key not in allowed or not isinstance(source, str) or not source.strip() for key, source in configured.items()
    ):
        reject(kind, None, "invalid_column_map", "use canonical field names mapped to nonempty source headers")
        return None
    else:
        mapping = configured
        if set(FILES[kind]) - mapping.keys() or len(set(mapping.values())) != len(mapping):
            reject(kind, None, "invalid_column_map", "map every required field to a distinct source header")
            return None
    missing = set(mapping.values()) - set(headers)
    if missing:
        reject(kind, None, "missing_columns", ", ".join(sorted(missing)))
        return None
    return mapping


def _append_row(
    kind: str,
    source: dict[str, str | None],
    mapping: dict[str, str],
    line: int,
    rows: list[dict[str, Any]],
    reject: Any,
) -> None:
    try:
        canonical = {name: source[header] for name, header in mapping.items()}
        item = _validate_row(kind, canonical)
        if "reported_min" in canonical:
            item["reported_min"] = _number(_required(canonical["reported_min"], "reported_min"))
        item["_line"] = line
        rows.append(item)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        reject(kind, line, "invalid_value", str(exc))


def _read_csv(path: Path, kind: str, configured: Any, reject: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if any(not column for column in columns):
            reject(kind, None, "empty_column_name", "CSV headers must all be named")
            return rows, {}
        mapping = _column_mapping(kind, columns, configured, reject)
        if mapping is None:
            return rows, {}
        for line, row in enumerate(reader, start=2):
            if None in row:
                reject(kind, line, "extra_columns", "more values than headers")
                continue
            _append_row(kind, row, mapping, line, rows, reject)
    return rows, mapping


def _read_xlsx(
    path: Path, kind: str, sheet_name: str, header_row: int, configured: Any, reject: Any
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    rows: list[dict[str, Any]] = []
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        if sheet_name not in workbook.sheetnames:
            reject(kind, None, "unknown_sheet", sheet_name)
            return rows, {}
        sheet = workbook[sheet_name]
        header_cells = next(sheet.iter_rows(min_row=header_row, max_row=header_row), ())
        if any(cell.data_type == "f" for cell in header_cells):
            reject(kind, header_row, "formula_header", "formula column headers are unsupported")
            return rows, {}
        headers = [str(cell.value).strip() if cell.value is not None else "" for cell in header_cells]
        mapping = _column_mapping(kind, headers, configured, reject)
        if mapping is None:
            return rows, {}
        indices = {header: headers.index(header) for header in mapping.values()}
        for line, cells in enumerate(sheet.iter_rows(min_row=header_row + 1), start=header_row + 1):
            if all(cell.value is None for cell in cells):
                continue
            if any(
                cell.value is not None
                for index, cell in enumerate(cells)
                if index >= len(headers) or not headers[index]
            ):
                reject(kind, line, "unheaded_column", "data appears below an empty header")
                continue
            selected = {name: cells[indices[name]] for name in mapping.values()}
            if any(cell.data_type == "f" for cell in selected.values()):
                reject(kind, line, "formula_cell", "mapped cells must contain values, not formulas")
                continue
            if any(isinstance(cell.value, (bool, date, time)) for cell in selected.values()):
                reject(kind, line, "invalid_value", "boolean/date/time cells require explicit source conversion")
                continue
            source = {name: str(cell.value) if cell.value is not None else None for name, cell in selected.items()}
            _append_row(kind, source, mapping, line, rows, reject)
        return rows, mapping
    finally:
        workbook.close()


def _covered_by_shifts(start: float, end: float, windows: list[tuple[float, float, int]]) -> bool:
    """Require continuous declared availability for one nonpreemptive operation."""
    cursor = start
    for left, right, _ in windows:
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return False


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
    lag_limit = None
    if "max_actual_reporting_lag_min" in manifest:
        try:
            value = manifest["max_actual_reporting_lag_min"]
            if isinstance(value, bool):
                raise ValueError("must be a finite nonnegative number")
            lag_limit = _number(str(value))
        except (TypeError, ValueError, OverflowError) as exc:
            reject("manifest", None, "invalid_actual_lag_limit", str(exc))
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
        entry = supplied.get(kind)
        if entry is None:
            if kind in REQUIRED_FILES:
                reject(kind, None, "missing_file", "required file is not listed")
            continue
        if isinstance(entry, str):
            spec = {"path": entry}
        elif isinstance(entry, dict):
            spec = entry
        else:
            reject(kind, None, "invalid_path", "file entry must be a path or file specification")
            continue
        if spec.keys() - {"path", "sheet", "header_row", "columns"}:
            reject(kind, None, "invalid_file_spec", "unknown file specification field")
            continue
        relative = spec.get("path")
        if not isinstance(relative, str) or not relative.strip():
            reject(kind, None, "invalid_path", "file path must be a nonempty string")
            continue
        suffix = Path(relative).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            reject(kind, None, "unsupported_format", "preflight accepts UTF-8 CSV or XLSX")
            continue
        if suffix == ".xlsx":
            sheet = spec.get("sheet")
            header_row = spec.get("header_row", 1)
            if not isinstance(sheet, str) or not sheet.strip():
                reject(kind, None, "missing_sheet", "XLSX requires an explicit sheet name")
                continue
            if isinstance(header_row, bool) or not isinstance(header_row, int) or header_row < 1:
                reject(kind, None, "invalid_header_row", "header_row must be a positive integer")
                continue
        elif "sheet" in spec or "header_row" in spec:
            reject(kind, None, "invalid_file_spec", "sheet and header_row apply only to XLSX")
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            reject(kind, None, "path_outside_package", "file must remain inside the package")
            continue
        if not path.is_file():
            reject(kind, None, "missing_file", "listed file does not exist")
            continue
        evidence[kind] = {
            "path": relative,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
            "format": suffix[1:],
        }
        if suffix == ".xlsx":
            evidence[kind]["sheet"] = sheet
            evidence[kind]["header_row"] = header_row
        try:
            if suffix == ".csv":
                data[kind], applied = _read_csv(path, kind, spec.get("columns"), reject)
            else:
                data[kind], applied = _read_xlsx(path, kind, sheet, header_row, spec.get("columns"), reject)
            evidence[kind]["columns"] = applied
        except (UnicodeError, csv.Error) as exc:
            reject(kind, None, "invalid_csv", f"expected valid UTF-8 CSV: {exc}")
            data[kind] = []
        except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
            code = "invalid_xlsx" if suffix == ".xlsx" else "invalid_csv"
            reject(kind, None, code, f"cannot read {suffix[1:].upper()} file: {exc}")
            data[kind] = []
        evidence[kind]["parsed_rows"] = len(data[kind])
        if kind in REQUIRED_FILES and not data[kind]:
            reject(kind, None, "empty_file", "required file has no accepted rows")

    machines = {row["machine_id"] for row in data.get("machines", [])}
    if len(machines) != len(data.get("machines", [])):
        reject("machines", None, "duplicate_machine", "machine_id must be unique")
    lots: dict[str, str] = {}
    lot_quantities: dict[str, float] = {}
    order_ids: set[str] = set()
    for row in data.get("orders", []):
        if row["order_id"] in order_ids:
            reject("orders", row["_line"], "duplicate_order", row["order_id"])
        order_ids.add(row["order_id"])
        if row["lot_id"] in lots:
            reject("orders", row["_line"], "duplicate_lot", row["lot_id"])
        lots[row["lot_id"]] = row["product_id"]
        lot_quantities[row["lot_id"]] = row["quantity"]

    routing: set[tuple[str, int, str]] = set()
    route_duration: dict[tuple[str, int, str], float] = {}
    operations: dict[str, set[int]] = defaultdict(set)
    route_machines: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in data.get("routing", []):
        key = (row["product_id"], row["operation_seq"], row["machine_id"])
        if key in routing:
            reject("routing", row["_line"], "duplicate_route", str(key))
        routing.add(key)
        route_duration[key] = row["duration_min_per_unit"]
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
    planned_rows = data.get("current_plan", [])
    for row in planned_rows:
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
        else:
            required_duration = lot_quantities[lot] * route_duration[(product, op, machine)]
            planned_duration = row["end_min"] - row["start_min"]
            if planned_duration < required_duration and not math.isclose(
                planned_duration, required_duration, rel_tol=0, abs_tol=1e-9
            ):
                reject(
                    "current_plan",
                    row["_line"],
                    "planned_duration_shortfall",
                    f"{lot}/op{op}: {planned_duration:g} < {required_duration:g} min",
                )
        if machine in shifts and not _covered_by_shifts(row["start_min"], row["end_min"], shifts[machine]):
            reject("current_plan", row["_line"], "planned_outside_shift", machine)
    planned_by_lot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    planned_by_machine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in planned_rows:
        planned_by_lot[row["lot_id"]].append(row)
        planned_by_machine[row["machine_id"]].append(row)
    for lot, rows in planned_by_lot.items():
        ordered = sorted(rows, key=lambda item: item["operation_seq"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["start_min"] < previous["end_min"]:
                reject("current_plan", current["_line"], "planned_precedence", lot)
    for machine, rows in planned_by_machine.items():
        ordered = sorted(rows, key=lambda item: item["start_min"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["start_min"] < previous["end_min"]:
                reject("current_plan", current["_line"], "planned_machine_overlap", machine)
    expected_plan = {(lot, op) for lot, product in lots.items() for op in operations.get(product, set())}
    missing_plan = sorted(expected_plan - planned)
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
        if lot in lot_quantities:
            accounted = row["produced_qty"] + row["scrap_qty"]
            order_quantity = lot_quantities[lot]
            if accounted > order_quantity and not math.isclose(accounted, order_quantity, rel_tol=0, abs_tol=1e-9):
                reject(
                    "actuals",
                    row["_line"],
                    "actual_quantity_exceeds_order",
                    f"{lot}: {accounted:g} > {order_quantity:g}",
                )

    actual_rows = data.get("actuals", [])
    actual_by_lot: dict[str, list[dict[str, Any]]] = defaultdict(list)
    actual_by_machine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in actual_rows:
        actual_by_lot[row["lot_id"]].append(row)
        actual_by_machine[row["machine_id"]].append(row)
    for lot, rows in actual_by_lot.items():
        ordered = sorted(rows, key=lambda item: item["operation_seq"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["actual_start_min"] < previous["actual_end_min"]:
                reject("actuals", current["_line"], "actual_precedence", lot)
            if "reported_min" in previous and "reported_min" in current:
                if current["reported_min"] < previous["reported_min"]:
                    reject("actuals", current["_line"], "out_of_order_actual_report", lot)
    for machine, rows in actual_by_machine.items():
        ordered = sorted(rows, key=lambda item: item["actual_start_min"])
        for previous, current in zip(ordered, ordered[1:]):
            if current["actual_start_min"] < previous["actual_end_min"]:
                reject("actuals", current["_line"], "actual_machine_overlap", machine)

    reported_rows = [row for row in actual_rows if "reported_min" in row]
    if lag_limit is not None and len(reported_rows) != len(actual_rows):
        reject("actuals", None, "missing_reporting_time", "reported_min is required to assess the declared lag limit")
    observed_lags = []
    for row in reported_rows:
        lag = row["reported_min"] - row["actual_end_min"]
        observed_lags.append(lag)
        if lag < 0:
            reject("actuals", row["_line"], "reported_before_completion", str(row["lot_id"]))
        elif lag_limit is not None and lag > lag_limit:
            reject("actuals", row["_line"], "late_actual_report", f"lag={lag:g}, limit={lag_limit:g}")
    if not actual_rows:
        timing_status = "NO_ACTUALS"
    elif len(reported_rows) != len(actual_rows):
        timing_status = "NO_REPORTING_TIMES"
    elif lag_limit is None:
        timing_status = "NO_DECLARED_LAG_LIMIT"
    else:
        timing_status = "ASSESSED"

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
        "baseline_coverage": {
            "status": "NO_ROUTING" if not expected_plan else "INCOMPLETE" if missing_plan else "COMPLETE",
            "expected_operations": len(expected_plan),
            "planned_operations": len(expected_plan & planned),
            "missing_operations": len(missing_plan),
            "missing_examples": [list(key) for key in missing_plan[:20]],
        },
        "actuals_timing": {
            "status": timing_status,
            "declared_max_reporting_lag_min": lag_limit,
            "max_observed_reporting_lag_min": max(observed_lags) if observed_lags else None,
            "actual_count": len(actual_rows),
        },
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
