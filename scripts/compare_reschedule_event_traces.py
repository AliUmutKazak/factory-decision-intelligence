"""Compare fixed-route dispatch policies on paired chronological synthetic traces.

Every method starts each trace from a fresh sealed-reference copy, receives
events only in time order, uses the same CP-SAT defaults, and retains failures.
This is laboratory evidence, not a factory service or benefit estimate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.probe_reschedule_event_trace import _code_hash, _load_events, _sha256, probe


def compare(
    reference_db: Path,
    expected_sha256: str,
    baseline_run_id: str,
    traces: list[Path],
    methods: list[str],
) -> dict:
    if len(traces) < 2 or len(set(path.resolve() for path in traces)) != len(traces):
        raise ValueError("comparison needs at least two distinct event traces")
    if methods != ["FULL", "EDD"]:
        raise ValueError("predefined paired methods must be FULL and EDD")
    source_hash = _sha256(reference_db)
    if source_hash != expected_sha256.lower():
        raise ValueError("sealed reference database SHA-256 mismatch")

    repo_root = Path(__file__).resolve().parents[1]
    trace_rows = []
    for trace_index, trace in enumerate(traces):
        expected_events = _load_events(trace)
        order = methods if trace_index % 2 == 0 else list(reversed(methods))
        outcomes = {}
        for method in order:
            outcomes[method] = probe(
                reference_db,
                expected_sha256,
                baseline_run_id,
                trace,
                force_full_solver=True,
                dispatch_rule=None if method == "FULL" else method,
            )
        left = outcomes["FULL"]["attempts"]
        right = outcomes["EDD"]["attempts"]
        paired = []
        for event_index, event in enumerate(expected_events):
            full = left[event_index] if event_index < len(left) else None
            edd = right[event_index] if event_index < len(right) else None
            if any(outcome is not None and outcome["event"]["event_id"] != event.event_id for outcome in (full, edd)):
                raise RuntimeError("paired methods did not receive the same event")
            eligible = bool(full and edd and full["accepted"] and edd["accepted"])
            row = {
                "event_id": event.event_id,
                "both_accepted": eligible,
                "method_status": {
                    method: "NOT_ATTEMPTED_AFTER_PRIOR_FAILURE"
                    if outcome is None
                    else ("ACCEPTED" if outcome["accepted"] else "FAILED")
                    for method, outcome in (("FULL", full), ("EDD", edd))
                },
            }
            if eligible:
                full_meta, edd_meta = full["solver_metadata"], edd["solver_metadata"]
                settings = ("time_limit_seconds", "random_seed", "num_search_workers")
                if any(full_meta[key] != edd_meta[key] for key in settings):
                    raise RuntimeError("paired methods used unequal solver settings")
                row["matched_solver_settings"] = {key: full_meta[key] for key in settings}
                row["metrics"] = {
                    method: {
                        "makespan_min": outcome["solver_metadata"]["makespan_min"],
                        "weighted_tardiness_min": outcome["solver_metadata"]["total_tardiness_min"],
                        "setup_min": outcome["solver_metadata"]["total_setup_min"],
                        "moved_tasks": outcome["stability"]["rescheduled_tasks_count"],
                        "frozen_tasks": outcome["stability"]["frozen_tasks_count"],
                        "solver_wall_seconds": outcome["solver_metadata"]["wall_time_seconds"],
                        "end_to_end_seconds": outcome["elapsed_seconds"],
                    }
                    for method, outcome in (("FULL", full), ("EDD", edd))
                }
            paired.append(row)
        trace_rows.append(
            {
                "trace": str(trace.resolve()),
                "trace_sha256": _sha256(trace),
                "method_order": order,
                "outcomes": outcomes,
                "paired_events": paired,
            }
        )

    if _sha256(reference_db) != source_hash:
        raise RuntimeError("sealed reference changed during paired replay")
    source_paths = (
        "scripts/compare_reschedule_event_traces.py",
        "scripts/probe_reschedule_event_trace.py",
        "src/scheduling/rescheduler.py",
        "src/scheduling/schedule_cpsat.py",
        "src/scheduling/reschedule_candidate_audit.py",
    )
    return {
        "experiment_type": "paired chronological synthetic fixed-route comparison",
        "source_db_sha256": source_hash,
        "baseline_run_id": baseline_run_id,
        "methods": methods,
        "code_sha256": {name: _code_hash(repo_root / name) for name in source_paths},
        "traces": trace_rows,
        "paired_accepted_event_count": sum(
            row["both_accepted"] for trace in trace_rows for row in trace["paired_events"]
        ),
        "planned_event_pair_count": sum(len(trace["paired_events"]) for trace in trace_rows),
        "attempted_trace_count": len(traces),
        "evidence_scope": (
            f"{len(traces)} synthetic traces only; no site actuals, service guarantee or general method ranking"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--traces", type=Path, nargs="+", required=True)
    parser.add_argument("--methods", nargs="+", default=["FULL", "EDD"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.db, args.sha256, args.baseline_run_id, args.traces, args.methods)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"paired_accepted_event_count": result["paired_accepted_event_count"]}))


if __name__ == "__main__":
    main()
