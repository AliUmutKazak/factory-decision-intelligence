"""Combine isolated reference worker probes without hiding failed attempts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def collect(paths: list[Path]) -> dict:
    if not paths:
        raise ValueError("at least one probe report is required")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    identity_fields = ("source_db_sha256", "source_run_id", "input_hash", "code_hashes", "ortools_version", "platform")
    identity = {field: reports[0][field] for field in identity_fields}
    for report in reports:
        if any(report[field] != identity[field] for field in identity_fields):
            raise ValueError("reference input, solver code, or environment changed between probes")
        if report["repeats"] != 1:
            raise ValueError("matrix expects one isolated attempt per child process")
    cases = []
    groups = defaultdict(list)
    for report in reports:
        attempt = report["attempts"][0]
        meta = attempt.get("solver_metadata") or {}
        case = {
            "workers": report["experimental_num_workers"],
            "seed": report["experimental_random_seed"],
            "time_limit_seconds": report["time_limit_seconds"],
            "status": attempt["status"],
            "objective_value": meta.get("objective_value"),
            "best_objective_bound": meta.get("best_objective_bound"),
            "solver_wall_seconds": attempt["solver_wall_seconds"],
            "reason": attempt.get("reason"),
        }
        cases.append(case)
        groups[(case["time_limit_seconds"], case["workers"])].append(case)
    summary = [
        {
            "time_limit_seconds": limit,
            "workers": workers,
            "attempts": len(group),
            "accepted": sum(case["status"] in {"OPTIMAL", "FEASIBLE"} for case in group),
            "raw_objectives": [case["objective_value"] for case in group],
            "raw_bounds": [case["best_objective_bound"] for case in group],
        }
        for (limit, workers), group in sorted(groups.items())
    ]
    return {
        "scope": "SYNTHETIC_REFERENCE_SOLVER_PROBE_NO_FACTORY_SLO",
        "identity": identity,
        "cases": cases,
        "summary": summary,
        "note": "Small sample; no worker setting is certified or selected. No independent candidate audit in this probe.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
