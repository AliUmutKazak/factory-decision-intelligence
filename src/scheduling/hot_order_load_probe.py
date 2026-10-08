"""Reproducible G7 hot-order replay on an isolated sealed reference snapshot."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import sqlite3
import tempfile
import warnings
from collections import Counter
from contextlib import closing, redirect_stdout
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any

from src.contracts.schemas import HotOrderInjection, ScheduleSolverMetadata
from src.scheduling.hot_order_schedule_audit import audit_hot_order_schedule
from src.scheduling.what_if import WhatIfEngine
from src.utils.lineage import get_git_sha


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 4)


class _MeasuredWhatIfEngine(WhatIfEngine):
    def __init__(self, disk_db_path: str):
        super().__init__(disk_db_path)
        self.baseline_metadata: ScheduleSolverMetadata | None = None

    def run_baseline(
        self,
        mem_conn: sqlite3.Connection,
        run_id: str = "BASELINE",
        time_limit_seconds: float | None = None,
    ) -> ScheduleSolverMetadata:
        metadata = super().run_baseline(mem_conn, run_id, time_limit_seconds)
        self.baseline_metadata = metadata
        return metadata

    def load_active_baseline(self, mem_conn: sqlite3.Connection):
        metadata, schedule = super().load_active_baseline(mem_conn)
        self.baseline_metadata = metadata
        return metadata, schedule


def _stage_completed_reference(source: Path, run_id: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="fdi-g7-hot-order-", suffix=".db")
    os.close(descriptor)
    staged = Path(name)
    try:
        with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(staged)) as target:
                original.backup(target)
                if target.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status = 'ACTIVE'").fetchone()[0]:
                    raise ValueError("sealed reference must not already contain an ACTIVE run")
                updated = target.execute(
                    "UPDATE pipeline_runs SET status = 'ACTIVE' WHERE run_id = ? AND status = 'COMPLETED'",
                    (run_id,),
                )
                if updated.rowcount != 1:
                    raise ValueError("expected exactly one completed reference run")
                target.commit()
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def probe_hot_order_replay(
    source_path: str | Path,
    baseline_run_id: str,
    *,
    expected_sha256: str,
    repeats: int = 3,
    baseline_limit_seconds: float = 5.0,
    scenario_limit_seconds: float = 2.0,
    reuse_active_baseline: bool = False,
    scenario_dispatch_rule: str | None = None,
) -> dict[str, Any]:
    """Replay one labeled synthetic rush order without touching the source DB."""
    source = Path(source_path).resolve()
    if repeats < 1 or baseline_limit_seconds <= 0 or scenario_limit_seconds <= 0:
        raise ValueError("repeats and solver time limits must be positive")
    source_hash = _sha256(source)
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError(f"source DB SHA-256 mismatch: {source_hash}")
    hot_order = HotOrderInjection(
        order_id="G7-RUSH-P01-51",
        product_id="P01",
        quantity=51,
        due_date_min=1200,
        priority_weight=20,
    )
    attempts: list[dict[str, Any]] = []
    for number in range(1, repeats + 1):
        staged = _stage_completed_reference(source, baseline_run_id)
        staged_hash = _sha256(staged)
        engine = _MeasuredWhatIfEngine(str(staged))
        baseline_meta: ScheduleSolverMetadata | None = None
        scenario_meta: ScheduleSolverMetadata | None = None
        independent_audit: dict[str, Any] | None = None
        failure: Exception | None = None
        started = perf_counter()
        try:
            with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
                warnings.filterwarnings(
                    "ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning
                )
                baseline_meta, scenario_meta, _, scenario_schedule = engine.simulate_hot_order(
                    hot_order,
                    scenario_name=f"G7-HOT-{number}",
                    baseline_time_limit_seconds=baseline_limit_seconds,
                    scenario_time_limit_seconds=scenario_limit_seconds,
                    reuse_active_baseline=reuse_active_baseline,
                    scenario_dispatch_rule=scenario_dispatch_rule,
                )
                with closing(sqlite3.connect(f"{staged.as_uri()}?mode=ro", uri=True)) as audit_conn:
                    independent_audit = audit_hot_order_schedule(
                        audit_conn, baseline_run_id, hot_order, scenario_schedule
                    )
                if independent_audit["status"] != "ACCEPTED":
                    raise RuntimeError("independent hot-order schedule audit rejected the candidate")
        except (TimeoutError, RuntimeError, ValueError, sqlite3.Error) as exc:
            failure = exc
        finally:
            elapsed = perf_counter() - started
            try:
                if _sha256(staged) != staged_hash:
                    raise RuntimeError("staged ACTIVE source changed during what-if replay")
                with closing(sqlite3.connect(f"{staged.as_uri()}?mode=ro", uri=True)) as check:
                    active = check.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE'").fetchall()
                    if active != [(baseline_run_id,)]:
                        raise RuntimeError("staged ACTIVE run changed during what-if replay")
            finally:
                staged.unlink(missing_ok=True)

        baseline_meta = baseline_meta or engine.baseline_metadata
        failure_stage = (
            None
            if failure is None
            else "AUDIT"
            if scenario_meta is not None
            else "SCENARIO"
            if baseline_meta is not None
            else "BASELINE"
        )
        attempts.append(
            {
                "number": number,
                "baseline_status": baseline_meta.status.value if baseline_meta else "NO_ACCEPTED_SOLUTION",
                "baseline_solver_wall_seconds": (
                    baseline_meta.wall_time_seconds if baseline_meta and not reuse_active_baseline else None
                ),
                "baseline_original_solver_wall_seconds": (
                    baseline_meta.wall_time_seconds if baseline_meta and reuse_active_baseline else None
                ),
                "scenario_status": (
                    "REJECTED_BY_AUDIT"
                    if scenario_meta is not None and failure_stage == "AUDIT"
                    else scenario_meta.status.value
                    if scenario_meta
                    else "NO_ACCEPTED_SOLUTION"
                ),
                "scenario_solver_wall_seconds": scenario_meta.wall_time_seconds if scenario_meta else None,
                "scenario_makespan_min": scenario_meta.makespan_min if scenario_meta else None,
                "scenario_total_tardiness_min": scenario_meta.total_tardiness_min if scenario_meta else None,
                "scenario_total_setup_min": scenario_meta.total_setup_min if scenario_meta else None,
                "scenario_proven_optimal_within_scope": scenario_meta.proven_optimal if scenario_meta else None,
                "replay_wall_seconds": round(elapsed, 4),
                "failure_stage": failure_stage,
                "failure_type": type(failure).__name__ if failure else None,
                "failure_reason": str(failure) if failure else None,
                "independent_audit": independent_audit,
                "staged_active_unchanged": True,
            }
        )

    if _sha256(source) != source_hash:
        raise RuntimeError("sealed source DB changed during hot-order replay")
    accepted = [
        row
        for row in attempts
        if row["scenario_status"] in {"OPTIMAL", "FEASIBLE"}
        and row["independent_audit"] is not None
        and row["independent_audit"]["status"] == "ACCEPTED"
    ]
    replay_times = [float(row["replay_wall_seconds"]) for row in attempts]
    scenario_times = [float(row["scenario_solver_wall_seconds"]) for row in accepted]
    code_root = Path(__file__).resolve().parents[2]
    return {
        "scope": "LAB_SYNTHETIC_HOT_ORDER_REPLAY_NO_CUSTOMER_SLO",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "source_db_sha256": source_hash,
        "source_run_id": baseline_run_id,
        "staging_rule": "copy sealed COMPLETED run; mark only temporary copy ACTIVE",
        "git_sha": get_git_sha(),
        "code_hashes": {
            name: _sha256(code_root / name)
            for name in (
                "src/scheduling/hot_order_load_probe.py",
                "src/scheduling/hot_order_schedule_audit.py",
                "src/scheduling/what_if.py",
                "src/scheduling/schedule_cpsat.py",
                "src/contracts/schemas.py",
            )
        },
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "ortools_version": version("ortools"),
        "hot_order": hot_order.model_dump(mode="json"),
        "baseline_limit_seconds": None if reuse_active_baseline else baseline_limit_seconds,
        "baseline_source": "ACTIVE_SNAPSHOT" if reuse_active_baseline else "FRESH_SOLVE",
        "scenario_dispatch_rule": scenario_dispatch_rule,
        "optimization_scope": "FIXED_DISPATCH_SEQUENCE" if scenario_dispatch_rule else "FULL_PRODUCTION_MODEL",
        "scenario_limit_seconds": scenario_limit_seconds,
        "repeats": repeats,
        "attempts": attempts,
        "summary": {
            "scenario_status_counts": dict(Counter(row["scenario_status"] for row in attempts)),
            "scenario_accepted_count": len(accepted),
            "baseline_failure_count": sum(row["failure_stage"] == "BASELINE" for row in attempts),
            "scenario_failure_count": sum(row["failure_stage"] == "SCENARIO" for row in attempts),
            "audit_failure_count": sum(row["failure_stage"] == "AUDIT" for row in attempts),
            "baseline_timeout_count": sum(
                row["failure_stage"] == "BASELINE" and row["failure_type"] == "TimeoutError" for row in attempts
            ),
            "scenario_timeout_count": sum(
                row["failure_stage"] == "SCENARIO" and row["failure_type"] == "TimeoutError" for row in attempts
            ),
            "replay_wall_p50_seconds": _percentile(replay_times, 0.5),
            "replay_wall_p95_seconds": _percentile(replay_times, 0.95),
            "accepted_scenario_solver_wall_p50_seconds": _percentile(scenario_times, 0.5),
            "accepted_scenario_solver_wall_p95_seconds": _percentile(scenario_times, 0.95),
            "percentile_method": "linear interpolation over sorted samples",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only synthetic hot-order replay probe")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--baseline-limit", type=float, default=5.0)
    parser.add_argument("--scenario-limit", type=float, default=2.0)
    parser.add_argument("--reuse-active-baseline", action="store_true")
    parser.add_argument("--dispatch-rule", choices=("FIFO", "EDD", "SPT", "Greedy"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = probe_hot_order_replay(
        args.db,
        args.baseline_run_id,
        expected_sha256=args.expected_sha256,
        repeats=args.repeats,
        baseline_limit_seconds=args.baseline_limit,
        scenario_limit_seconds=args.scenario_limit,
        reuse_active_baseline=args.reuse_active_baseline,
        scenario_dispatch_rule=args.dispatch_rule,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
