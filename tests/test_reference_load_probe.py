"""A failed solver attempt must remain visible in the G7 timing report."""

import hashlib

import pytest

from src.scheduling import reference_load_probe


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
