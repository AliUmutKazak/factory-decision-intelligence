"""Paired synthetic trials retain failures and measure existing-plan movement."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from src.scheduling.hot_order_load_probe import _schedule_stability
from src.scheduling.hot_order_method_comparison import _summarize, compare_hot_order_methods

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DB = ROOT / "artifacts/reference/factory.db"


def test_stability_counts_only_existing_tasks_and_machine_changes():
    old = pd.DataFrame(
        [
            {"task_id": 1, "machine_id": "M1", "start_min": 10},
            {"task_id": 2, "machine_id": "M2", "start_min": 20},
        ]
    )
    new = pd.DataFrame(
        [
            {"task_id": 1, "machine_id": "M1", "start_min": 13},
            {"task_id": 2, "machine_id": "M3", "start_min": 20},
            {"task_id": 3, "machine_id": "M2", "start_min": 30},
        ]
    )
    assert _schedule_stability(old, new) == {
        "baseline_task_count": 2,
        "new_task_count": 1,
        "changed_existing_task_count": 2,
        "absolute_existing_start_shift_min": 3,
    }


def test_summary_excludes_failed_candidate_quality_and_preserves_denominator():
    passed = {"accepted": True, "status": "FEASIBLE"}
    passed.update(
        {
            metric: 10
            for metric in (
                "scenario_makespan_min",
                "scenario_total_tardiness_min",
                "scenario_total_setup_min",
                "scenario_solver_wall_seconds",
                "changed_existing_task_count",
                "absolute_existing_start_shift_min",
            )
        }
    )
    failed = {**passed, "accepted": False, "status": "NO_ACCEPTED_SOLUTION"}
    failed["scenario_makespan_min"] = 1
    summary = _summarize([passed, failed])
    assert summary["attempts"] == 2
    assert summary["accepted"] == summary["failures"] == 1
    assert summary["metric_quantiles_accepted_only"]["scenario_makespan_min"]["median"] == 10


def test_paired_methods_use_same_seed_source_and_independent_audit(tmp_path):
    cases = {
        "source_type": "SYNTHETIC",
        "cases": [
            {
                "case_id": "ONE_ARRIVAL",
                "hot_order": {
                    "order_id": "G7-PAIR-P01-1",
                    "product_id": "P01",
                    "quantity": 1,
                    "due_date_min": 480,
                    "priority_weight": 20,
                },
            }
        ],
    }
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")
    digest = hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest()
    report = compare_hot_order_methods(
        REFERENCE_DB,
        "RUN-20261006-00a0d3",
        expected_sha256=digest,
        cases_path=cases_file,
        seeds=(7,),
        methods=("EDD", "FIFO"),
        scenario_limit_seconds=2,
        workers=1,
    )
    assert report["source_db_sha256"] == digest
    assert len(report["trials"]) == 2
    assert {row["method"] for row in report["trials"]} == {"EDD", "FIFO"}
    assert all(row["accepted"] and row["independent_audit"]["status"] == "ACCEPTED" for row in report["trials"])
    assert all(
        row["measured_solver_random_seed"] == 7 and row["measured_solver_workers"] == 1 for row in report["trials"]
    )
    assert all(row["baseline_task_count"] > 0 and row["new_task_count"] > 0 for row in report["trials"])
    assert hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest() == digest
