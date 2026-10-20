"""What-If Scenario and Sensitivity Analysis Engine for CP-SAT Scheduling (Faz 4)."""

import math
import sqlite3
from pathlib import Path

import pandas as pd

from src.config import PRODUCTION_BATCH_SIZE, get_runtime_paths
from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    RescheduleTriggerEvent,
    ScenarioDeltaReport,
    ScenarioType,
    ScheduleSolverMetadata,
    SolverStatus,
)
from src.scheduling.hot_order_schedule_audit import audit_hot_order_schedule
from src.scheduling.maintenance import MaintenanceWindow
from src.scheduling.model_context import load_model_context
from src.scheduling.reschedule_candidate_audit import audit_reschedule_candidate
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.schedule_metrics import schedule_kpis
from src.utils.db import clone_run_inputs, get_active_run_id
from src.utils.solver_slot import admitted_solver_call


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

    def run_baseline(
        self,
        mem_conn: sqlite3.Connection,
        run_id: str = "BASELINE",
        time_limit_seconds: float | None = None,
    ) -> ScheduleSolverMetadata:
        """Solves and returns the baseline operational schedule."""
        wrapped_conn = NoCloseConnectionWrapper(mem_conn)
        clone_run_inputs(mem_conn, get_active_run_id(mem_conn), run_id)
        meta = run_cpsat_scheduling(
            run_id=run_id,
            persist_outputs=False,
            connection=wrapped_conn,
            time_limit_seconds=time_limit_seconds,
        )
        return meta

    def load_active_baseline(self, mem_conn: sqlite3.Connection) -> tuple[ScheduleSolverMetadata, pd.DataFrame]:
        """Read the accepted ACTIVE schedule as the current what-if baseline."""
        active_run_id = get_active_run_id(mem_conn)
        cursor = mem_conn.execute(
            "SELECT * FROM schedule_solver_metadata WHERE run_id = ? ORDER BY rowid DESC LIMIT 2",
            (active_run_id,),
        )
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise RuntimeError("ACTIVE baseline requires exactly one solver metadata row")
        metadata = ScheduleSolverMetadata.model_validate(
            dict(zip((column[0] for column in cursor.description), rows[0]))
        )
        if metadata.run_id != active_run_id or metadata.status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            raise RuntimeError("ACTIVE baseline has no accepted solver result")
        context = load_model_context(mem_conn, active_run_id)
        if (
            context.get("earliest_start_min", 0) != 0
            or context.get("frozen_positions")
            or context.get("flexible_windows")
            or context.get("maintenance_overrides")
        ):
            raise RuntimeError("ACTIVE baseline has replay constraints that this hot-order experiment cannot preserve")
        schedule = pd.read_sql(
            "SELECT * FROM production_schedule WHERE run_id = ?",
            mem_conn,
            params=(active_run_id,),
        )
        if schedule.empty or schedule["task_id"].isna().any() or schedule["task_id"].duplicated().any():
            raise RuntimeError("ACTIVE baseline schedule is empty or has invalid task IDs")
        return metadata, schedule

    @admitted_solver_call
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
            baseline_sched = pd.read_sql(
                "SELECT * FROM production_schedule WHERE run_id = ?", mem_conn, params=("BASE",)
            )

            # 2. Makine Takviminde Duruş Simülasyonu
            clone_run_inputs(mem_conn, "BASE", scenario_name)
            # 3. Senaryo Çözümü
            wrapped_conn = NoCloseConnectionWrapper(mem_conn)
            breakdown_window = MaintenanceWindow(
                breakdown.machine_id,
                breakdown.start_min,
                breakdown.start_min + breakdown.duration_min,
                "BREAKDOWN",
                breakdown.description,
            )
            scenario_meta = run_cpsat_scheduling(
                run_id=scenario_name,
                persist_outputs=False,
                connection=wrapped_conn,
                maintenance_overrides=[breakdown_window],
            )

            scenario_sched = pd.read_sql(
                "SELECT * FROM production_schedule WHERE run_id = ?",
                mem_conn,
                params=(scenario_name,),
            )

            # This is a hypothetical plan from time zero, not an executed MES
            # event: no frozen or flexible commitments are claimed here.
            candidate_audit = audit_reschedule_candidate(
                mem_conn,
                baseline_sched,
                scenario_sched,
                RescheduleTriggerEvent(
                    event_id=f"WHATIF-{scenario_name}",
                    current_time_min=0,
                    freeze_horizon_min=0,
                    flexible_horizon_min=0,
                    max_flexible_shift_min=0,
                    delay_machine_id=breakdown.machine_id,
                    delay_duration_min=breakdown.duration_min,
                    reason=breakdown.description,
                ),
                maintenance_overrides=[breakdown_window],
                baseline_run_id="BASE",
                enforce_started_at_current_time=False,
            )
            if candidate_audit["status"] != "ACCEPTED":
                codes = ", ".join(sorted({item["code"] for item in candidate_audit["issues"]}))
                raise RuntimeError(f"Independent breakdown candidate audit rejected the scenario: {codes}")

            # 4. KPI Delta Hesaplama
            report = self._calculate_delta(
                scenario_name=scenario_name,
                scenario_type=ScenarioType.MACHINE_BREAKDOWN,
                baseline_schedule=baseline_sched,
                scenario_schedule=scenario_sched,
            )
            return baseline_meta, scenario_meta, report, scenario_sched
        finally:
            mem_conn.close()

    @admitted_solver_call
    def simulate_hot_order(
        self,
        hot_order: HotOrderInjection,
        scenario_name: str = "HOT_ORDER_SCENARIO",
        baseline_time_limit_seconds: float | None = None,
        scenario_time_limit_seconds: float | None = None,
        reuse_active_baseline: bool = False,
        scenario_dispatch_rule: str | None = None,
        experimental_scenario_seed: int | None = None,
        experimental_scenario_workers: int | None = None,
    ) -> tuple[
        ScheduleSolverMetadata,
        ScheduleSolverMetadata,
        ScenarioDeltaReport,
        pd.DataFrame,
    ]:
        """Injects a high-priority rush order and assesses the schedule disruption."""
        mem_conn = self._create_isolated_connection()
        try:
            # The accepted ACTIVE version is already solved; interactive replay
            # can use it directly instead of spending its budget solving it again.
            reference_schedule = None
            source_run_id = "BASE"
            if reuse_active_baseline:
                baseline_meta, reference_schedule = self.load_active_baseline(mem_conn)
                source_run_id = baseline_meta.run_id
            else:
                baseline_meta = self.run_baseline(
                    mem_conn, run_id="BASE", time_limit_seconds=baseline_time_limit_seconds
                )

            # 2. Acil Siparişi sku_production_plan Tablosuna Ekle
            batches = math.ceil(hot_order.quantity / PRODUCTION_BATCH_SIZE)
            clone_run_inputs(mem_conn, source_run_id, scenario_name)
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
                sku_plan=scenario_plan,
                run_id=scenario_name,
                persist_outputs=False,
                connection=wrapped_conn,
                time_limit_seconds=scenario_time_limit_seconds,
                reference_schedule=reference_schedule,
                dispatch_rule=scenario_dispatch_rule,
                experimental_random_seed=experimental_scenario_seed,
                experimental_num_workers=experimental_scenario_workers,
            )

            scenario_sched = pd.read_sql(
                "SELECT * FROM production_schedule WHERE run_id = ?",
                mem_conn,
                params=(scenario_name,),
            )

            candidate_audit = audit_hot_order_schedule(mem_conn, source_run_id, hot_order, scenario_sched)
            if candidate_audit["status"] != "ACCEPTED":
                codes = ", ".join(sorted({item["code"] for item in candidate_audit["issues"]}))
                raise RuntimeError(f"Independent hot-order candidate audit rejected the scenario: {codes}")

            # 4. KPI Delta Hesaplama
            baseline_sched = reference_schedule
            if baseline_sched is None:
                baseline_sched = pd.read_sql(
                    "SELECT * FROM production_schedule WHERE run_id = ?", mem_conn, params=(source_run_id,)
                )
            report = self._calculate_delta(
                scenario_name=scenario_name,
                scenario_type=ScenarioType.HOT_ORDER,
                baseline_schedule=baseline_sched,
                scenario_schedule=scenario_sched,
            )
            return baseline_meta, scenario_meta, report, scenario_sched
        finally:
            mem_conn.close()

    def _calculate_delta(
        self,
        scenario_name: str,
        scenario_type: ScenarioType,
        baseline_schedule: pd.DataFrame,
        scenario_schedule: pd.DataFrame,
    ) -> ScenarioDeltaReport:
        baseline = schedule_kpis(baseline_schedule)
        scenario = schedule_kpis(scenario_schedule)

        return ScenarioDeltaReport(
            scenario_name=scenario_name,
            scenario_type=scenario_type,
            baseline_makespan_min=baseline.makespan_min,
            scenario_makespan_min=scenario.makespan_min,
            makespan_delta_min=scenario.makespan_min - baseline.makespan_min,
            baseline_total_tardiness_min=baseline.weighted_tardiness_min,
            scenario_total_tardiness_min=scenario.weighted_tardiness_min,
            tardiness_delta_min=scenario.weighted_tardiness_min - baseline.weighted_tardiness_min,
            baseline_total_setup_min=baseline.total_setup_min,
            scenario_total_setup_min=scenario.total_setup_min,
            setup_delta_min=scenario.total_setup_min - baseline.total_setup_min,
            impacted_tasks_count=len(scenario_schedule),
        )
