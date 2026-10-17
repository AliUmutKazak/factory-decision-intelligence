import pandas as pd
import pytest

from src.planning.plan_schedule_consistency import WEEK_ONE_END_MIN, compare_week_one


def test_week_one_counts_final_operation_only_and_preserves_run_scope():
    plan = pd.DataFrame(
        [{"run_id": "R1", "period_week": 1, "product_id": "P1", "family_id": "F1", "planned_units": 20}]
    )
    schedule = pd.DataFrame(
        [
            {
                "run_id": "R1",
                "parent_lot_id": "L1",
                "sub_lot_index": 1,
                "operation_seq": 1,
                "product_id": "P1",
                "production_units": 10,
                "end_min": 100,
            },
            {
                "run_id": "R1",
                "parent_lot_id": "L1",
                "sub_lot_index": 1,
                "operation_seq": 2,
                "product_id": "P1",
                "production_units": 10,
                "end_min": WEEK_ONE_END_MIN,
            },
            {
                "run_id": "R1",
                "parent_lot_id": "L2",
                "sub_lot_index": 1,
                "operation_seq": 1,
                "product_id": "P1",
                "production_units": 10,
                "end_min": 200,
            },
            {
                "run_id": "R1",
                "parent_lot_id": "L2",
                "sub_lot_index": 1,
                "operation_seq": 2,
                "product_id": "P1",
                "production_units": 10,
                "end_min": WEEK_ONE_END_MIN + 1,
            },
        ]
    )
    report = compare_week_one(plan, schedule)
    assert report["planned_units"] == 20
    assert report["scheduled_to_finish_by_week_end_units"] == 10
    assert report["scheduled_after_week_end_units"] == 10
    assert report["scheduled_completion_share"] == 0.5

    schedule.loc[:, "run_id"] = "R2"
    with pytest.raises(ValueError, match="same single run"):
        compare_week_one(plan, schedule)
