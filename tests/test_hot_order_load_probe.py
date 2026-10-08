"""G7 replay must distinguish baseline failure from hot-order failure."""

import hashlib
from pathlib import Path

import pytest

from src.contracts.schemas import ScheduleSolverMetadata, SolverStatus
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
