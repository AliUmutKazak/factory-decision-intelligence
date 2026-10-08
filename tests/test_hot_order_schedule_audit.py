"""Independent G7 audit accepts a real candidate and rejects corrupted copies."""

import hashlib
import shutil
import sqlite3
import warnings
from contextlib import closing
from pathlib import Path

from src.contracts.schemas import HotOrderInjection
from src.scheduling.hot_order_schedule_audit import audit_hot_order_schedule
from src.scheduling.what_if import WhatIfEngine

REFERENCE_DB = Path(__file__).resolve().parents[1] / "artifacts/reference/factory.db"


def test_independent_hot_order_audit_detects_quantity_route_and_machine_corruption(tmp_path):
    source = tmp_path / "factory.db"
    shutil.copy2(REFERENCE_DB, source)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE pipeline_runs SET status = 'ACTIVE' WHERE status = 'COMPLETED'")
        active_run_id = conn.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE'").fetchone()[0]
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    order = HotOrderInjection(order_id="AUDIT-RUSH", product_id="P01", quantity=51, due_date_min=1200)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
        _, _, _, schedule = WhatIfEngine(str(source)).simulate_hot_order(
            order,
            reuse_active_baseline=True,
            scenario_dispatch_rule="EDD",
            scenario_time_limit_seconds=2,
        )
    with closing(sqlite3.connect(source)) as conn:
        assert audit_hot_order_schedule(conn, active_run_id, order, schedule)["status"] == "ACCEPTED"

        wrong_units = schedule.copy()
        wrong_units.loc[0, "production_units"] += 25
        codes = {item["code"] for item in audit_hot_order_schedule(conn, active_run_id, order, wrong_units)["issues"]}
        assert "UNIT_CONSERVATION" in codes

        wrong_hot_allocation = schedule.copy()
        baseline_lot = wrong_hot_allocation.loc[
            (wrong_hot_allocation["product_id"] == order.product_id)
            & (wrong_hot_allocation["parent_lot_id"] != f"HOT_{order.product_id}"),
            "lot_id",
        ].iloc[0]
        baseline_rows = wrong_hot_allocation["lot_id"] == baseline_lot
        wrong_hot_allocation.loc[baseline_rows, "parent_lot_id"] = f"HOT_{order.product_id}"
        wrong_hot_allocation.loc[baseline_rows, "due_date_min"] = order.due_date_min
        wrong_hot_allocation.loc[baseline_rows, "priority_weight"] = order.priority_weight
        codes = {
            item["code"]
            for item in audit_hot_order_schedule(conn, active_run_id, order, wrong_hot_allocation)["issues"]
        }
        assert "HOT_ORDER_QUANTITY" in codes

        wrong_machine = schedule.copy()
        wrong_machine.loc[0, "machine_id"] = "UNKNOWN"
        codes = {item["code"] for item in audit_hot_order_schedule(conn, active_run_id, order, wrong_machine)["issues"]}
        assert "ROUTING_MISMATCH" in codes

        missing_operation = schedule.drop(index=0)
        codes = {
            item["code"] for item in audit_hot_order_schedule(conn, active_run_id, order, missing_operation)["issues"]
        }
        assert "INCOMPLETE_ROUTE" in codes

        wrong_setup = schedule.copy()
        wrong_setup.loc[0, "setup_before_min"] += 1
        codes = {item["code"] for item in audit_hot_order_schedule(conn, active_run_id, order, wrong_setup)["issues"]}
        assert "SETUP_DURATION" in codes

        overlapping = schedule.copy()
        first_two = overlapping[overlapping["machine_id"] == "M01"].sort_values("start_min").index[:2]
        previous, following = first_two
        overlapping.loc[following, "start_min"] = overlapping.loc[previous, "end_min"] - 1
        overlapping.loc[following, "end_min"] = (
            overlapping.loc[following, "start_min"] + overlapping.loc[following, "duration_min"]
        )
        overlapping.loc[following, "setup_end_min"] = overlapping.loc[following, "start_min"]
        overlapping.loc[following, "setup_start_min"] = (
            overlapping.loc[following, "start_min"] - overlapping.loc[following, "setup_before_min"]
        )
        codes = {item["code"] for item in audit_hot_order_schedule(conn, active_run_id, order, overlapping)["issues"]}
        assert "MACHINE_OVERLAP" in codes
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
