"""Tests for Heuristic Benchmarking & Contract Integration (Faz 3 - Madde 5)."""

import pandas as pd
import pytest

from src.contracts.schemas import ScheduleSolverMetadata, SolverStatus
from src.scheduling.benchmark import (
    BenchmarkResult,
    BenchmarkTask,
    SchedulingBenchmarkSuite,
)


def test_heuristic_result_to_solver_metadata():
    """Sezgisel sonucunun ScheduleSolverMetadata sözleşmesine hatasız dönüştüğünü doğrular."""
    bench_res = BenchmarkResult(
        method="SPT",
        makespan=12.5,
        late_orders=0,
        total_tardiness=0.0,
        total_setup_time=1.5,
        total_processing_time=11.0,
    )

    meta = bench_res.to_solver_metadata()
    assert isinstance(meta, ScheduleSolverMetadata)
    assert meta.status == SolverStatus.FEASIBLE
    assert meta.proven_optimal is False
    assert meta.makespan_min == int(round(12.5 * 60))
    assert meta.total_setup_min == int(round(1.5 * 60))
    assert meta.total_tardiness_min == 0


def test_benchmark_suite_accepts_cpsat_contract():
    """SchedulingBenchmarkSuite'in doğrudan ScheduleSolverMetadata ile karşılaştırma yapabilmesini doğrular."""
    tasks = [
        BenchmarkTask(
            task_id="T1",
            product_id="P1",
            machine_id="M1",
            processing_time=2.0,
            release_date=0.0,
            due_date=10.0,
        ),
        BenchmarkTask(
            task_id="T2",
            product_id="P2",
            machine_id="M1",
            processing_time=3.0,
            release_date=0.0,
            due_date=8.0,
        ),
    ]
    suite = SchedulingBenchmarkSuite(tasks)

    dummy_cpsat_meta = ScheduleSolverMetadata(
        run_id="RUN-TEST-001",
        status=SolverStatus.OPTIMAL,
        proven_optimal=True,
        wall_time_seconds=0.45,
        objective_value=300.0,
        makespan_min=300,  # 5 saat
        total_setup_min=30,  # 0.5 saat
        total_tardiness_min=0,
    )

    df_comp = suite.run_cpsat_comparison(cpsat_result=dummy_cpsat_meta)

    # 4 Sezgisel (FIFO, EDD, SPT, Greedy) + 1 CP-SAT = 5 Satır
    assert len(df_comp) == 5
    assert "CP-SAT (Reported)" in df_comp["Method"].values
    cpsat_row = df_comp[df_comp["Method"] == "CP-SAT (Reported)"].iloc[0]
    assert cpsat_row["Makespan (hr)"] == 5.0


def test_solver_aggregate_does_not_invent_late_order_count_or_unweighted_tardiness():
    metadata = ScheduleSolverMetadata(
        run_id="WEIGHTED",
        status=SolverStatus.FEASIBLE,
        proven_optimal=False,
        wall_time_seconds=1,
        objective_value=100,
        makespan_min=120,
        total_setup_min=0,
        total_tardiness_min=90,
    )
    row = SchedulingBenchmarkSuite([]).run_cpsat_comparison(metadata).iloc[-1]
    assert pd.isna(row["Late Orders"])
    assert pd.isna(row["Total Tardiness (hr)"])
    assert row["Weighted Tardiness (hr)"] == 1.5


def test_reported_benchmark_counts_lots_once_and_keeps_weights_separate():
    schedule = pd.DataFrame(
        [
            {
                "lot_id": "A",
                "operation_seq": 1,
                "start_min": 0,
                "end_min": 120,
                "duration_min": 120,
                "due_date_min": 60,
                "priority_weight": 3,
                "setup_before_min": 0,
            },
            {
                "lot_id": "A",
                "operation_seq": 2,
                "start_min": 120,
                "end_min": 180,
                "duration_min": 60,
                "due_date_min": 60,
                "priority_weight": 3,
                "setup_before_min": 10,
            },
            {
                "lot_id": "B",
                "operation_seq": 1,
                "start_min": 0,
                "end_min": 90,
                "duration_min": 90,
                "due_date_min": 60,
                "priority_weight": 2,
                "setup_before_min": 0,
            },
        ]
    )
    metrics = SchedulingBenchmarkSuite.reported_schedule_metrics(schedule)
    assert metrics["late_orders"] == 2
    assert metrics["total_tardiness"] == 2.5
    assert metrics["weighted_tardiness"] == 7
    assert metrics["makespan"] == 3
    assert metrics["total_setup_time"] == 0.17
    with pytest.raises(ValueError, match="due dates"):
        SchedulingBenchmarkSuite.reported_schedule_metrics(schedule.drop(columns="due_date_min"))


def test_heuristic_counts_one_late_order_for_multiple_operations():
    tasks = [
        BenchmarkTask("A-1", "P1", "M1", 2, 1, order_id="A", priority_weight=3),
        BenchmarkTask("A-2", "P1", "M1", 1, 1, order_id="A", priority_weight=3),
    ]
    result = SchedulingBenchmarkSuite(tasks).run_heuristic("FIFO")
    assert result.late_orders == 1
    assert result.total_tardiness == 2
    assert result.weighted_tardiness == 6


def test_benchmark_rejects_ambiguous_or_missing_task_inputs():
    task = BenchmarkTask("A", "P", "M", 1, 1)
    with pytest.raises(ValueError, match="Duplicate"):
        SchedulingBenchmarkSuite([task, task])
    with pytest.raises(ValueError, match="finite"):
        SchedulingBenchmarkSuite([BenchmarkTask("A", "P", "M", 1, float("nan"))])


def test_greedy_uses_available_finish_time_instead_of_edd_sorting():
    suite = SchedulingBenchmarkSuite(
        [
            BenchmarkTask("LONG", "P1", "M1", 10, 1),
            BenchmarkTask("SHORT", "P2", "M1", 1, 2),
        ]
    )
    result = suite.run_heuristic("Greedy")
    assert result.late_orders == 1
    assert result.total_tardiness == 10.5
    assert suite.run_heuristic("EDD").late_orders == 2
    assert result.to_solver_metadata().wall_time_seconds == result.wall_time_seconds


def test_infeasible_solver_result_is_not_benchmarked_as_a_schedule():
    metadata = ScheduleSolverMetadata(
        run_id="FAILED",
        status=SolverStatus.INFEASIBLE,
        proven_optimal=False,
        wall_time_seconds=1,
        objective_value=0,
        makespan_min=0,
        total_setup_min=0,
    )
    with pytest.raises(ValueError, match="feasible"):
        SchedulingBenchmarkSuite([]).run_cpsat_comparison(metadata)
