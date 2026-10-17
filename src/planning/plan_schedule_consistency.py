"""Read-only comparison of week-one SKU targets and scheduled final operations.

This measures scheduled completion by the seven-day boundary. It is not an
actual production, service-level, or LP infeasibility measurement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

WEEK_ONE_END_MIN = 7 * 24 * 60


def compare_week_one(sku_plan: pd.DataFrame, schedule: pd.DataFrame) -> dict:
    plan = sku_plan.loc[sku_plan["period_week"] == 1].copy()
    if plan.empty or schedule.empty:
        raise ValueError("week-one SKU plan and schedule must both be nonempty")
    if plan["product_id"].duplicated().any():
        raise ValueError("week-one SKU plan must have one row per product")
    plan_runs = set(plan["run_id"])
    schedule_runs = set(schedule["run_id"])
    if len(plan_runs) != 1 or schedule_runs != plan_runs:
        raise ValueError("plan and schedule must identify the same single run")

    key = ["parent_lot_id", "sub_lot_index"]
    if schedule.duplicated([*key, "operation_seq"]).any():
        raise ValueError("duplicate operation within a sublot")
    first = schedule.sort_values("operation_seq").groupby(key, sort=False).head(1)
    final = schedule.sort_values("operation_seq").groupby(key, sort=False).tail(1)
    entry = first.set_index(key)[["product_id", "production_units"]].sort_index()
    exit_ = final.set_index(key)[["product_id", "production_units"]].sort_index()
    if not entry.equals(exit_):
        raise ValueError("sublot operation quantities disagree")
    first_by_sku = first.groupby("product_id")["production_units"].sum().to_dict()
    final_by_sku = final.groupby("product_id")["production_units"].sum().to_dict()
    due_by_sku = (
        final.loc[final["end_min"] <= WEEK_ONE_END_MIN].groupby("product_id")["production_units"].sum().to_dict()
    )
    if set(first_by_sku) != set(plan["product_id"]):
        raise ValueError("scheduled SKUs do not match the week-one plan")

    rows = []
    for row in plan.itertuples():
        planned = int(row.planned_units)
        scheduled = int(first_by_sku[row.product_id])
        eventual = int(final_by_sku[row.product_id])
        if scheduled != planned or eventual != planned:
            raise ValueError(f"scheduled quantities disagree with plan for {row.product_id}")
        due = int(due_by_sku.get(row.product_id, 0))
        rows.append(
            {
                "product_id": row.product_id,
                "family_id": row.family_id,
                "planned_units": planned,
                "scheduled_to_finish_by_week_end_units": due,
                "scheduled_after_week_end_units": planned - due,
            }
        )
    planned_total = sum(row["planned_units"] for row in rows)
    due_total = sum(row["scheduled_to_finish_by_week_end_units"] for row in rows)
    return {
        "scope": "SYNTHETIC_PLANNED_SCHEDULE_NOT_ACTUALS",
        "run_id": next(iter(plan_runs)),
        "week_end_min": WEEK_ONE_END_MIN,
        "planned_units": planned_total,
        "scheduled_to_finish_by_week_end_units": due_total,
        "scheduled_after_week_end_units": planned_total - due_total,
        "scheduled_completion_share": due_total / planned_total if planned_total else None,
        "by_product": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sku-plan", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare_week_one(pd.read_csv(args.sku_plan), pd.read_csv(args.schedule))
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
