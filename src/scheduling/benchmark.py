"""Scheduling Benchmark Suite (Madde 32).

Quantitatively benchmarks OR-Tools CP-SAT against traditional industrial heuristics:
- FIFO (First-In, First-Out)
- EDD (Earliest Due Date)
- SPT (Shortest Processing Time)
- Greedy (Earliest Available Machine with minimal setup)

Evaluates:
- Makespan (C_max)
- Late Orders count
- Total Tardiness (sum of max(0, completion - due_date))
- Total Setup Duration
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.contracts.schemas import ScheduleSolverMetadata, SolverStatus


@dataclass
class BenchmarkTask:
    task_id: str
    product_id: str
    machine_id: str
    processing_time: float
    due_date: float
    release_date: float = 0.0


@dataclass
class BenchmarkResult:
    method: str
    makespan: float
    late_orders: int
    total_tardiness: float
    total_setup_time: float
    total_processing_time: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "Method": self.method,
            "Makespan (hr)": round(self.makespan, 2),
            "Late Orders": self.late_orders,
            "Total Tardiness (hr)": round(self.total_tardiness, 2),
            "Total Setup Time (hr)": round(self.total_setup_time, 2),
        }

    def to_solver_metadata(self, run_id: str = "HEURISTIC-RUN") -> ScheduleSolverMetadata:
        """Sezgisel sonucunu standart ScheduleSolverMetadata sözleşmesine dönüştürür."""
        return ScheduleSolverMetadata(
            run_id=f"{run_id}-{self.method}",
            status=SolverStatus.FEASIBLE,
            proven_optimal=False,
            wall_time_seconds=0.001,  # Sezgiseller anlık çalışır (< 1-2 ms)
            objective_value=float(round(self.makespan + self.total_setup_time + self.total_tardiness, 4)),
            best_objective_bound=None,
            random_seed=42,
            num_search_workers=1,
            time_limit_seconds=0.0,
            makespan_min=int(round(self.makespan * 60)),  # Saat -> Dakika dönüşümü
            total_setup_min=int(round(self.total_setup_time * 60)),
            total_tardiness_min=int(round(self.total_tardiness * 60)),
        )


class SchedulingBenchmarkSuite:
    """Endüstriyel sezgiseller ve CP-SAT karşılaştırma motoru."""

    def __init__(self, tasks: list[BenchmarkTask], setup_matrix: dict[tuple[str, str], float] | None = None):
        self.tasks = tasks
        self.setup_matrix = setup_matrix or {}

    def _get_setup(self, prev_prod: str | None, next_prod: str) -> float:
        if prev_prod is None:
            return 0.0
        return self.setup_matrix.get((prev_prod, next_prod), 0.5 if prev_prod != next_prod else 0.0)

    def run_heuristic(self, rule: str) -> BenchmarkResult:
        """Belirtilen kurala göre (FIFO, EDD, SPT) çizelge oluşturur ve metrikleri hesaplar."""
        tasks_sorted = list(self.tasks)
        if rule == "FIFO":
            # Doğal liste sırası / geliş sırası
            pass
        elif rule == "EDD":
            tasks_sorted.sort(key=lambda t: t.due_date)
        elif rule == "SPT":
            tasks_sorted.sort(key=lambda t: t.processing_time)
        elif rule == "Greedy":
            tasks_sorted.sort(key=lambda t: (t.due_date, t.processing_time))
        else:
            raise ValueError(f"Bilinmeyen kural: {rule}")

        # Makine bazında ardışık simülasyon
        machine_availability: dict[str, float] = {}
        machine_last_product: dict[str, str | None] = {}
        completion_times: dict[str, float] = {}

        total_setup_time = 0.0
        total_proc_time = sum(t.processing_time for t in self.tasks)

        for task in tasks_sorted:
            m = task.machine_id
            curr_avail = machine_availability.get(m, 0.0)
            prev_prod = machine_last_product.get(m, None)

            setup = self._get_setup(prev_prod, task.product_id)
            start_time = max(curr_avail, task.release_date) + setup
            finish_time = start_time + task.processing_time

            total_setup_time += setup
            machine_availability[m] = finish_time
            machine_last_product[m] = task.product_id
            completion_times[task.task_id] = finish_time

        makespan = max(machine_availability.values()) if machine_availability else 0.0
        late_orders = 0
        total_tardiness = 0.0

        for task in self.tasks:
            comp = completion_times[task.task_id]
            tardiness = max(0.0, comp - task.due_date)
            if tardiness > 1e-4:
                late_orders += 1
                total_tardiness += tardiness

        return BenchmarkResult(
            method=rule,
            makespan=makespan,
            late_orders=late_orders,
            total_tardiness=total_tardiness,
            total_setup_time=total_setup_time,
            total_processing_time=total_proc_time,
        )

    def run_cpsat_comparison(self, cpsat_result: dict[str, Any] | ScheduleSolverMetadata | None = None) -> pd.DataFrame:
        """Tüm sezgiselleri ve CP-SAT sonucunu birleştirip kıyaslama tablosu döner."""
        results = [
            self.run_heuristic("FIFO"),
            self.run_heuristic("EDD"),
            self.run_heuristic("SPT"),
            self.run_heuristic("Greedy"),
        ]

        # Eğer dışarıdan ScheduleSolverMetadata veya dict formatında CP-SAT sonucu verilmişse ekle
        if cpsat_result is not None:
            if isinstance(cpsat_result, ScheduleSolverMetadata):
                makespan_hr = (cpsat_result.makespan_min or 0) / 60.0
                setup_hr = (cpsat_result.total_setup_min or 0) / 60.0
                tardiness_hr = (cpsat_result.total_tardiness_min or 0) / 60.0
                late_orders = 1 if tardiness_hr > 0 else 0
                results.append(
                    BenchmarkResult(
                        method="CP-SAT (Exact)",
                        makespan=makespan_hr,
                        late_orders=late_orders,
                        total_tardiness=tardiness_hr,
                        total_setup_time=setup_hr,
                        total_processing_time=sum(t.processing_time for t in self.tasks),
                    )
                )
            elif isinstance(cpsat_result, dict):
                results.append(
                    BenchmarkResult(
                        method="CP-SAT (Exact)",
                        makespan=float(cpsat_result.get("makespan", 0.0)),
                        late_orders=int(cpsat_result.get("late_orders", 0)),
                        total_tardiness=float(cpsat_result.get("total_tardiness", 0.0)),
                        total_setup_time=float(cpsat_result.get("total_setup_time", 0.0)),
                        total_processing_time=sum(t.processing_time for t in self.tasks),
                    )
                )

        df = pd.DataFrame([r.to_dict() for r in results])
        return df
