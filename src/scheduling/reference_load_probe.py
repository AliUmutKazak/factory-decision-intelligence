"""Read-only G7 laboratory timing probe for one completed reference run.

Each repetition uses a fresh in-memory snapshot of the same source database.
This measures a reference workload, not a production service-level objective.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import warnings
from collections import Counter
from contextlib import redirect_stdout
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any

from src.scheduling.production_benchmark import production_benchmark

ACCEPTED = {"OPTIMAL", "FEASIBLE"}


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


def probe_reference_load(
    db_path: str | Path,
    baseline_run_id: str,
    *,
    repeats: int = 5,
    time_limit_seconds: float = 5.0,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Measure identical CP-SAT attempts without changing the source DB."""
    path = Path(db_path).resolve()
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if time_limit_seconds <= 0:
        raise ValueError("time limit must be positive")
    if not baseline_run_id:
        raise ValueError("baseline run ID is required")
    source_hash = _sha256(path)
    if expected_sha256 and source_hash.lower() != expected_sha256.lower():
        raise ValueError(f"source DB SHA-256 mismatch: {source_hash}")

    attempts: list[dict[str, Any]] = []
    input_hash: str | None = None
    code_hashes: dict[str, str] | None = None
    git_sha: str | None = None
    for index in range(repeats):
        started = perf_counter()
        with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
            warnings.filterwarnings(
                "ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning
            )
            result = production_benchmark(
                db_path=path,
                baseline_run_id=baseline_run_id,
                rules=("CP-SAT",),
                time_limit_seconds=time_limit_seconds,
            )
        elapsed = perf_counter() - started
        if len(result["cases"]) != 1 or result["cases"][0]["Method"] != "CP-SAT":
            raise RuntimeError("probe expected exactly one CP-SAT case")
        if input_hash is not None and result["input_hash"] != input_hash:
            raise RuntimeError("reference input changed between attempts")
        if code_hashes is not None and result["code_hashes"] != code_hashes:
            raise RuntimeError("solver code changed between attempts")
        input_hash = result["input_hash"]
        code_hashes = result["code_hashes"]
        git_sha = result["git_sha"]
        case = result["cases"][0]
        attempts.append(
            {
                "number": index + 1,
                "status": case["Status"],
                "attempt_wall_seconds": round(elapsed, 4),
                "solver_wall_seconds": case.get("Solve Time (s)"),
                "reason": case.get("Reason"),
            }
        )

    if _sha256(path) != source_hash:
        raise RuntimeError("source DB changed during the read-only probe")
    accepted = [row for row in attempts if row["status"] in ACCEPTED]
    solver_times = [float(row["solver_wall_seconds"]) for row in accepted]
    attempt_times = [float(row["attempt_wall_seconds"]) for row in attempts]
    return {
        "scope": "LAB_REFERENCE_SNAPSHOT_ONLY_NO_CUSTOMER_SLO",
        "measured_at_utc": datetime.now(UTC).isoformat(),
        "source_db_sha256": source_hash,
        "source_run_id": baseline_run_id,
        "input_hash": input_hash,
        "git_sha": git_sha,
        "code_hashes": code_hashes,
        "probe_code_sha256": _sha256(Path(__file__).resolve()),
        "ortools_version": version("ortools"),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "policy": "CP-SAT BALANCED via production_benchmark",
        "time_limit_seconds": time_limit_seconds,
        "repeats": repeats,
        "attempts": attempts,
        "summary": {
            "status_counts": dict(Counter(row["status"] for row in attempts)),
            "accepted_count": len(accepted),
            "no_accepted_solution_count": repeats - len(accepted),
            "attempt_wall_p50_seconds": _percentile(attempt_times, 0.5),
            "attempt_wall_p95_seconds": _percentile(attempt_times, 0.95),
            "accepted_solver_wall_p50_seconds": _percentile(solver_times, 0.5),
            "accepted_solver_wall_p95_seconds": _percentile(solver_times, 0.95),
            "percentile_method": "linear interpolation over sorted samples",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only repeated CP-SAT reference load probe")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--time-limit", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = probe_reference_load(
        args.db,
        args.baseline_run_id,
        repeats=args.repeats,
        time_limit_seconds=args.time_limit,
        expected_sha256=args.expected_sha256,
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
