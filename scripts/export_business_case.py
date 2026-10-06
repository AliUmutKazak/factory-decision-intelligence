"""Export an auditable benchmark, B2MML demo and parameterized ROI case."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.contracts.b2mml import schedule_to_xml
from src.contracts.schemas import ProductionScheduleTask, ScheduleResult
from src.economics.business_case import modeled_roi
from src.scheduling.production_benchmark import production_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db")
    parser.add_argument("--baseline-run-id")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--cycles-per-year", type=float, default=50)
    parser.add_argument("--realization-fraction", type=float, default=0)
    parser.add_argument("--implementation-cost", type=float, default=0)
    parser.add_argument("--annual-operating-cost", type=float, default=0)
    parser.add_argument(
        "--origin",
        default="2026-10-05T00:00:00+00:00",
        help="Timezone-aware Monday factory epoch; demo default is explicitly synthetic",
    )
    args = parser.parse_args()
    report = production_benchmark(args.db, baseline_run_id=args.baseline_run_id, time_limit_seconds=args.seconds)
    accepted = {case["Method"]: case for case in report["cases"] if case["Status"] in {"FEASIBLE", "OPTIMAL"}}
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report["solver_time_limit_seconds"] = args.seconds
    report["factory_time_origin"] = args.origin
    report["customer_pilot_executed"] = False
    if "EDD" in accepted:
        report["roi_projections_vs_edd"] = {
            name: modeled_roi(
                accepted["EDD"]["Total Cost"],
                case["Total Cost"],
                cycles_per_year=args.cycles_per_year,
                realization_fraction=args.realization_fraction,
                implementation_cost=args.implementation_cost,
                annual_operating_cost=args.annual_operating_cost,
            )
            for name, case in accepted.items()
            if name in {"CP-SAT", "COST_OPTIMIZED"}
        }
    rows = [
        {key: value for key, value in case.items() if key not in {"schedule", "cost_breakdown", "solver_metadata"}}
        for case in report["cases"]
    ]
    pd.DataFrame(rows).to_csv(output / "comparison.csv", index=False)
    for name in ("CP-SAT", "COST_OPTIMIZED"):
        if name not in accepted:
            continue
        case = accepted[name]
        result = ScheduleResult(
            status=case["Status"],
            makespan_hours=case["Makespan (hr)"],
            total_cost_eur=case["Total Cost"],
            tasks=[ProductionScheduleTask(**{**task, "task_id": str(task["task_id"])}) for task in case["schedule"]],
        )
        xml = schedule_to_xml(
            result, origin=datetime.fromisoformat(args.origin), schedule_id=f"{report['baseline_run_id']}-{name}"
        )
        (output / f"{name.lower()}_schedule.xml").write_text(xml)
    (output / "benchmark.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    summary = [
        "# Measured factory demo business case",
        "",
        f"Baseline: `{report['baseline_run_id']}`.",
        f"Physical input fingerprint: `{report['input_hash']}`.",
        "",
        "All accepted schedules share the production calendar, maintenance, routes, setup, material availability, overtime and committed movement constraints.",
        "Dispatch baselines select machine order and use CP-SAT to place intervals; runtime includes a solver and is not a pure heuristic speed comparison.",
        "",
        "| Method | Status | Makespan h | Weighted tardiness h | Cost | Currency |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        summary.append(
            f"| {row['Method']} | {row['Status']} | {row.get('Makespan (hr)', 'unknown')} | {row.get('Weighted Tardiness (hr)', 'unknown')} | {row.get('Total Cost', 'unknown')} | {row.get('Currency', 'unknown')} |"
        )
    summary += [
        "",
        f"Weighted tardiness improvement versus EDD: {report['weighted_tardiness_improvement_vs_edd_pct']}% (undefined if EDD is zero or unavailable).",
        "",
        "ROI projections and their explicit assumptions are in benchmark.json. Default realization is zero until customer financial evidence exists.",
        "These are modeled manufacturing costs and analytic energy estimates. No actual customer pilot, verified cash saving, meter telemetry or vendor endpoint acceptance is claimed.",
        "B2MML schedules are validated against the unmodified MESA 0701 XSDs. The supplied time epoch is recorded separately.",
    ]
    (output / "business-case.md").write_text("\n".join(summary) + "\n")
    print(f"Exported {len(rows)} benchmark cases from {report['baseline_run_id']} to {output}")


if __name__ == "__main__":
    main()
