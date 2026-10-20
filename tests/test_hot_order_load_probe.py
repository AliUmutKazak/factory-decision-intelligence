"""G7 replay must distinguish baseline failure from hot-order failure."""

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import pytest

from src.contracts.schemas import ScenarioDeltaReport, ScenarioType, ScheduleSolverMetadata, SolverStatus
from src.scheduling import hot_order_load_probe

REFERENCE_DB = Path(__file__).resolve().parents[1] / "artifacts/reference/factory.db"


@pytest.mark.parametrize("failure_stage", ["BASELINE", "SCENARIO"])
def test_probe_classifies_timeout_and_preserves_sealed_source(monkeypatch, failure_stage):
    source_hash = hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest()

    class FakeEngine:
        def __init__(self, disk_db_path):
            self.disk_db_path = disk_db_path
            self.baseline_metadata = None

        def simulate_hot_order(self, *args, **kwargs):
            if failure_stage == "SCENARIO":
                self.baseline_metadata = ScheduleSolverMetadata(
                    run_id="BASE",
                    status=SolverStatus.FEASIBLE,
                    proven_optimal=False,
                    wall_time_seconds=1.0,
                    objective_value=1.0,
                )
            raise TimeoutError("UNKNOWN: no accepted solution")

    monkeypatch.setattr(hot_order_load_probe, "_MeasuredWhatIfEngine", FakeEngine)
    report = hot_order_load_probe.probe_hot_order_replay(
        REFERENCE_DB,
        "RUN-20261006-00a0d3",
        expected_sha256=source_hash,
        repeats=1,
    )

    assert report["source_db_sha256"] == source_hash
    assert hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest() == source_hash
    assert report["attempts"][0]["failure_stage"] == failure_stage
    assert report["attempts"][0]["staged_active_unchanged"] is True
    assert report["summary"][f"{failure_stage.lower()}_timeout_count"] == 1
    assert report["summary"]["scenario_accepted_count"] == 0


def test_probe_counts_only_independently_audited_candidate():
    source_hash = hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest()
    report = hot_order_load_probe.probe_hot_order_replay(
        REFERENCE_DB,
        "RUN-20261006-00a0d3",
        expected_sha256=source_hash,
        repeats=1,
        scenario_limit_seconds=2,
        reuse_active_baseline=True,
        scenario_dispatch_rule="EDD",
    )
    assert report["summary"]["scenario_accepted_count"] == 1
    assert report["attempts"][0]["independent_audit"]["status"] == "ACCEPTED"
    assert report["attempts"][0]["independent_audit"]["task_count"] > 0
    assert hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest() == source_hash


def test_probe_rejects_solver_result_when_independent_audit_fails(monkeypatch):
    source_hash = hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest()

    class FakeEngine:
        def __init__(self, disk_db_path):
            self.baseline_metadata = None

        def simulate_hot_order(self, *args, **kwargs):
            baseline = ScheduleSolverMetadata(
                run_id="BASE",
                status=SolverStatus.FEASIBLE,
                proven_optimal=False,
                wall_time_seconds=1,
                objective_value=1,
            )
            scenario = ScheduleSolverMetadata(
                run_id="SCENARIO",
                status=SolverStatus.FEASIBLE,
                proven_optimal=False,
                wall_time_seconds=1,
                objective_value=1,
            )
            return baseline, scenario, None, None

    monkeypatch.setattr(hot_order_load_probe, "_MeasuredWhatIfEngine", FakeEngine)
    monkeypatch.setattr(
        hot_order_load_probe,
        "audit_hot_order_schedule",
        lambda *args: {"status": "REJECTED", "scope": "TEST", "issues": [{"code": "MACHINE_OVERLAP"}]},
    )
    report = hot_order_load_probe.probe_hot_order_replay(
        REFERENCE_DB,
        "RUN-20261006-00a0d3",
        expected_sha256=source_hash,
        repeats=1,
    )
    assert report["attempts"][0]["scenario_status"] == "REJECTED_BY_AUDIT"
    assert report["summary"]["scenario_accepted_count"] == 0
    assert report["summary"]["audit_failure_count"] == 1


def test_probe_uses_recomputed_kpis_not_solver_metadata(monkeypatch):
    source_hash = hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest()

    class FakeEngine:
        def __init__(self, disk_db_path):
            self.disk_db_path = disk_db_path
            self.baseline_metadata = None

        def simulate_hot_order(self, *args, **kwargs):
            metadata = ScheduleSolverMetadata(
                run_id="SYNTHETIC",
                status=SolverStatus.FEASIBLE,
                proven_optimal=False,
                wall_time_seconds=0.1,
                objective_value=1,
                makespan_min=999,
                total_tardiness_min=999,
                total_setup_min=999,
            )
            delta = ScenarioDeltaReport(
                scenario_name="SYNTHETIC",
                scenario_type=ScenarioType.HOT_ORDER,
                baseline_makespan_min=1,
                scenario_makespan_min=10,
                makespan_delta_min=9,
                baseline_total_tardiness_min=2,
                scenario_total_tardiness_min=20,
                tardiness_delta_min=18,
                baseline_total_setup_min=3,
                scenario_total_setup_min=30,
                setup_delta_min=27,
                impacted_tasks_count=31,
            )
            with closing(sqlite3.connect(self.disk_db_path)) as conn:
                schedule = pd.read_sql_query("SELECT * FROM production_schedule", conn)
            return metadata, metadata, delta, schedule

    monkeypatch.setattr(hot_order_load_probe, "_MeasuredWhatIfEngine", FakeEngine)
    monkeypatch.setattr(
        hot_order_load_probe,
        "audit_hot_order_schedule",
        lambda *args: {"status": "ACCEPTED", "scope": "TEST", "issues": [], "task_count": 31},
    )
    report = hot_order_load_probe.probe_hot_order_replay(
        REFERENCE_DB,
        "RUN-20261006-00a0d3",
        expected_sha256=source_hash,
        repeats=1,
    )
    attempt = report["attempts"][0]
    assert attempt["scenario_status"] == "FEASIBLE"
    assert attempt["scenario_makespan_min"] == 10
    assert attempt["scenario_total_tardiness_min"] == 20
    assert attempt["scenario_total_setup_min"] == 30
