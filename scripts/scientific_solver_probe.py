"""Isolated, hash-pinned worker/seed probe for the fixed-machine JSP subset.

Each attempt runs in a child process so a native solver crash is recorded rather
than terminating the matrix. Results are laboratory evidence, not a factory SLO.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from src.scheduling.external_jsp_benchmark import SEALED_REFERENCE_SHA256


def probe(
    source: Path,
    source_sha256: str,
    reference_db: Path,
    instances: list[str],
    workers: list[int],
    seeds: list[int],
    time_limit: float,
) -> dict:
    source = source.resolve()
    reference_db = reference_db.resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha256.lower():
        raise ValueError("source SHA-256 mismatch")
    if hashlib.sha256(reference_db.read_bytes()).hexdigest() != SEALED_REFERENCE_SHA256:
        raise ValueError("sealed reference DB SHA-256 mismatch")
    if time_limit <= 0 or not instances or not workers or not seeds:
        raise ValueError("time limit, instances, workers and seeds are required")
    if min(workers) < 1 or min(seeds) < 0 or max(workers) > (os.cpu_count() or 1):
        raise ValueError("workers must fit local logical CPUs; seeds must be nonnegative")
    attempts = []
    code_identity = None
    for instance in instances:
        for worker_count in workers:
            for seed in seeds:
                command = [
                    sys.executable,
                    "-m",
                    "src.scheduling.external_jsp_benchmark",
                    str(source),
                    instance,
                    "--sha256",
                    source_sha256,
                    "--reference-db",
                    str(reference_db),
                    "--time-limit",
                    str(time_limit),
                    "--num-workers",
                    str(worker_count),
                    "--random-seed",
                    str(seed),
                ]
                row = {"instance": instance, "workers": worker_count, "seed": seed}
                try:
                    completed = subprocess.run(
                        command, capture_output=True, text=True, timeout=time_limit + 45, check=False
                    )
                    row["exit_code"] = completed.returncode
                    if completed.stdout.strip():
                        try:
                            result = json.loads(completed.stdout)
                        except json.JSONDecodeError:
                            result = None
                    else:
                        result = None
                    if result is not None:
                        if (
                            result["source_sha256"] != source_sha256.lower()
                            or result["reference_db_sha256"] != SEALED_REFERENCE_SHA256
                        ):
                            raise ValueError("child process used a different input")
                        if code_identity is None:
                            code_identity = result["code_hashes_normalized_lf"]
                        elif code_identity != result["code_hashes_normalized_lf"]:
                            raise ValueError("solver code changed during probe")
                        row.update(
                            {
                                key: result.get(key)
                                for key in (
                                    "solver_status",
                                    "solver_version",
                                    "relative_makespan",
                                    "objective_value",
                                    "best_objective_bound",
                                    "solver_wall_time_seconds",
                                    "comparable_static_jsp_subset",
                                    "code_hashes_normalized_lf",
                                )
                            }
                        )
                        row["independent_status"] = result["independent_check"]["status"]
                        row["actual_workers"] = result["num_search_workers"]
                        row["actual_seed"] = result["random_seed"]
                    if result is None or completed.returncode:
                        row["error_tail"] = completed.stderr[-2000:]
                except subprocess.TimeoutExpired as exc:
                    row.update({"exit_code": None, "timeout": True, "error_tail": str(exc)})
                attempts.append(row)
    summary = []
    for instance in instances:
        for worker_count in workers:
            group = [row for row in attempts if row["instance"] == instance and row["workers"] == worker_count]
            accepted = [
                row
                for row in group
                if row.get("solver_status") in {"FEASIBLE", "OPTIMAL"}
                and row.get("independent_status") == "ACCEPTED"
                and row.get("comparable_static_jsp_subset")
                and row.get("exit_code") == 0
                and row.get("actual_workers") == worker_count
                and row.get("actual_seed") == row["seed"]
            ]
            values = sorted(row["relative_makespan"] for row in accepted)
            summary.append(
                {
                    "instance": instance,
                    "workers": worker_count,
                    "attempts": len(group),
                    "accepted": len(accepted),
                    "exit_codes": dict(Counter(str(row.get("exit_code")) for row in group)),
                    "raw_makespans": values,
                    "median_makespan": median(values) if values else None,
                }
            )
    return {
        "scope": "LAB_FIXED_MACHINE_JSP_ONLY_NO_FACTORY_SLO",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "source_sha256": source_sha256.lower(),
        "reference_db_sha256": SEALED_REFERENCE_SHA256,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "time_limit_seconds": time_limit,
        "code_hashes_normalized_lf": code_identity,
        "summary": summary,
        "attempts": attempts,
        "note": "All observations are raw. No tail percentile is estimated from small samples.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--reference-db", type=Path, default=Path("artifacts/reference/factory.db"))
    parser.add_argument("--instances", nargs="+", default=["ft06", "ft10"])
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 2])
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 42, 73])
    parser.add_argument("--time-limit", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe(
        args.source, args.sha256, args.reference_db, args.instances, args.workers, args.seeds, args.time_limit
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": result["summary"]}, ensure_ascii=False))
    return 0 if all(row["accepted"] == row["attempts"] for row in result["summary"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
