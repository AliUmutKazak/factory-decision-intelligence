"""Tests for Heuristic Benchmarking & Contract Integration (Faz 3 - Madde 5)."""

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
    assert "CP-SAT (Exact)" in df_comp["Method"].values
    cpsat_row = df_comp[df_comp["Method"] == "CP-SAT (Exact)"].iloc[0]
    assert cpsat_row["Makespan (hr)"] == 5.0
