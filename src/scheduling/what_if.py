"""What-If Scenario and Sensitivity Analysis Engine for CP-SAT Scheduling (Faz 4)."""

import math
import sqlite3
from pathlib import Path

import pandas as pd

from src.config import PRODUCTION_BATCH_SIZE, get_runtime_paths
from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    ScenarioDeltaReport,
    ScenarioType,
    ScheduleSolverMetadata,
)
from src.scheduling.maintenance import MaintenanceWindow
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


class WhatIfEngine:
    """Orchestrates sensitivity analysis and scenario simulation on top of CP-SAT scheduler."""

    def __init__(self, disk_db_path: str | None = None):
        self.disk_db_path = str(disk_db_path or get_runtime_paths()["db_path"])

    def _create_isolated_connection(self) -> sqlite3.Connection:
        source = Path(self.disk_db_path).resolve()
        disk_conn = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
        mem_conn = sqlite3.connect(":memory:")
        disk_conn.backup(mem_conn)
        disk_conn.close()
        return mem_conn

    def run_baseline(self, mem_conn: sqlite3.Connection, run_id: str = "BASELINE") -> ScheduleSolverMetadata:
        """Solves and returns the baseline operational schedule."""
        wrapped_conn = NoCloseConnectionWrapper(mem_conn)
        clone_run_inputs(mem_conn, get_active_run_id(mem_conn), run_id)
        meta = run_cpsat_scheduling(run_id=run_id, persist_outputs=False, connection=wrapped_conn)
        return meta

    def simulate_breakdown(
        self,
        breakdown: MachineBreakdownEvent,
        scenario_name: str = "BREAKDOWN_SCENARIO",
    ) -> tuple[
        ScheduleSolverMetadata,
        ScheduleSolverMetadata,
        ScenarioDeltaReport,
        pd.DataFrame,
    ]:
        """Simulates an unexpected machine breakdown by adjusting machine calendar/unavailability."""
        mem_conn = self._create_isolated_connection()
        try:
            # 1. Baz Senaryoyu Koştur
            baseline_meta = self.run_baseline(mem_conn, run_id="BASE")

            # 2. Makine Takviminde Duruş Simülasyonu
            clone_run_inputs(mem_conn, "BASE", scenario_name)
            # 3. Senaryo Çözümü
            wrapped_conn = NoCloseConnectionWrapper(mem_conn)
            scenario_meta = run_cpsat_scheduling(
                run_id=scenario_name,
                persist_outputs=False,
                connection=wrapped_conn,
                maintenance_overrides=[
                    MaintenanceWindow(
                        breakdown.machine_id,
                        breakdown.start_min,
                        breakdown.start_min + breakdown.duration_min,
                        "BREAKDOWN",
                        breakdown.description,
                    )
                ],
            )

            scenario_sched = pd.read_sql(
                "SELECT * FROM production_schedule WHERE run_id = ?",
                mem_conn,
                params=(scenario_name,),
            )

            # 4. KPI Delta Hesaplama
            report = self._calculate_delta(
                scenario_name=scenario_name,
                scenario_type=ScenarioType.MACHINE_BREAKDOWN,
                baseline_meta=baseline_meta,
                scenario_meta=scenario_meta,
                impacted_tasks=len(scenario_sched),
            )
            return baseline_meta, scenario_meta, report, scenario_sched
        finally:
            mem_conn.close()

    def simulate_hot_order(
        self,
        hot_order: HotOrderInjection,
        scenario_name: str = "HOT_ORDER_SCENARIO",
    ) -> tuple[
        ScheduleSolverMetadata,
        ScheduleSolverMetadata,
        ScenarioDeltaReport,
        pd.DataFrame,
    ]:
        """Injects a high-priority rush order and assesses the schedule disruption."""
        mem_conn = self._create_isolated_connection()
        try:
            # 1. Baz Senaryoyu Koştur
            baseline_meta = self.run_baseline(mem_conn, run_id="BASE")

            # 2. Acil Siparişi sku_production_plan Tablosuna Ekle
            batches = math.ceil(hot_order.quantity / PRODUCTION_BATCH_SIZE)
            clone_run_inputs(mem_conn, "BASE", scenario_name)
            scenario_plan = pd.read_sql(
                "SELECT * FROM sku_production_plan WHERE run_id = ? AND period_week = 1",
                mem_conn,
                params=(scenario_name,),
            )

            # Ürünün family_id bilgisini products tablosundan çek
            p_df = pd.read_sql(
                "SELECT family_id FROM products WHERE product_id = ?",
                mem_conn,
                params=(hot_order.product_id,),
            )
            if p_df.empty:
                raise ValueError(f"Unknown hot-order product: {hot_order.product_id}")
            family_id = p_df.iloc[0]["family_id"]

            new_row = {
                "period_week": 1,
                "product_id": hot_order.product_id,
                "family_id": family_id,
                "weekly_forecast_units": hot_order.quantity,
                "planned_batches": batches,
                "planned_units": batches * PRODUCTION_BATCH_SIZE,
                "run_id": scenario_name,
            }
            updated = mem_conn.execute(
                "UPDATE sku_production_plan SET planned_batches = planned_batches + ?, "
                "planned_units = planned_units + ?, weekly_forecast_units = weekly_forecast_units + ? "
                "WHERE run_id = ? AND product_id = ? AND period_week = 1",
                (batches, batches * PRODUCTION_BATCH_SIZE, hot_order.quantity, scenario_name, hot_order.product_id),
            )
            if updated.rowcount == 0:
                pd.DataFrame([new_row]).to_sql("sku_production_plan", mem_conn, if_exists="append", index=False)
            mem_conn.commit()
            # Keep the rush order as its own lot so its due date and penalty
            # do not silently change the commitments of baseline quantities.
            hot_lot = dict(
                new_row,
                lot_id=f"HOT_{hot_order.product_id}",
                due_date_min=hot_order.due_date_min,
                priority_weight=hot_order.priority_weight,
            )
            scenario_plan = pd.concat([scenario_plan, pd.DataFrame([hot_lot])], ignore_index=True)

            # 3. Senaryo Çözümü
            wrapped_conn = NoCloseConnectionWrapper(mem_conn)
            scenario_meta = run_cpsat_scheduling(
                sku_plan=scenario_plan, run_id=scenario_name, persist_outputs=False, connection=wrapped_conn
            )

            scenario_sched = pd.read_sql(
                "SELECT * FROM production_schedule WHERE run_id = ?",
                mem_conn,
                params=(scenario_name,),
            )

            # 4. KPI Delta Hesaplama
            report = self._calculate_delta(
                scenario_name=scenario_name,
                scenario_type=ScenarioType.HOT_ORDER,
                baseline_meta=baseline_meta,
                scenario_meta=scenario_meta,
                impacted_tasks=len(scenario_sched),
            )
            return baseline_meta, scenario_meta, report, scenario_sched
        finally:
            mem_conn.close()

    def _calculate_delta(
        self,
        scenario_name: str,
        scenario_type: ScenarioType,
        baseline_meta: ScheduleSolverMetadata,
        scenario_meta: ScheduleSolverMetadata,
        impacted_tasks: int,
    ) -> ScenarioDeltaReport:
        b_makespan = float(baseline_meta.makespan_min or 0.0)
        s_makespan = float(scenario_meta.makespan_min or 0.0)

        b_tardiness = float(baseline_meta.total_tardiness_min or 0.0)
        s_tardiness = float(scenario_meta.total_tardiness_min or 0.0)

        b_setup = float(baseline_meta.total_setup_min or 0.0)
        s_setup = float(scenario_meta.total_setup_min or 0.0)

        return ScenarioDeltaReport(
            scenario_name=scenario_name,
            scenario_type=scenario_type,
            baseline_makespan_min=b_makespan,
            scenario_makespan_min=s_makespan,
            makespan_delta_min=s_makespan - b_makespan,
            baseline_total_tardiness_min=b_tardiness,
            scenario_total_tardiness_min=s_tardiness,
            tardiness_delta_min=s_tardiness - b_tardiness,
            baseline_total_setup_min=b_setup,
            scenario_total_setup_min=s_setup,
            setup_delta_min=s_setup - b_setup,
            impacted_tasks_count=impacted_tasks,
        )
