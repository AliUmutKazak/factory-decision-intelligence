"""Tests for Scheduling Benchmark Suite (Madde 32)."""

import pandas as pd
from src.scheduling.benchmark import BenchmarkTask, SchedulingBenchmarkSuite


def test_heuristic_benchmark_rules():
    """FIFO, EDD, SPT ve Greedy sezgisellerinin çalıştığını ve metrik ürettiğini doğrular."""
    tasks = [
        BenchmarkTask(
            task_id="T1",
            product_id="P1",
            machine_id="M1",
            processing_time=10.0,
            due_date=12.0,
        ),
        BenchmarkTask(
            task_id="T2",
            product_id="P2",
            machine_id="M1",
            processing_time=2.0,
            due_date=5.0,
        ),
        BenchmarkTask(
            task_id="T3",
            product_id="P1",
            machine_id="M1",
            processing_time=4.0,
            due_date=20.0,
        ),
    ]

    setup_matrix = {("P1", "P2"): 1.0, ("P2", "P1"): 1.5}
    suite = SchedulingBenchmarkSuite(tasks=tasks, setup_matrix=setup_matrix)

    # 1. FIFO: T1 (10) -> T2 (setup 1 + proc 2 = 13) -> T3 (setup 1.5 + proc 4 = 18.5)
    fifo = suite.run_heuristic("FIFO")
    assert fifo.method == "FIFO"
    assert fifo.makespan > 0
    assert fifo.late_orders >= 1  # T2 gecikir (due_date=5, bitiş=13)

    # 2. EDD: Teslim tarihine göre sıralama (T2 (5), T1 (12), T3 (20))
    edd = suite.run_heuristic("EDD")
    assert edd.method == "EDD"
    assert edd.total_tardiness <= fifo.total_tardiness  # EDD gecikmeyi azaltmalı

    # 3. SPT: İşlem süresine göre sıralama (T2 (2), T3 (4), T1 (10))
    spt = suite.run_heuristic("SPT")
    assert spt.method == "SPT"
    assert spt.makespan > 0

    # 4. Genel karşılaştırma tablosu üretimi
    df = suite.run_cpsat_comparison(
        cpsat_result={
            "makespan": 17.0,
            "late_orders": 0,
            "total_tardiness": 0.0,
            "total_setup_time": 1.0,
        }
    )

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5  # FIFO, EDD, SPT, Greedy, CP-SAT
    assert "Makespan (hr)" in df.columns
    assert "Total Tardiness (hr)" in df.columns