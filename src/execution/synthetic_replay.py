"""G6-T synthetic, single-operation execution event replay.

This laboratory policy does not alter the scheduler or claim a MES contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

EVENT_TYPES = {"START", "PRODUCE", "SCRAP", "INTERRUPT", "RESUME", "COMPLETE"}
SCOPE = "SYNTHETIC_SINGLE_LOT_OPERATION_READ_ONLY"


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _reject(code: str, index: int | None, detail: str) -> dict[str, Any]:
    return {"status": "REJECTED", "scope": SCOPE, "issue": {"code": code, "event_index": index, "detail": detail}}


def replay_execution(case: Any) -> dict[str, Any]:
    """Replay one synthetic lot-operation; return a JSON-ready report or rejection."""
    if not isinstance(case, dict) or case.get("source_type") != "SYNTHETIC":
        return _reject("invalid_source", None, "source_type must be SYNTHETIC")
    if not all(isinstance(case.get(key), str) and case[key].strip() for key in ("lot_id", "machine_id")):
        return _reject("invalid_identity", None, "lot_id and machine_id are required")
    if not _positive_int(case.get("operation_seq")) or not _positive_int(case.get("planned_units")):
        return _reject("invalid_plan", None, "operation_seq and planned_units must be positive integers")
    events = case.get("events")
    if not isinstance(events, list) or not events:
        return _reject("invalid_events", None, "events must be a nonempty list")

    state = "NOT_STARTED"
    good = scrap = last_time = duplicate_count = 0
    seen: dict[str, dict[str, Any]] = {}
    trace: list[dict[str, Any]] = []
    transitions = {
        ("NOT_STARTED", "START"): "RUNNING",
        ("RUNNING", "INTERRUPT"): "INTERRUPTED",
        ("INTERRUPTED", "RESUME"): "RUNNING",
        ("RUNNING", "COMPLETE"): "COMPLETED",
    }

    for index, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != {"event_id", "type", "occurred_min", "quantity"}:
            return _reject("invalid_event", index, "event fields must be event_id, type, occurred_min, quantity")
        event_id = event["event_id"]
        if not isinstance(event_id, str) or not event_id.strip():
            return _reject("invalid_event_id", index, "event_id must be nonempty")
        if event_id in seen:
            previous = seen[event_id]
            if any(type(previous[key]) is not type(event[key]) or previous[key] != event[key] for key in event):
                return _reject("conflicting_duplicate", index, "same event_id has different contents")
            duplicate_count += 1
            continue
        kind = event["type"]
        if not isinstance(kind, str) or kind not in EVENT_TYPES:
            return _reject("unsupported_event", index, f"event type {kind!r} is unsupported")
        at = event["occurred_min"]
        quantity = event["quantity"]
        if not _nonnegative_int(at) or at < last_time:
            return _reject("invalid_event_time", index, "event times must be nonnegative and nondecreasing")
        if not _nonnegative_int(quantity) or (kind in {"PRODUCE", "SCRAP"}) != (quantity > 0):
            return _reject("invalid_quantity", index, "quantity must be positive only for PRODUCE or SCRAP")
        if kind in {"PRODUCE", "SCRAP"}:
            if state != "RUNNING":
                return _reject("invalid_transition", index, f"{kind} requires RUNNING state")
            if good + scrap + quantity > case["planned_units"]:
                return _reject("quantity_exceeds_plan", index, "good plus scrap exceeds planned_units")
            if kind == "PRODUCE":
                good += quantity
            else:
                scrap += quantity
        else:
            next_state = transitions.get((state, kind))
            if next_state is None:
                return _reject("invalid_transition", index, f"{kind} cannot follow {state}")
            if kind == "COMPLETE" and good + scrap != case["planned_units"]:
                return _reject("incomplete_quantity", index, "COMPLETE requires zero remaining units")
            state = next_state
        last_time = at
        seen[event_id] = event.copy()
        trace.append(
            {
                "event_id": event_id,
                "type": kind,
                "occurred_min": at,
                "state": state,
                "good_units": good,
                "scrap_units": scrap,
                "remaining_units": case["planned_units"] - good - scrap,
                "frozen": state in {"RUNNING", "INTERRUPTED"},
            }
        )

    return {
        "status": "ACCEPTED",
        "scope": SCOPE,
        "source_type": "SYNTHETIC",
        "lot_id": case["lot_id"],
        "operation_seq": case["operation_seq"],
        "machine_id": case["machine_id"],
        "planned_units": case["planned_units"],
        "final_state": state,
        "good_units": good,
        "scrap_units": scrap,
        "remaining_units": case["planned_units"] - good - scrap,
        "duplicate_events_ignored": duplicate_count,
        "trace": trace,
    }


def replay_file(path: str | Path) -> dict[str, Any]:
    """Read a case without modifying it and bind the report to its bytes."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        case = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        report = _reject("invalid_json", None, str(exc))
    else:
        report = replay_execution(case)
    report["input_sha256"] = digest
    code_bytes = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    report["implementation_sha256"] = hashlib.sha256(code_bytes).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = replay_file(args.input)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_bytes(rendered.encode("utf-8"))
    else:
        print(rendered, end="")
    return 0 if report["status"] == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
