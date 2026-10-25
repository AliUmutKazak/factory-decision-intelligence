"""Paired synthetic trials retain failures and measure existing-plan movement."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.scheduling.dispatch import dispatch_rank
from src.scheduling.hot_order_load_probe import _schedule_stability
from src.scheduling.hot_order_method_comparison import _summarize, compare_hot_order_methods
from src.scheduling.schedule_cpsat import run_cpsat_scheduling

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DB = ROOT / "artifacts/reference/factory.db"


def test_stability_methods_require_an_isolated_memory_connection():
    with pytest.raises(ValueError, match="isolated BALANCED what-if"):
        run_cpsat_scheduling(
            reference_schedule=pd.DataFrame([{"task_id": "old", "start_min": 1, "end_min": 2}]),
            dispatch_rule="APPEND",
            persist_outputs=False,
        )


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


def test_transfer_fifo_does_not_link_independent_orders_of_same_product():
    tasks = pd.DataFrame(
        [
            {
                "task_id": "old-1",
                "lot_id": "A-1",
                "parent_lot_id": "A",
                "product_id": "P01",
                "operation_seq": 1,
                "sub_lot_index": 1,
                "machine_id": "M01",
                "duration": 1,
                "due_date_min": 100,
                "release_time_min": 0,
            },
            {
                "task_id": "old-2",
                "lot_id": "A-2",
                "parent_lot_id": "A",
                "product_id": "P01",
                "operation_seq": 1,
                "sub_lot_index": 2,
                "machine_id": "M01",
                "duration": 1,
                "due_date_min": 100,
                "release_time_min": 0,
            },
            {
                "task_id": "rush-1",
                "lot_id": "B",
                "parent_lot_id": "B",
                "product_id": "P01",
                "operation_seq": 1,
                "sub_lot_index": 1,
                "machine_id": "M01",
                "duration": 1,
                "due_date_min": 1,
                "release_time_min": 0,
            },
        ]
    )
    ranks = dispatch_rank(tasks, "EDD")
    assert ranks["rush-1"] < ranks["old-1"] < ranks["old-2"]


def test_summary_excludes_failed_candidate_quality_and_preserves_denominator():
    passed = {"accepted": True, "status": "FEASIBLE", "replay_wall_seconds": 1.0}
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
    failed = {**passed, "accepted": False, "status": "NO_ACCEPTED_SOLUTION", "replay_wall_seconds": 2.0}
    failed["scenario_makespan_min"] = 1
    summary = _summarize([passed, failed])
    assert summary["attempts"] == 2
    assert summary["accepted"] == summary["failures"] == 1
    assert summary["metric_quantiles_accepted_only"]["scenario_makespan_min"]["median"] == 10
    assert summary["replay_wall_seconds_all_attempts"] == {"p50": 1.5, "p95": 1.95}


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


def test_append_candidate_keeps_existing_plan_and_passes_independent_audit(tmp_path):
    cases = {
        "source_type": "SYNTHETIC",
        "cases": [
            {
                "case_id": "RUSH_SAME_PRODUCT",
                "hot_order": {
                    "order_id": "RUSH-SEPARATE-LOT",
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
        methods=("APPEND",),
        scenario_limit_seconds=10,
        workers=1,
    )
    candidate = report["trials"][0]
    assert candidate["accepted"]
    assert candidate["independent_audit"]["status"] == "ACCEPTED"
    assert candidate["changed_existing_task_count"] == 0
    assert candidate["absolute_existing_start_shift_min"] == 0
    assert candidate["new_task_count"] > 0
    assert hashlib.sha256(REFERENCE_DB.read_bytes()).hexdigest() == digest
