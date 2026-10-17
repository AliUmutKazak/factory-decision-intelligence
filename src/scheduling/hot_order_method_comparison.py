"""Paired, synthetic single-arrival comparison on FDI's fixed-route model.

Each method receives the same sealed baseline, rush order, seed, worker count,
and solver time limit. A failed or independently rejected candidate contributes
to the failure count, never to quality or stability statistics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path
from typing import Any

from src.contracts.schemas import HotOrderInjection
from src.scheduling.hot_order_load_probe import probe_hot_order_replay
from src.utils.lineage import get_git_sha

METHODS = ("FULL", "FIFO", "EDD", "SPT")
METRICS = (
    "scenario_makespan_min",
    "scenario_total_tardiness_min",
    "scenario_total_setup_min",
    "scenario_solver_wall_seconds",
    "changed_existing_task_count",
    "absolute_existing_start_shift_min",
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_hash(path: Path) -> str:
    """Hash repository text as UTF-8 with LF, independent of checkout line endings."""
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower), 4)


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [row for row in rows if row["accepted"]]
    summary: dict[str, Any] = {
        "attempts": len(rows),
        "accepted": len(accepted),
        "failures": len(rows) - len(accepted),
        "status_counts": {
            status: sum(row["status"] == status for row in rows) for status in sorted({r["status"] for r in rows})
        },
        "metric_quantiles_accepted_only": {},
    }
    for metric in METRICS:
        values = [float(row[metric]) for row in accepted]
        summary["metric_quantiles_accepted_only"][metric] = {
            "p25": _quantile(values, 0.25),
            "median": _quantile(values, 0.5),
            "p75": _quantile(values, 0.75),
        }
    return summary


def compare_hot_order_methods(
    source_path: str | Path,
    baseline_run_id: str,
    *,
    expected_sha256: str,
    cases_path: str | Path,
    seeds: tuple[int, ...] = (7, 17, 42),
    methods: tuple[str, ...] = METHODS,
    scenario_limit_seconds: float = 2.0,
    workers: int = 1,
) -> dict[str, Any]:
    """Run paired single-arrival trials and retain every solver/audit failure."""
    source = Path(source_path).resolve()
    cases_file = Path(cases_path).resolve()
    if not seeds or len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
        raise ValueError("seeds must be unique nonnegative integers")
    if not methods or len(set(methods)) != len(methods) or any(method not in METHODS for method in methods):
        raise ValueError("methods must be unique members of FULL, FIFO, EDD, SPT")
    if scenario_limit_seconds <= 0 or workers < 1:
        raise ValueError("time limit and worker count must be positive")
    source_hash = _hash(source)
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("source DB SHA-256 mismatch")
    manifest_hash = _text_hash(cases_file)
    manifest = json.loads(cases_file.read_text(encoding="utf-8"))
    if manifest.get("source_type") != "SYNTHETIC":
        raise ValueError("comparison requires a SYNTHETIC case manifest")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    parsed: list[tuple[str, HotOrderInjection]] = []
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"].strip():
            raise ValueError("each case requires a case_id")
        case_id = case["case_id"]
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        parsed.append((case_id, HotOrderInjection.model_validate(case.get("hot_order"))))

    trials: list[dict[str, Any]] = []
    for case_id, order in parsed:
        for seed_index, seed in enumerate(seeds):
            # Rotate execution order so one method does not always run first.
            ordered_methods = methods[seed_index % len(methods) :] + methods[: seed_index % len(methods)]
            for method in ordered_methods:
                report = probe_hot_order_replay(
                    source,
                    baseline_run_id,
                    expected_sha256=expected_sha256,
                    hot_order=order,
                    repeats=1,
                    scenario_limit_seconds=scenario_limit_seconds,
                    reuse_active_baseline=True,
                    scenario_dispatch_rule=None if method == "FULL" else method,
                    scenario_seed=seed,
                    scenario_workers=workers,
                )
                attempt = report["attempts"][0]
                if (
                    attempt["scenario_solver_random_seed"] is not None
                    and attempt["scenario_solver_random_seed"] != seed
                ):
                    raise RuntimeError("solver used a different random seed than requested")
                if attempt["scenario_solver_workers"] is not None and attempt["scenario_solver_workers"] != workers:
                    raise RuntimeError("solver used a different worker count than requested")
                accepted = (
                    attempt["scenario_status"] in {"OPTIMAL", "FEASIBLE"}
                    and attempt["independent_audit"] is not None
                    and attempt["independent_audit"]["status"] == "ACCEPTED"
                    and attempt["stability"] is not None
                )
                stability = attempt["stability"] if accepted else None
                trials.append(
                    {
                        "case_id": case_id,
                        "hot_order": order.model_dump(mode="json"),
                        "seed": seed,
                        "method": method,
                        "status": attempt["scenario_status"],
                        "accepted": accepted,
                        "failure_stage": attempt["failure_stage"],
                        "failure_type": attempt["failure_type"],
                        "failure_reason": attempt["failure_reason"],
                        "independent_audit": attempt["independent_audit"],
                        "solver_random_seed": seed,
                        "solver_workers": workers,
                        "measured_solver_random_seed": attempt["scenario_solver_random_seed"],
                        "measured_solver_workers": attempt["scenario_solver_workers"],
                        "replay_wall_seconds": attempt["replay_wall_seconds"],
                        "measured_solver_wall_seconds": attempt["scenario_solver_wall_seconds"],
                        "optimization_scope": "FULL_PRODUCTION_MODEL"
                        if method == "FULL"
                        else "FIXED_DISPATCH_SEQUENCE",
                        "scenario_makespan_min": attempt["scenario_makespan_min"] if accepted else None,
                        "scenario_total_tardiness_min": attempt["scenario_total_tardiness_min"] if accepted else None,
                        "scenario_total_setup_min": attempt["scenario_total_setup_min"] if accepted else None,
                        "scenario_solver_wall_seconds": attempt["scenario_solver_wall_seconds"] if accepted else None,
                        "changed_existing_task_count": stability["changed_existing_task_count"] if stability else None,
                        "absolute_existing_start_shift_min": (
                            stability["absolute_existing_start_shift_min"] if stability else None
                        ),
                        "baseline_task_count": stability["baseline_task_count"] if stability else None,
                        "new_task_count": stability["new_task_count"] if stability else None,
                    }
                )
    if _hash(source) != source_hash or _text_hash(cases_file) != manifest_hash:
        raise RuntimeError("sealed source or case manifest changed during comparison")
    return {
        "scope": "ADAPTED_SYNTHETIC_FIXED_ROUTE_SINGLE_ARRIVAL_NO_FACTORY_VALIDATION",
        "event_time_min": 0,
        "future_event_information": "NONE; each trial has one declared arrival at time zero",
        "baseline_source": "SAME_SEALED_ACTIVE_SNAPSHOT",
        "source_db_sha256": source_hash,
        "source_run_id": baseline_run_id,
        "cases_manifest_sha256": manifest_hash,
        "cases_manifest_name": cases_file.name,
        "code_sha256": {
            str(path.relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/"): _text_hash(path)
            for path in (
                Path(__file__).resolve(),
                Path(__file__).with_name("hot_order_load_probe.py").resolve(),
                Path(__file__).with_name("what_if.py").resolve(),
                Path(__file__).with_name("schedule_cpsat.py").resolve(),
                Path(__file__).with_name("hot_order_schedule_audit.py").resolve(),
            )
        },
        "git_sha": get_git_sha(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "ortools_version": version("ortools"),
        "seeds": list(seeds),
        "methods": list(methods),
        "workers_per_trial": workers,
        "scenario_limit_seconds_per_trial": scenario_limit_seconds,
        "metric_policy": "quantiles use independently accepted candidates only; failures remain in denominator",
        "quantile_method": "linear interpolation over sorted samples",
        "trials": trials,
        "summary": {
            case_id: {
                method: _summarize([row for row in trials if row["case_id"] == case_id and row["method"] == method])
                for method in methods
            }
            for case_id, _ in parsed
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Paired synthetic fixed-route hot-order comparison")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=[7, 17, 42])
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--scenario-limit", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare_hot_order_methods(
        args.db,
        args.baseline_run_id,
        expected_sha256=args.expected_sha256,
        cases_path=args.cases,
        seeds=tuple(args.seeds),
        methods=tuple(args.methods),
        scenario_limit_seconds=args.scenario_limit,
        workers=args.workers,
    )
    rendered = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
