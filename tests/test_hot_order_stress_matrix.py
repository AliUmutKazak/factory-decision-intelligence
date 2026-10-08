"""Labeled G7 matrix broadens synthetic cases while preserving source evidence."""

import hashlib
import json
from pathlib import Path

import pytest

from src.scheduling import hot_order_stress_matrix

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DB = ROOT / "artifacts/reference/factory.db"
CASES = ROOT / "examples/g7-hot-order-stress-cases.json"
RUN_ID = "RUN-20261006-00a0d3"


def test_matrix_audits_three_distinct_hot_orders_without_changing_reference():
    source_hash = hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest()
    report = hot_order_stress_matrix.probe_hot_order_matrix(
        REFERENCE_DB,
        RUN_ID,
        expected_sha256=source_hash,
        cases_path=CASES,
        repeats=1,
        scenario_limit_seconds=2,
    )
    assert report["scope"] == "LAB_SYNTHETIC_HOT_ORDER_MATRIX_NO_FACTORY_VALIDATION_OR_SLO"
    assert report["case_count"] == report["attempt_count"] == report["independently_accepted_count"] == 3
    assert report["all_accepted"] is True
    assert {row["report"]["hot_order"]["product_id"] for row in report["cases"]} == {"P01", "P03"}
    assert {row["report"]["hot_order"]["quantity"] for row in report["cases"]} == {1, 51, 200}
    assert all(row["report"]["attempts"][0]["independent_audit"]["status"] == "ACCEPTED" for row in report["cases"])
    assert hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest() == source_hash


def test_matrix_rejects_duplicate_case_ids_before_running_any_case(tmp_path, monkeypatch):
    manifest = json.loads(CASES.read_text(encoding="utf-8"))
    manifest["cases"].append({**manifest["cases"][0]})
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        hot_order_stress_matrix,
        "probe_hot_order_replay",
        lambda *args, **kwargs: pytest.fail("case execution started before manifest validation"),
    )
    with pytest.raises(ValueError, match="duplicate case_id"):
        hot_order_stress_matrix.probe_hot_order_matrix(
            REFERENCE_DB,
            RUN_ID,
            expected_sha256=hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest(),
            cases_path=cases_file,
            repeats=1,
        )
