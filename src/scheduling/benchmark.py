"""Scheduling Benchmark Suite (Madde 32).

Reports CP-SAT metrics alongside simplified industrial heuristic illustrations.
Heuristics omit routing precedence, calendars, maintenance and frozen commitments;
these results do not establish equivalent-feasibility performance gains.
- FIFO (First-In, First-Out)
- EDD (Earliest Due Date)
- SPT (Shortest Processing Time)
- Greedy (Earliest finish on each task's fixed machine)

Evaluates:
- Makespan (C_max)
- Late Orders count
- Total Tardiness (sum of max(0, completion - due_date))
- Total Setup Duration
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Any

import pandas as pd

from src.contracts.schemas import ScheduleSolverMetadata, SolverStatus
from src.scheduling.analytics_schema import schedule_job_summary
from src.scheduling.service_level import evaluate_schedule_service_level


@dataclass
class BenchmarkTask:
    task_id: str
    product_id: str
    machine_id: str
    processing_time: float
    due_date: float
    release_date: float = 0.0
    order_id: str | None = None
    priority_weight: float = 1.0


@dataclass
class BenchmarkResult:
    method: str
    makespan: float
    late_orders: int | None
    total_tardiness: float | None
    total_setup_time: float
    total_processing_time: float
    weighted_tardiness: float | None = None
    wall_time_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "Method": self.method,
            "Makespan (hr)": round(self.makespan, 2),
            "Late Orders": self.late_orders,
            "Total Tardiness (hr)": round(self.total_tardiness, 2) if self.total_tardiness is not None else None,
            "Weighted Tardiness (hr)": round(self.weighted_tardiness, 2)
            if self.weighted_tardiness is not None
            else None,
            "Total Setup Time (hr)": round(self.total_setup_time, 2),
        }

    def to_solver_metadata(self, run_id: str = "HEURISTIC-RUN") -> ScheduleSolverMetadata:
        """Sezgisel sonucunu standart ScheduleSolverMetadata sözleşmesine dönüştürür."""
        if self.total_tardiness is None:
            raise ValueError("Unknown tardiness cannot be converted to solver metadata.")
        weighted = self.weighted_tardiness if self.weighted_tardiness is not None else self.total_tardiness
        return ScheduleSolverMetadata(
            run_id=f"{run_id}-{self.method}",
            status=SolverStatus.FEASIBLE,
            proven_optimal=False,
            wall_time_seconds=self.wall_time_seconds,
            objective_value=float(round((self.makespan + self.total_setup_time + weighted) * 60, 4)),
            best_objective_bound=None,
            random_seed=42,
            num_search_workers=1,
            time_limit_seconds=0.0,
            makespan_min=int(round(self.makespan * 60)),  # Saat -> Dakika dönüşümü
            total_setup_min=int(round(self.total_setup_time * 60)),
            total_tardiness_min=int(round(weighted * 60)),
        )


class SchedulingBenchmarkSuite:
    """Endüstriyel sezgiseller ve CP-SAT karşılaştırma motoru."""

    def __init__(self, tasks: list[BenchmarkTask], setup_matrix: dict[tuple[str, str], float] | None = None):
        self.tasks = tasks
        self.setup_matrix = setup_matrix or {}
        if len({task.task_id for task in tasks}) != len(tasks):
            raise ValueError("Duplicate benchmark task_id.")
        order_metadata = {}
        for task in tasks:
            values = (task.processing_time, task.due_date, task.release_date, task.priority_weight)
            if not all(isfinite(value) and value >= 0 for value in values):
                raise ValueError("Benchmark durations, due dates, releases and weights must be finite and nonnegative.")
            order = task.order_id or task.task_id
            metadata = (task.due_date, task.priority_weight)
            if order in order_metadata and order_metadata[order] != metadata:
                raise ValueError(f"Conflicting due date or priority for benchmark order {order}.")
            order_metadata[order] = metadata
        self.order_metadata = order_metadata

    @staticmethod
    def reported_schedule_metrics(schedule: pd.DataFrame) -> dict[str, Any]:
        """Compute actual late lots and both tardiness measures from operation rows."""
        if not schedule.empty:
            _, jobs = schedule_job_summary(schedule)
            if (
                "due_date_min" not in jobs
                or not pd.to_numeric(jobs["due_date_min"], errors="coerce").map(isfinite).all()
            ):
                raise ValueError("Reported benchmark requires explicit finite lot due dates.")
        service = evaluate_schedule_service_level(schedule)
        return {
            "makespan": service["makespan_hours"],
            "late_orders": service["late_orders"],
            "total_tardiness": service["total_tardiness_min"] / 60.0,
            "weighted_tardiness": service["weighted_tardiness"] / 60.0,
            "total_setup_time": service["total_setup_hours"],
        }

    def _get_setup(self, prev_prod: str | None, next_prod: str) -> float:
        if prev_prod is None:
            return 0.0
        return self.setup_matrix.get((prev_prod, next_prod), 0.5 if prev_prod != next_prod else 0.0)

    def run_heuristic(self, rule: str) -> BenchmarkResult:
        """Belirtilen kurala göre (FIFO, EDD, SPT) çizelge oluşturur ve metrikleri hesaplar."""
        started = perf_counter()
        tasks_sorted = list(self.tasks)
        if rule == "FIFO":
            # Doğal liste sırası / geliş sırası
            pass
        elif rule == "EDD":
            tasks_sorted.sort(key=lambda t: t.due_date)
        elif rule == "SPT":
            tasks_sorted.sort(key=lambda t: t.processing_time)
        elif rule == "Greedy":
            pass  # Select dynamically using current machine availability below.
        else:
            raise ValueError(f"Bilinmeyen kural: {rule}")

        # Makine bazında ardışık simülasyon
        machine_availability: dict[str, float] = {}
        machine_last_product: dict[str, str | None] = {}
        completion_times: dict[str, float] = {}

        total_setup_time = 0.0
        total_proc_time = sum(t.processing_time for t in self.tasks)

        while tasks_sorted:
            if rule == "Greedy":

                def finish_key(task):
                    setup = self._get_setup(machine_last_product.get(task.machine_id), task.product_id)
                    return (
                        max(machine_availability.get(task.machine_id, 0.0), task.release_date)
                        + setup
                        + task.processing_time,
                        setup,
                        task.due_date,
                        task.task_id,
                    )

                task = min(tasks_sorted, key=finish_key)
                tasks_sorted.remove(task)
            else:
                task = tasks_sorted.pop(0)
            m = task.machine_id
            curr_avail = machine_availability.get(m, 0.0)
            prev_prod = machine_last_product.get(m, None)

            setup = self._get_setup(prev_prod, task.product_id)
            start_time = max(curr_avail, task.release_date) + setup
            finish_time = start_time + task.processing_time

            total_setup_time += setup
            machine_availability[m] = finish_time
            machine_last_product[m] = task.product_id
            order = task.order_id or task.task_id
            completion_times[order] = max(completion_times.get(order, 0.0), finish_time)

        makespan = max(machine_availability.values()) if machine_availability else 0.0
        late_orders = 0
        total_tardiness = 0.0
        weighted_tardiness = 0.0

        for order, (due_date, priority_weight) in self.order_metadata.items():
            tardiness = max(0.0, completion_times[order] - due_date)
            if tardiness > 1e-4:
                late_orders += 1
                total_tardiness += tardiness
                weighted_tardiness += tardiness * priority_weight

        return BenchmarkResult(
            method=rule,
            makespan=makespan,
            late_orders=late_orders,
            total_tardiness=total_tardiness,
            total_setup_time=total_setup_time,
            total_processing_time=total_proc_time,
            weighted_tardiness=weighted_tardiness,
            wall_time_seconds=perf_counter() - started,
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
                if cpsat_result.status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
                    raise ValueError("Benchmark requires a feasible CP-SAT result.")
                if cpsat_result.makespan_min is None or cpsat_result.total_setup_min is None:
                    raise ValueError("Benchmark requires reported makespan and setup metrics.")
                makespan_hr = cpsat_result.makespan_min / 60.0
                setup_hr = cpsat_result.total_setup_min / 60.0
                weighted_hr = cpsat_result.total_tardiness_min
                results.append(
                    BenchmarkResult(
                        method="CP-SAT (Reported)",
                        makespan=makespan_hr,
                        late_orders=None,
                        total_tardiness=None,
                        weighted_tardiness=weighted_hr / 60.0 if weighted_hr is not None else None,
                        total_setup_time=setup_hr,
                        total_processing_time=sum(t.processing_time for t in self.tasks),
                    )
                )
            elif isinstance(cpsat_result, dict):
                results.append(
                    BenchmarkResult(
                        method="CP-SAT (Reported)",
                        makespan=float(cpsat_result["makespan"]),
                        late_orders=int(cpsat_result["late_orders"]) if "late_orders" in cpsat_result else None,
                        total_tardiness=float(cpsat_result["total_tardiness"])
                        if "total_tardiness" in cpsat_result
                        else None,
                        weighted_tardiness=float(cpsat_result["weighted_tardiness"])
                        if "weighted_tardiness" in cpsat_result
                        else None,
                        total_setup_time=float(cpsat_result["total_setup_time"]),
                        total_processing_time=sum(t.processing_time for t in self.tasks),
                    )
                )

        df = pd.DataFrame([r.to_dict() for r in results])
        return df
