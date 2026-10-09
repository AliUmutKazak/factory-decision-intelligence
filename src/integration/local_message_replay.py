"""Read-only G5-T replay of locally delivered B2MML MES actuals."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from lxml import etree

from src.contracts.b2mml import mes_from_xml, mes_to_xml

SCOPE = "LOCAL_SYNTHETIC_B2MML_DELIVERY_REPLAY_NO_RUNTIME_WRITES"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _reject(report: dict[str, Any], code: str, index: int | None, detail: str) -> dict[str, Any]:
    report["status"] = "REJECTED"
    report["issue"] = {"code": code, "message_index": index, "detail": detail}
    report["accepted_actuals"] = []
    return report


def replay_local_messages(manifest_path: str | Path) -> dict[str, Any]:
    """Validate, deduplicate and order synthetic local deliveries without persistence."""
    path = Path(manifest_path)
    raw = path.read_bytes()
    report: dict[str, Any] = {
        "status": "REJECTED",
        "scope": SCOPE,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "deliveries": [],
        "accepted_actuals": [],
    }
    try:
        manifest = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        return _reject(report, "invalid_manifest", None, str(exc))
    if not isinstance(manifest, dict) or manifest.get("source_type") != "SYNTHETIC":
        return _reject(report, "invalid_manifest", None, "source_type must be SYNTHETIC")
    if not isinstance(manifest.get("lot_id"), str) or not manifest["lot_id"].strip():
        return _reject(report, "invalid_manifest", None, "lot_id is required")
    expected = manifest.get("expected_operation_seqs")
    if (
        not isinstance(expected, list)
        or not expected
        or any(not isinstance(op, int) or isinstance(op, bool) or op <= 0 for op in expected)
        or expected != sorted(set(expected))
    ):
        return _reject(
            report, "invalid_manifest", None, "expected_operation_seqs must be sorted unique positive integers"
        )
    lag_limit = manifest.get("max_delivery_lag_min")
    if not _number(lag_limit):
        return _reject(report, "invalid_manifest", None, "max_delivery_lag_min must be declared and nonnegative")
    try:
        origin = datetime.fromisoformat(manifest["origin"])
        if (
            origin.tzinfo is None
            or origin.utcoffset() is None
            or origin.weekday() != 0
            or any((origin.hour, origin.minute, origin.second, origin.microsecond))
        ):
            raise ValueError("origin must be a timezone-aware Monday at midnight")
    except (KeyError, TypeError, ValueError) as exc:
        return _reject(report, "invalid_manifest", None, str(exc))
    messages = manifest.get("messages")
    if not isinstance(messages, list) or not messages:
        return _reject(report, "invalid_manifest", None, "messages must be a nonempty list")

    report["lot_id"] = manifest["lot_id"]
    report["source_type"] = "SYNTHETIC"
    report["expected_operation_seqs"] = expected
    report["max_delivery_lag_min"] = lag_limit
    seen_ids: dict[str, str] = {}
    seen_operations: set[int] = set()
    pending: dict[int, Any] = {}
    applied: list[Any] = []
    previous_received = 0.0
    root = path.resolve().parent

    for index, envelope in enumerate(messages):
        if not isinstance(envelope, dict) or set(envelope) != {"message_id", "received_min", "xml_file"}:
            return _reject(report, "invalid_envelope", index, "message_id, received_min and xml_file are required")
        message_id = envelope["message_id"]
        received = envelope["received_min"]
        xml_name = envelope["xml_file"]
        if not isinstance(message_id, str) or not message_id.strip():
            return _reject(report, "invalid_envelope", index, "message_id must be nonempty")
        if not _number(received) or received < previous_received:
            return _reject(report, "invalid_delivery_time", index, "received_min must be finite and nondecreasing")
        previous_received = received
        if not isinstance(xml_name, str) or not xml_name or Path(xml_name).name != xml_name:
            return _reject(report, "invalid_path", index, "xml_file must be a filename in the manifest directory")
        xml_path = (root / xml_name).resolve()
        if xml_path.parent != root or not xml_path.is_file():
            return _reject(report, "invalid_path", index, "XML file is missing or outside the manifest directory")
        xml_bytes = xml_path.read_bytes()
        xml_sha = hashlib.sha256(xml_bytes).hexdigest()
        if message_id in seen_ids:
            if seen_ids[message_id] != xml_sha:
                return _reject(report, "conflicting_duplicate", index, "same message_id has different XML bytes")
            report["deliveries"].append(
                {"message_id": message_id, "action": "DUPLICATE_IGNORED", "xml_sha256": xml_sha}
            )
            continue
        try:
            actual = mes_from_xml(xml_bytes, origin=origin)
            if mes_from_xml(mes_to_xml(actual, origin=origin), origin=origin) != actual:
                raise ValueError("canonical B2MML round-trip changed the actual")
        except (TypeError, ValueError, etree.LxmlError) as exc:
            return _reject(report, "invalid_b2mml", index, str(exc))
        if actual.lot_id != manifest["lot_id"] or actual.operation_seq not in expected:
            return _reject(report, "unexpected_operation", index, "lot or operation is outside the declared manifest")
        if actual.operation_seq in seen_operations:
            return _reject(report, "duplicate_operation", index, "another message_id already reports this operation")
        if received < actual.actual_end_min:
            return _reject(report, "reported_before_completion", index, "delivery precedes actual completion")
        lag = received - actual.actual_end_min
        if lag > lag_limit:
            return _reject(report, "late_delivery", index, f"lag={lag:g} exceeds declared limit={lag_limit:g}")

        seen_ids[message_id] = xml_sha
        seen_operations.add(actual.operation_seq)
        pending[actual.operation_seq] = actual
        released: list[int] = []
        while len(applied) < len(expected) and expected[len(applied)] in pending:
            operation = expected[len(applied)]
            next_actual = pending.pop(operation)
            if applied and next_actual.actual_start_min < applied[-1].actual_end_min:
                return _reject(report, "operation_precedence", index, "next operation starts before prior one ends")
            applied.append(next_actual)
            released.append(operation)
        report["deliveries"].append(
            {
                "message_id": message_id,
                "operation_seq": actual.operation_seq,
                "received_min": received,
                "delivery_lag_min": lag,
                "xml_sha256": xml_sha,
                "action": "RELEASED" if released else "BUFFERED",
                "released_operation_seqs": released,
            }
        )

    if len(applied) != len(expected):
        return _reject(report, "incomplete_delivery", None, "not all expected operations arrived")
    report["status"] = "ACCEPTED"
    report["accepted_actuals"] = [actual.model_dump(mode="json") for actual in applied]
    report["duplicate_messages_ignored"] = sum(item["action"] == "DUPLICATE_IGNORED" for item in report["deliveries"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = replay_local_messages(args.manifest)
    rendered = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.output:
        args.output.write_bytes(rendered)
    else:
        print(rendered.decode("utf-8"), end="")
    return 0 if report["status"] == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
