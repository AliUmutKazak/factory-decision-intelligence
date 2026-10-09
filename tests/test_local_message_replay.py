"""G5-T B2MML delivery replay: ordering, idempotency and fail-closed inputs."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from src.contracts.b2mml import mes_to_xml
from src.contracts.schemas import MESActual
from src.integration.local_message_replay import replay_local_messages

EXAMPLE = Path("examples/g5-local-messages")


def package(tmp_path):
    root = tmp_path / "messages"
    shutil.copytree(EXAMPLE, root)
    return root / "manifest.json"


def edit_manifest(path, edit):
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_out_of_order_delivery_is_buffered_and_retry_is_not_counted(tmp_path):
    manifest = package(tmp_path)
    before = {item.name: item.read_bytes() for item in manifest.parent.iterdir()}
    report = replay_local_messages(manifest)
    assert report["status"] == "ACCEPTED"
    assert [item["action"] for item in report["deliveries"]] == ["BUFFERED", "RELEASED", "DUPLICATE_IGNORED"]
    assert report["deliveries"][1]["released_operation_seqs"] == [1, 2]
    assert [item["operation_seq"] for item in report["accepted_actuals"]] == [1, 2]
    assert report["duplicate_messages_ignored"] == 1
    assert report["deliveries"][1]["delivery_lag_min"] == 50
    assert {item.name: item.read_bytes() for item in manifest.parent.iterdir()} == before


def test_conflicting_retry_and_second_message_for_same_operation_fail_closed(tmp_path):
    manifest = package(tmp_path)
    edit_manifest(manifest, lambda data: data["messages"][2].update(xml_file="actual-op1.xml"))
    report = replay_local_messages(manifest)
    assert report["issue"]["code"] == "conflicting_duplicate"
    assert report["accepted_actuals"] == []

    edit_manifest(manifest, lambda data: data["messages"][2].update(message_id="m-other"))
    report = replay_local_messages(manifest)
    assert report["issue"]["code"] == "duplicate_operation"
    assert report["accepted_actuals"] == []


def test_declared_lag_and_missing_predecessor_fail_closed(tmp_path):
    manifest = package(tmp_path)
    edit_manifest(manifest, lambda data: data.update(max_delivery_lag_min=30))
    report = replay_local_messages(manifest)
    assert report["issue"]["code"] == "late_delivery"
    assert report["accepted_actuals"] == []

    edit_manifest(manifest, lambda data: data.update(max_delivery_lag_min=60, messages=data["messages"][:1]))
    report = replay_local_messages(manifest)
    assert report["issue"]["code"] == "incomplete_delivery"
    assert report["accepted_actuals"] == []


def test_invalid_xml_and_untrusted_file_path_are_rejected(tmp_path):
    manifest = package(tmp_path)
    (manifest.parent / "actual-op2.xml").write_bytes(b"<!DOCTYPE x><x/>")
    assert replay_local_messages(manifest)["issue"]["code"] == "invalid_b2mml"

    edit_manifest(manifest, lambda data: data["messages"][0].update(xml_file="../outside.xml"))
    assert replay_local_messages(manifest)["issue"]["code"] == "invalid_path"


def test_operation_overlap_and_nonmonotonic_delivery_are_rejected(tmp_path):
    manifest = package(tmp_path)
    origin = datetime.fromisoformat("2026-10-05T00:00:00+03:00")
    overlap = MESActual(
        lot_id="EX-L1",
        machine_id="EX-M2",
        operation_seq=2,
        actual_start_min=75,
        actual_end_min=120,
        produced_qty=8,
        scrap_qty=1,
    )
    (manifest.parent / "actual-op2.xml").write_bytes(mes_to_xml(overlap, origin=origin).encode("utf-8"))
    report = replay_local_messages(manifest)
    assert report["issue"]["code"] == "operation_precedence"
    assert report["accepted_actuals"] == []

    edit_manifest(manifest, lambda data: data["messages"][1].update(received_min=100))
    assert replay_local_messages(manifest)["issue"]["code"] == "invalid_delivery_time"
