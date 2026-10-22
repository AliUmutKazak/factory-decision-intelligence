"""A failed solver attempt must remain visible in the G7 timing report."""

import hashlib
import sqlite3

import pandas as pd
import pytest

from src.scheduling import reference_load_probe
from src.scheduling.model_context import load_model_context
from src.scheduling.reschedule_candidate_audit import audit_reference_benchmark_candidate


def test_reference_probe_reports_failed_attempt_separately_from_solver_latency(tmp_path, monkeypatch):
    source = tmp_path / "reference.db"
    source.write_bytes(b"sealed sample")
    cases = [
        {"Method": "CP-SAT", "Status": "OPTIMAL", "Solve Time (s)": 1.0},
        {"Method": "CP-SAT", "Status": "NO_ACCEPTED_SOLUTION", "Reason": "UNKNOWN: no solution"},
        {"Method": "CP-SAT", "Status": "FEASIBLE", "Solve Time (s)": 3.0},
    ]

    def fake_benchmark(**kwargs):
        assert kwargs["rules"] == ("CP-SAT",)
        assert kwargs["baseline_run_id"] == "REFERENCE"
        return {
            "cases": [cases.pop(0)],
            "input_hash": "same-input",
            "code_hashes": {"solver": "same-code"},
            "git_sha": "test-commit",
        }

    monkeypatch.setattr(reference_load_probe, "production_benchmark", fake_benchmark)
    monkeypatch.setattr(reference_load_probe, "_audit_candidate", lambda *_: {"status": "ACCEPTED", "issues": []})
    report = reference_load_probe.probe_reference_load(
        source,
        "REFERENCE",
        repeats=3,
        expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    assert report["summary"]["status_counts"] == {
        "OPTIMAL": 1,
        "NO_ACCEPTED_SOLUTION": 1,
        "FEASIBLE": 1,
    }
    assert report["summary"]["accepted_count"] == 2
    assert report["summary"]["no_accepted_solution_count"] == 1
    assert report["summary"]["accepted_solver_wall_p50_seconds"] == 2.0
    assert report["summary"]["accepted_solver_wall_p95_seconds"] == 2.9
    assert report["attempts"][1]["solver_wall_seconds"] is None
    assert report["attempts"][1]["reason"] == "UNKNOWN: no solution"


def test_reference_probe_excludes_independently_rejected_solver_candidate(tmp_path, monkeypatch):
    source = tmp_path / "reference.db"
    source.write_bytes(b"sealed sample")
    monkeypatch.setattr(
        reference_load_probe,
        "production_benchmark",
        lambda **_: {
            "cases": [{"Method": "CP-SAT", "Status": "FEASIBLE", "Solve Time (s)": 1.0}],
            "input_hash": "same-input",
            "code_hashes": {"solver": "same-code"},
            "git_sha": "test-commit",
        },
    )
    monkeypatch.setattr(
        reference_load_probe,
        "_audit_candidate",
        lambda *_: {"status": "REJECTED", "issues": [{"code": "MACHINE_OCCUPANCY_OVERLAP", "detail": "A"}]},
    )
    report = reference_load_probe.probe_reference_load(source, "REFERENCE", repeats=1)
    assert report["attempts"][0]["solver_status"] == "FEASIBLE"
    assert report["attempts"][0]["status"] == "REJECTED_BY_AUDIT"
    assert report["summary"]["accepted_count"] == 0
    assert report["summary"]["accepted_solver_wall_p50_seconds"] is None


def test_reference_audit_detects_candidate_timing_corruption():
    source = "artifacts/reference/factory.db"
    run_id = "RUN-20261006-00a0d3"
    with sqlite3.connect(source) as conn:
        baseline = pd.read_sql_query("SELECT * FROM production_schedule WHERE run_id = ?", conn, params=(run_id,))
        context = load_model_context(conn, run_id)
        accepted = audit_reference_benchmark_candidate(conn, run_id, baseline, baseline.copy(), context)
        assert accepted["status"] == "ACCEPTED"
        corrupted = baseline.copy()
        corrupted.loc[0, "duration_min"] += 1
        rejected = audit_reference_benchmark_candidate(conn, run_id, baseline, corrupted, context)
    assert rejected["status"] == "REJECTED"
    assert {issue["code"] for issue in rejected["issues"]} & {"TASK_INPUT_CHANGED", "INVALID_TASK_TIMING"}


def test_reference_probe_rejects_source_change(tmp_path, monkeypatch):
    source = tmp_path / "reference.db"
    source.write_bytes(b"original")

    def fake_benchmark(**kwargs):
        source.write_bytes(b"changed")
        return {
            "cases": [{"Method": "CP-SAT", "Status": "OPTIMAL", "Solve Time (s)": 1.0}],
            "input_hash": "input",
            "code_hashes": {"solver": "code"},
            "git_sha": "test-commit",
        }

    monkeypatch.setattr(reference_load_probe, "production_benchmark", fake_benchmark)
    with pytest.raises(RuntimeError, match="source DB changed"):
        reference_load_probe.probe_reference_load(source, "REFERENCE", repeats=1)
