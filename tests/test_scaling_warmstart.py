"""Tests for large-scale scheduling performance and warm-start hinting capabilities (Faz 4)."""

import sqlite3
from unittest.mock import patch

import pandas as pd

from src.config import DB_PATH, PRODUCTION_BATCH_SIZE
from src.contracts.schemas import ScheduleSolverMetadata, SolverStatus
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.utils.db import clone_run_inputs, get_active_run_id


class NoCloseConnectionWrapper:
    """Wrapper that prevents close() from closing an in-memory SQLite connection."""

    def __init__(self, target: sqlite3.Connection):
        self._target = target

    def close(self):
        pass

    def cursor(self, *args, **kwargs):
        return self._target.cursor(*args, **kwargs)

    def commit(self):
        return self._target.commit()

    def rollback(self):
        return self._target.rollback()

    def execute(self, *args, **kwargs):
        return self._target.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._target.executemany(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._target, name)


def test_large_scale_warm_start_feasibility():
    """Verify that CP-SAT solver successfully scales and finds a valid schedule

    with heuristic warm-start hints on an expanded batch portfolio.
    """
    disk_conn = sqlite3.connect(DB_PATH)
    mem_conn = sqlite3.connect(":memory:")
    disk_conn.backup(mem_conn)
    disk_conn.close()

    wrapped_conn = NoCloseConnectionWrapper(mem_conn)
    test_run_id = "RUN-SCALE-WARMSTART-001"

    clone_run_inputs(mem_conn, get_active_run_id(mem_conn), test_run_id)
    try:
        # Planlama verilerini ve adetlerini birbiriyle tutarlı olacak şekilde ölçekle
        existing_plan = pd.read_sql(
            "SELECT * FROM sku_production_plan WHERE period_week = 1 AND run_id = ?", mem_conn, params=(test_run_id,)
        )
        if not existing_plan.empty:
            scaled_plan = existing_plan.copy()
            scaled_plan["planned_batches"] = scaled_plan["planned_batches"].apply(lambda x: min(max(int(x), 4), 6))
            scaled_plan["planned_units"] = scaled_plan["planned_batches"] * PRODUCTION_BATCH_SIZE
            scaled_plan.to_sql(
                "sku_production_plan",
                mem_conn,
                if_exists="replace",
                index=False,
            )

        # W1 fazla mesai bütçesini esnet
        mem_conn.execute("UPDATE machine_capacity_plan SET overtime_hours = 16.0 WHERE period_week = 1")
        mem_conn.commit()

        with (
            patch(
                "src.scheduling.schedule_cpsat.get_db_connection",
                return_value=wrapped_conn,
            ),
            patch("src.scheduling.schedule_cpsat.CPSAT_TIME_LIMIT_SECONDS", 15),
        ):
            result = run_cpsat_scheduling(run_id=test_run_id, persist_outputs=False)

            assert isinstance(result, ScheduleSolverMetadata)
            assert result.run_id == test_run_id
            assert result.status in (
                SolverStatus.OPTIMAL,
                SolverStatus.FEASIBLE,
            )
            assert result.makespan_min is not None and result.makespan_min > 0

            sched_df = pd.read_sql(
                f"SELECT * FROM production_schedule WHERE run_id = '{test_run_id}'",
                mem_conn,
            )
            assert not sched_df.empty

            # Tezgâh çakışma kısıt kontrolü
            for mid, grp in sched_df.groupby("machine_id"):
                sorted_grp = grp.sort_values("start_min")
                prev_end = 0
                for _, op in sorted_grp.iterrows():
                    assert op["start_min"] >= prev_end, f"{mid} tezgâhında çakışma tespit edildi!"
                    prev_end = op["end_min"]

    finally:
        mem_conn.close()
