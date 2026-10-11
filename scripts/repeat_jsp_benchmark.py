"""Repeat the identical sealed JSP subset without publishing an ACTIVE run."""

import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from src.scheduling.external_jsp_benchmark import SEALED_REFERENCE_SHA256, run_orlibrary_fixed_jsp


def repeat_benchmark(source, *, source_sha256, reference_db, reference_sha256, instances, repeats, time_limit):
    if repeats < 2:
        raise ValueError("at least two repetitions are required")
    if time_limit <= 0:
        raise ValueError("time_limit must be positive")
    matrix = []
    fingerprint = None
    for instance in instances:
        attempts = []
        for _ in range(repeats):
            result = run_orlibrary_fixed_jsp(
                source,
                instance,
                expected_sha256=source_sha256,
                reference_db_path=reference_db,
                expected_reference_sha256=reference_sha256,
                time_limit_seconds=time_limit,
            )
            identity = {
                "source_sha256": result["source_sha256"],
                "reference_db_sha256": result["reference_db_sha256"],
                "code_hashes": result["code_hashes"],
                "solver_version": result["solver_version"],
                "random_seed": result["random_seed"],
                "num_search_workers": result["num_search_workers"],
                "objective_policy": result["objective_policy"],
                "objective_weights": result["objective_weights"],
            }
            if fingerprint is None:
                fingerprint = identity
            elif identity != fingerprint:
                raise ValueError("benchmark identity changed between repetitions")
            attempts.append(
                {
                    "solver_status": result["solver_status"],
                    "proven_optimal": result["proven_optimal_for_model"],
                    "relative_makespan": result["relative_makespan"],
                    "best_objective_bound": result["best_objective_bound"],
                    "solver_wall_time_seconds": result["solver_wall_time_seconds"],
                    "independent_status": result["independent_check"]["status"],
                    "neutrality_checks": result["neutrality_checks"],
                    "comparable_static_jsp_subset": result["comparable_static_jsp_subset"],
                }
            )
        times = [item["solver_wall_time_seconds"] for item in attempts]
        matrix.append(
            {
                "instance": instance,
                "attempts": attempts,
                "accepted_count": sum(
                    item["solver_status"] in {"OPTIMAL", "FEASIBLE"}
                    and item["independent_status"] == "ACCEPTED"
                    and item["comparable_static_jsp_subset"]
                    for item in attempts
                ),
                "solver_time_p50_seconds": float(np.percentile(times, 50)),
                "solver_time_p95_seconds": float(np.percentile(times, 95)),
            }
        )
    return {
        "status": "PASS" if all(row["accepted_count"] == repeats for row in matrix) else "INCOMPLETE",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "environment": platform.platform(),
        "identity": fingerprint,
        "repeats_per_instance": repeats,
        "time_limit_seconds": time_limit,
        "instances": matrix,
        "scope": "REPEATED_LAB_STATIC_FIXED_MACHINE_JSP_ONLY_NO_CUSTOMER_KPI",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Repeat hash-pinned fixed-machine OR-Library cases")
    parser.add_argument("source", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--reference-db", type=Path, default=Path("artifacts/reference/factory.db"))
    parser.add_argument("--reference-sha256", default=SEALED_REFERENCE_SHA256)
    parser.add_argument("--instances", nargs="+", default=["ft06", "la01", "la02", "ft10"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = repeat_benchmark(
        args.source,
        source_sha256=args.sha256,
        reference_db=args.reference_db,
        reference_sha256=args.reference_sha256,
        instances=args.instances,
        repeats=args.repeats,
        time_limit=args.time_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(json.dumps({"status": report["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
