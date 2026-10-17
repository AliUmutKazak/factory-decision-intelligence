"""Test a hard completion deadline on an immutable synthetic run snapshot.

An INFEASIBLE result proves only that this exact model and input cannot finish
every modeled operation by that deadline. It does not establish a real site's
physical capacity or service level.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import warnings
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

from src.planning.plan_schedule_consistency import compare_week_one
from src.scheduling.production_benchmark import production_benchmark


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(
    db_path: Path,
    run_id: str,
    expected_sha256: str,
    deadlines: list[int],
    time_limit_seconds: float,
    workers: int,
    seed: int,
) -> dict:
    source_hash = sha256_file(db_path)
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError(f"source DB SHA-256 mismatch: {source_hash}")
    if not deadlines or any(deadline <= 0 for deadline in deadlines):
        raise ValueError("positive deadlines are required")

    cases = []
    input_hash = None
    code_hashes = None
    for deadline in deadlines:
        with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
            warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy connectable")
            result = production_benchmark(
                db_path=db_path,
                baseline_run_id=run_id,
                rules=("CP-SAT",),
                time_limit_seconds=time_limit_seconds,
                experimental_num_workers=workers,
                experimental_random_seed=seed,
                experimental_completion_deadline_min=deadline,
            )
        if input_hash is not None and result["input_hash"] != input_hash:
            raise RuntimeError("input changed between deadlines")
        if code_hashes is not None and result["code_hashes"] != code_hashes:
            raise RuntimeError("solver code changed between deadlines")
        input_hash = result["input_hash"]
        code_hashes = result["code_hashes"]
        outcome = result["cases"][0]
        reason = outcome.get("Reason")
        if outcome["Status"] in {"OPTIMAL", "FEASIBLE"}:
            schedule = pd.DataFrame(outcome["schedule"])
            with sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True) as conn:
                plan = pd.read_sql("SELECT * FROM sku_production_plan WHERE run_id = ?", conn, params=(run_id,))
            plan["run_id"] = schedule["run_id"].iloc[0]
            reconciliation = compare_week_one(plan, schedule)
            cases.append(
                {
                    "deadline_min": deadline,
                    "solver_status": outcome["Status"],
                    "interpretation": "FEASIBLE_SCHEDULE_EXISTS_UNDER_MODEL",
                    "solver_metadata": outcome["solver_metadata"],
                    "max_end_min": int(schedule["end_min"].max()),
                    "week_one_planned_units": reconciliation["planned_units"],
                    "week_one_finished_units": reconciliation["scheduled_to_finish_by_week_end_units"],
                }
            )
        else:
            proven_infeasible = bool(reason and "Durum: INFEASIBLE" in reason)
            cases.append(
                {
                    "deadline_min": deadline,
                    "solver_status": "INFEASIBLE" if proven_infeasible else "NO_ACCEPTED_SOLUTION",
                    "interpretation": "PROVEN_INFEASIBLE_UNDER_MODEL" if proven_infeasible else "INCONCLUSIVE",
                    "reason": reason,
                }
            )

    if sha256_file(db_path) != source_hash:
        raise RuntimeError("source DB changed during read-only probe")
    return {
        "scope": "SEALED_SYNTHETIC_MODEL_ONLY_NOT_FACTORY_CAPACITY",
        "source_db_sha256": source_hash,
        "source_run_id": run_id,
        "input_hash": input_hash,
        "code_hashes": code_hashes,
        "probe_code_sha256": sha256_file(Path(__file__).resolve()),
        "time_limit_seconds": time_limit_seconds,
        "num_workers": workers,
        "random_seed": seed,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--deadlines", nargs="+", type=int, required=True)
    parser.add_argument("--time-limit", type=float, default=20.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = probe(args.db, args.run_id, args.expected_sha256, args.deadlines, args.time_limit, args.workers, args.seed)
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
