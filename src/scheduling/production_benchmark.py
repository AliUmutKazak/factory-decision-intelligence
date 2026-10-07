"""Equivalent-physical-constraint dispatch benchmarks on an immutable snapshot.

FIFO/EDD/SPT/Greedy select machine sequences. CP-SAT places those sequences under
the *same* routing, setup, calendar, maintenance, material and overtime model.
These are solver-placed dispatch baselines, not claimed pure heuristic runtimes.
Failed/unknown cases carry no fabricated KPI or improvement percentage.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

from src.config import ECONOMIC_CONFIG, get_runtime_paths
from src.economics.schedule_cost import evaluate_schedule_cost
from src.scheduling.benchmark import SchedulingBenchmarkSuite
from src.scheduling.maintenance import MaintenanceWindow
from src.scheduling.model_context import load_model_context
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.what_if import NoCloseConnectionWrapper
from src.utils.db import clone_run_inputs, get_active_run_id
from src.utils.lineage import get_git_sha


def production_benchmark(
    db_path=None,
    rules=("CP-SAT", "FIFO", "EDD", "SPT", "Greedy", "COST_OPTIMIZED"),
    time_limit_seconds=None,
    baseline_run_id=None,
):
    path = Path(db_path or get_runtime_paths()["db_path"])
    if not path.is_file():
        raise ValueError("Benchmark requires an existing ACTIVE database.")
    snapshot = sqlite3.connect(":memory:")
    with sqlite3.connect(path) as source:
        source.backup(snapshot)
    try:
        baseline = baseline_run_id or get_active_run_id(snapshot)
        if baseline_run_id:
            row = snapshot.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (baseline,)).fetchone()
            if not row or row[0] not in {"ACTIVE", "COMPLETED", "SUPERSEDED"}:
                raise ValueError("An explicit benchmark baseline must be a successfully completed version.")
        context = load_model_context(snapshot, baseline)
        tasks = pd.read_sql(
            "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY task_id", snapshot, params=(baseline,)
        )
        if tasks.empty:
            raise ValueError("Benchmark requires nonempty ACTIVE tasks.")
        frozen = {
            str(row.task_id): (str(row.machine_id), float(row.start_min), float(row.end_min))
            for row in tasks.itertuples()
            if row.schedule_state == "FROZEN" or row.execution_status in {"IN_PROGRESS", "COMPLETED"}
        }
        frozen.update(context["frozen_positions"])
        signature_tables_context = context
        signature_tables = {}
        for table in (
            "machines",
            "routing",
            "changeover_matrix",
            "bom",
            "materials",
            "machine_calendar",
            "machine_maintenance",
            "machine_capacity_plan",
            "mrp_plan",
            "machine_state_snapshot",
        ):
            columns = {row[1] for row in snapshot.execute(f"PRAGMA table_info({table})")}
            if not columns:
                continue
            data = pd.read_sql(
                f"SELECT * FROM {table}" + (" WHERE run_id = ?" if "run_id" in columns else ""),
                snapshot,
                params=(baseline,) if "run_id" in columns else None,
            )
            signature_tables[table] = data.to_dict("records")
        signature_tables["tasks"] = tasks.to_dict("records")
        signature_tables["model_context"] = signature_tables_context
        digest = hashlib.sha256(json.dumps(signature_tables, sort_keys=True, default=str).encode()).hexdigest()
        code_root = Path(__file__).resolve().parents[2]
        code_hashes = {
            name: hashlib.sha256((code_root / name).read_bytes()).hexdigest()
            for name in (
                "src/config.py",
                "src/scheduling/schedule_cpsat.py",
                "src/scheduling/dispatch.py",
                "src/scheduling/production_benchmark.py",
                "src/scheduling/monetary_objective.py",
                "src/scheduling/model_context.py",
                "src/scheduling/calendar_service.py",
                "src/scheduling/analytics_schema.py",
                "src/scheduling/maintenance.py",
                "src/economics/schedule_cost.py",
                "src/economics/cost_to_serve.py",
                "src/contracts/schemas.py",
                "src/utils/db.py",
            )
        }
        cases = []
        for index, rule in enumerate(rules):
            if rule not in {"CP-SAT", "FIFO", "EDD", "SPT", "Greedy", "COST_OPTIMIZED"}:
                raise ValueError(f"Unknown benchmark policy: {rule}")
            private = sqlite3.connect(":memory:")
            snapshot.backup(private)
            case_run = f"BENCH-{baseline}-{index}"
            clone_run_inputs(private, baseline, case_run)
            try:
                metadata = run_cpsat_scheduling(
                    run_id=case_run,
                    connection=NoCloseConnectionWrapper(private),
                    persist_outputs=False,
                    task_override=tasks,
                    reference_schedule=tasks,
                    frozen_task_positions=frozen,
                    earliest_start_min=context["earliest_start_min"],
                    flexible_task_windows=context["flexible_windows"],
                    maintenance_overrides=[MaintenanceWindow(**window) for window in context["maintenance_overrides"]],
                    dispatch_rule=None if rule in {"CP-SAT", "COST_OPTIMIZED"} else rule,
                    policy="COST_OPTIMIZED" if rule == "COST_OPTIMIZED" else "BALANCED",
                    time_limit_seconds=time_limit_seconds,
                )
                result = pd.read_sql("SELECT * FROM production_schedule WHERE run_id = ?", private, params=(case_run,))
                metrics = SchedulingBenchmarkSuite.reported_schedule_metrics(result)
                cost = evaluate_schedule_cost(private, result, case_run)
                cases.append(
                    {
                        "Method": rule,
                        "Status": metadata.status.value,
                        "Optimality Scope": "fixed dispatch sequence"
                        if rule in {"FIFO", "EDD", "SPT", "Greedy"}
                        else "full production model",
                        "Physical Constraints": digest,
                        "Makespan (hr)": metrics["makespan"],
                        "Late Lots": metrics["late_orders"],
                        "Total Tardiness (hr)": metrics["total_tardiness"],
                        "Weighted Tardiness (hr)": metrics["weighted_tardiness"],
                        "Total Setup Time (hr)": metrics["total_setup_time"],
                        "Solve Time (s)": metadata.wall_time_seconds,
                        "Total Cost": cost["total_manufacturing_cost"],
                        "Currency": cost["currency"],
                        "cost_breakdown": cost,
                        "solver_metadata": metadata.model_dump(mode="json"),
                        "schedule": result.to_dict("records"),
                    }
                )
            except (RuntimeError, TimeoutError) as exc:
                cases.append(
                    {
                        "Method": rule,
                        "Status": "NO_ACCEPTED_SOLUTION",
                        "Physical Constraints": digest,
                        "Reason": str(exc),
                    }
                )
            finally:
                private.close()
        accepted = {case["Method"]: case for case in cases if case["Status"] in {"OPTIMAL", "FEASIBLE"}}
        improvement = None
        if "CP-SAT" in accepted and "EDD" in accepted:
            edd = accepted["EDD"]["Weighted Tardiness (hr)"]
            if edd > 0:
                improvement = 100 * (edd - accepted["CP-SAT"]["Weighted Tardiness (hr)"]) / edd
        return {
            "baseline_run_id": baseline,
            "input_hash": digest,
            "git_sha": get_git_sha(),
            "code_hashes": code_hashes,
            "economic_parameters": ECONOMIC_CONFIG.model_dump(mode="json"),
            "baseline_definition": "dispatch-selected machine sequences placed by the production CP-SAT model",
            "cases": cases,
            "weighted_tardiness_improvement_vs_edd_pct": improvement,
        }
    finally:
        snapshot.close()
