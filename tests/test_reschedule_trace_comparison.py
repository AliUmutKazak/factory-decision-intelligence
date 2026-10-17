"""Paired replay keeps failed trials and rejects unequal solver settings."""

import hashlib
import json

import pytest

import scripts.compare_reschedule_event_traces as comparison


def _fixture_paths(tmp_path):
    source = tmp_path / "factory.db"
    source.write_bytes(b"immutable synthetic reference")
    traces = [tmp_path / "early.json", tmp_path / "late.json"]
    for index, trace in enumerate(traces):
        trace.write_text(
            json.dumps(
                [
                    {"event_id": "EVENT-1", "current_time_min": 100 + index},
                    {"event_id": "EVENT-2", "current_time_min": 200 + index},
                ]
            ),
            encoding="utf-8",
        )
    return source, hashlib.sha256(source.read_bytes()).hexdigest(), traces


def _outcome(accepted, seed=42):
    row = {"event": {"event_id": "EVENT-1"}, "accepted": accepted}
    if accepted:
        row.update(
            solver_metadata={
                "time_limit_seconds": 30.0,
                "random_seed": seed,
                "num_search_workers": 1,
                "makespan_min": 100,
                "total_tardiness_min": 20,
                "total_setup_min": 5,
                "wall_time_seconds": 1.0,
            },
            stability={"rescheduled_tasks_count": 2, "frozen_tasks_count": 1},
            elapsed_seconds=2.0,
        )
    return {"attempts": [row]}


def test_failed_method_stays_in_pair_and_method_order_rotates(tmp_path, monkeypatch):
    source, digest, traces = _fixture_paths(tmp_path)
    calls = []

    def fake_probe(_source, _digest, _run, trace, *, force_full_solver, dispatch_rule):
        assert force_full_solver
        calls.append((trace.name, dispatch_rule))
        return _outcome(dispatch_rule is None)

    monkeypatch.setattr(comparison, "probe", fake_probe)
    report = comparison.compare(source, digest, "BASE", traces, ["FULL", "EDD"])

    assert calls == [("early.json", None), ("early.json", "EDD"), ("late.json", "EDD"), ("late.json", None)]
    assert report["paired_accepted_event_count"] == 0
    assert report["planned_event_pair_count"] == 4
    assert all(pair["both_accepted"] is False for trace in report["traces"] for pair in trace["paired_events"])
    assert all("metrics" not in pair for trace in report["traces"] for pair in trace["paired_events"])
    assert all(
        trace["paired_events"][1]["method_status"]["EDD"] == "NOT_ATTEMPTED_AFTER_PRIOR_FAILURE"
        for trace in report["traces"]
    )
    assert source.read_bytes() == b"immutable synthetic reference"


def test_pair_rejects_unequal_solver_settings(tmp_path, monkeypatch):
    source, digest, traces = _fixture_paths(tmp_path)
    monkeypatch.setattr(
        comparison,
        "probe",
        lambda _source, _digest, _run, _trace, *, force_full_solver, dispatch_rule: _outcome(
            True, seed=42 if dispatch_rule is None else 17
        ),
    )
    with pytest.raises(RuntimeError, match="unequal solver settings"):
        comparison.compare(source, digest, "BASE", traces, ["FULL", "EDD"])
