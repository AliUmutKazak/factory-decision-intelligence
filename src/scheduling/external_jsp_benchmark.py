"""Read-only bridge from an OR-Library fixed-machine JSP to the FDI solver.

This is a laboratory G8-T experiment. The source and sealed reference DB are
read into memory. Factory master data are replaced there with neutral benchmark
inputs; no customer data, ACTIVE version, or production artifact is published.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import sqlite3
import warnings
from contextlib import redirect_stdout
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import OBJECTIVE_POLICIES, SchedulingObjectivePolicy
from src.scheduling.fjsp_reference import check_fjsp_schedule, parse_orlibrary_jobshop1
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.what_if import NoCloseConnectionWrapper

MODEL_ORIGIN_MIN = 480
MODEL_REGULAR_END_MIN = 1440
SEALED_REFERENCE_SHA256 = "8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf"
_NEUTRAL_MASTER_TABLES = (
    "routing",
    "bom",
    "changeover_matrix",
    "machine_calendar",
    "machine_maintenance",
    "machine_state",
    "machines",
    "products",
    "materials",
)
_NEUTRAL_RUN_TABLES = (
    "sku_production_plan",
    "mrp_plan",
    "machine_capacity_plan",
    "machine_state_snapshot",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_orlibrary_fixed_jsp(
    source_path: str | Path,
    instance_name: str,
    *,
    expected_sha256: str,
    reference_db_path: str | Path,
    time_limit_seconds: float = 30.0,
    expected_reference_sha256: str = SEALED_REFERENCE_SHA256,
) -> dict[str, Any]:
    """Solve one fixed-machine instance and independently check its schedule."""
    source_path, reference_db_path = Path(source_path).resolve(), Path(reference_db_path).resolve()
    source_hash = _sha256(source_path)
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError(f"source SHA-256 mismatch: {source_hash}")
    instance = parse_orlibrary_jobshop1(source_path.read_text(encoding="utf-8"), instance_name)
    if any(len(choices) != 1 for job in instance.jobs for choices in job):
        raise ValueError("fixed-machine JSP requires exactly one machine per operation")
    reference_hash = _sha256(reference_db_path)
    if reference_hash.lower() != expected_reference_sha256.lower():
        raise ValueError(f"reference DB SHA-256 mismatch: {reference_hash}")
    code_root = Path(__file__).resolve().parents[2]
    code_hashes = {
        name: _sha256(code_root / name)
        for name in (
            "src/config.py",
            "src/scheduling/schedule_cpsat.py",
            "src/scheduling/calendar_service.py",
            "src/scheduling/fjsp_reference.py",
            "src/scheduling/external_jsp_benchmark.py",
        )
    }
    run_id = f"BENCH-ORLIB-{instance_name.upper()}"
    conn = sqlite3.connect(":memory:")
    try:
        source = sqlite3.connect(f"{reference_db_path.as_uri()}?mode=ro", uri=True)
        try:
            source.backup(conn)
        finally:
            source.close()
        for table in (*_NEUTRAL_MASTER_TABLES, *_NEUTRAL_RUN_TABLES):
            conn.execute(f"DELETE FROM {table}")

        for machine in range(1, instance.machine_count + 1):
            machine_id = f"BM{machine}"
            conn.execute(
                "INSERT INTO machines (machine_id, machine_name, base_power_kw, "
                "operating_cost_per_hour, max_daily_hours) VALUES (?, ?, 0, 0, 16)",
                (machine_id, machine_id),
            )
            conn.execute(
                "INSERT INTO machine_capacity_plan "
                "(period_week, machine_id, regular_capacity_hours, overtime_hours, "
                "total_capacity_hours, utilized_hours, utilization_pct, "
                "shadow_price_usd_per_hr, is_bottleneck, run_id) "
                "VALUES (1, ?, 96, 0, 96, 0, 0, 0, 'NO', ?)",
                (machine_id, run_id),
            )
            for day in range(6):
                conn.execute(
                    "INSERT INTO machine_calendar "
                    "(machine_id, day_of_week, shift_id, start_minute, end_minute, "
                    "available_hours, exception_type, is_available) "
                    "VALUES (?, ?, 'SHIFT_REGULAR', 480, 1440, 16, 'REGULAR', 1)",
                    (machine_id, day),
                )

        tasks = []
        plan = []
        for job_id, job in enumerate(instance.jobs, start=1):
            product_id, lot_id = f"BJ{job_id}", f"J{job_id}"
            conn.execute(
                "INSERT INTO products (product_id, family_id, product_name, unit_sale_price, "
                "holding_cost_per_week, late_penalty_per_day) VALUES (?, 'FAM_A', ?, 0, 0, 0)",
                (product_id, product_id),
            )
            plan.append(
                {
                    "product_id": product_id,
                    "lot_id": lot_id,
                    "due_date_min": 10000,
                    "priority_weight": 1,
                    "planned_batches": 1,
                    "planned_units": 1,
                }
            )
            for operation_seq, choices in enumerate(job, start=1):
                machine, duration = choices[0]
                machine_id = f"BM{machine}"
                conn.execute(
                    "INSERT INTO routing (product_id, operation_seq, machine_id, "
                    "processing_time_min, variable_kwh_per_unit) VALUES (?, ?, ?, ?, 0)",
                    (product_id, operation_seq, machine_id, duration),
                )
                tasks.append(
                    {
                        "task_id": f"J{job_id}-O{operation_seq}",
                        "lot_id": lot_id,
                        "product_id": product_id,
                        "machine_id": machine_id,
                        "operation_seq": operation_seq,
                        "duration_min": duration,
                        "due_date_min": 10000,
                        "priority_weight": 1,
                        "production_units": 1,
                        "batch_count": 1,
                        "batch_size_units": 1,
                        "release_time_min": MODEL_ORIGIN_MIN,
                    }
                )
        conn.commit()
        with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
            warnings.filterwarnings(
                "ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning
            )
            metadata = run_cpsat_scheduling(
                sku_plan=pd.DataFrame(plan),
                run_id=run_id,
                connection=NoCloseConnectionWrapper(conn),
                persist_outputs=False,
                task_override=pd.DataFrame(tasks),
                policy="THROUGHPUT_MAX",
                time_limit_seconds=time_limit_seconds,
            )
        schedule = pd.read_sql(
            "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY task_id", conn, params=(run_id,)
        )
        rows = [
            {
                "job_id": int(row.lot_id[1:]),
                "operation_seq": int(row.operation_seq),
                "machine_id": int(row.machine_id[2:]),
                "start": int(row.start_min) - MODEL_ORIGIN_MIN,
                "end": int(row.end_min) - MODEL_ORIGIN_MIN,
            }
            for row in schedule.itertuples()
        ]
        independent = check_fjsp_schedule(instance, rows)
        weights = OBJECTIVE_POLICIES[SchedulingObjectivePolicy.THROUGHPUT_MAX]
        neutral = {
            "pure_makespan_policy": bool(
                weights.makespan_weight > 0 and weights.setup_weight == 0 and weights.tardiness_weight == 0
            ),
            "zero_setup": bool(metadata.total_setup_min == 0 and (schedule.setup_before_min == 0).all()),
            "zero_tardiness": bool(metadata.total_tardiness_min == 0),
            "within_first_regular_shift": bool(
                not schedule.empty
                and (schedule.start_min >= MODEL_ORIGIN_MIN).all()
                and (schedule.end_min <= MODEL_REGULAR_END_MIN).all()
            ),
            "zero_overtime": bool(
                (schedule.production_overtime_minutes == 0).all() and (schedule.setup_overtime_minutes == 0).all()
            ),
            "all_operations_present": len(schedule) == instance.operation_count,
            "independent_feasibility": independent["status"] == "ACCEPTED",
        }
        comparable = all(neutral.values())
        return {
            "source": "OR-Library jobshop1",
            "source_url": "https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/jobshop1.txt",
            "instance_name": instance_name,
            "source_sha256": source_hash,
            "reference_db_sha256": reference_hash,
            "code_hashes": code_hashes,
            "source_unit": "abstract benchmark time unit",
            "model_unit_mapping": "one benchmark unit = one model minute; origin offset +480",
            "job_count": len(instance.jobs),
            "machine_count": instance.machine_count,
            "operation_count": instance.operation_count,
            "solver_status": metadata.status.value,
            "proven_optimal_for_model": metadata.proven_optimal,
            "solver_version": version("ortools"),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "objective_policy": "THROUGHPUT_MAX",
            "objective_weights": {
                "makespan": weights.makespan_weight,
                "setup": weights.setup_weight,
                "tardiness": weights.tardiness_weight,
            },
            "solver_time_limit_seconds": time_limit_seconds,
            "random_seed": metadata.random_seed,
            "num_search_workers": metadata.num_search_workers,
            "objective_value": metadata.objective_value,
            "best_objective_bound": metadata.best_objective_bound,
            "solver_wall_time_seconds": metadata.wall_time_seconds,
            "model_absolute_makespan_min": metadata.makespan_min,
            "relative_makespan": independent["makespan"],
            "independent_check": independent,
            "neutrality_checks": neutral,
            "comparable_static_jsp_subset": comparable,
            "scope": "LAB_STATIC_FIXED_MACHINE_JSP_ONLY_NO_CUSTOMER_KPI_NO_PUBLICATION",
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only OR-Library fixed-machine JSP benchmark")
    parser.add_argument("source", type=Path, help="Downloaded OR-Library jobshop1.txt")
    parser.add_argument("instance", help="Instance name, e.g. ft06")
    parser.add_argument("--sha256", required=True, help="Expected SHA-256 of the full source file")
    parser.add_argument(
        "--reference-db",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "artifacts/reference/factory.db",
    )
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--reference-sha256", default=SEALED_REFERENCE_SHA256)
    args = parser.parse_args()
    report = run_orlibrary_fixed_jsp(
        args.source,
        args.instance,
        expected_sha256=args.sha256,
        reference_db_path=args.reference_db,
        time_limit_seconds=args.time_limit,
        expected_reference_sha256=args.reference_sha256,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["comparable_static_jsp_subset"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
