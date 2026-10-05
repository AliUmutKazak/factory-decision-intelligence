"""What-If Scenario and Sensitivity Analysis Engine for CP-SAT Scheduling (Faz 4)."""

import sqlite3

import pandas as pd

from src.config import DB_PATH, PRODUCTION_BATCH_SIZE
from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    ScenarioDeltaReport,
    ScenarioType,
    ScheduleSolverMetadata,
)
from src.scheduling.schedule_cpsat import run_cpsat_scheduling


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

    def __init__(self, disk_db_path: str = DB_PATH):
        self.disk_db_path = disk_db_path

    def _create_isolated_connection(self) -> sqlite3.Connection:
        disk_conn = sqlite3.connect(self.disk_db_path)
        mem_conn = sqlite3.connect(":memory:")
        disk_conn.backup(mem_conn)
        disk_conn.close()
        return mem_conn

    def run_baseline(self, mem_conn: sqlite3.Connection, run_id: str = "BASELINE") -> ScheduleSolverMetadata:
        """Solves and returns the baseline operational schedule."""
        from unittest.mock import patch

        wrapped_conn = NoCloseConnectionWrapper(mem_conn)
        with patch(
            "src.scheduling.schedule_cpsat.get_db_connection",
            return_value=wrapped_conn,
        ):
            meta = run_cpsat_scheduling(run_id=run_id)
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
        from unittest.mock import patch

        mem_conn = self._create_isolated_connection()
        try:
            # 1. Baz Senaryoyu Koştur
            baseline_meta = self.run_baseline(mem_conn, run_id="BASE")

            # 2. Makine Takviminde Duruş Simülasyonu
            cal_df = pd.read_sql(
                "SELECT * FROM machine_calendar WHERE machine_id = ?",
                mem_conn,
                params=(breakdown.machine_id,),
            )
            down_hours = breakdown.duration_min / 60.0
            if not cal_df.empty:
                # İlgili makinenin vardiya uygunluk saatlerini düşür
                mem_conn.execute(
                    "UPDATE machine_calendar SET available_hours = MAX(0.0, available_hours - ?) WHERE machine_id = ?",
                    (down_hours, breakdown.machine_id),
                )
            else:
                # Fallback: machines tablosundaki max_daily_hours değerini düşür
                mem_conn.execute(
                    "UPDATE machines SET max_daily_hours = MAX(1.0, max_daily_hours - ?) WHERE machine_id = ?",
                    (down_hours / 7.0, breakdown.machine_id),
                )
            mem_conn.commit()

            # 3. Senaryo Çözümü
            wrapped_conn = NoCloseConnectionWrapper(mem_conn)
            with patch(
                "src.scheduling.schedule_cpsat.get_db_connection",
                return_value=wrapped_conn,
            ):
                scenario_meta = run_cpsat_scheduling(run_id=scenario_name)

            scenario_sched = pd.read_sql(
                f"SELECT * FROM production_schedule WHERE run_id = '{scenario_name}'",
                mem_conn,
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
        from unittest.mock import patch

        mem_conn = self._create_isolated_connection()
        try:
            # 1. Baz Senaryoyu Koştur
            baseline_meta = self.run_baseline(mem_conn, run_id="BASE")

            # 2. Acil Siparişi sku_production_plan Tablosuna Ekle
            batches = max(1, (hot_order.quantity // PRODUCTION_BATCH_SIZE) or 1)

            # Ürünün family_id bilgisini products tablosundan çek
            p_df = pd.read_sql(
                "SELECT family_id FROM products WHERE product_id = ?",
                mem_conn,
                params=(hot_order.product_id,),
            )
            family_id = p_df.iloc[0]["family_id"] if not p_df.empty else "F01"

            new_row = {
                "period_week": 1,
                "product_id": hot_order.product_id,
                "family_id": family_id,
                "weekly_forecast_units": hot_order.quantity,
                "planned_batches": batches,
                "planned_units": batches * PRODUCTION_BATCH_SIZE,
                "run_id": scenario_name,
            }
            df_new = pd.DataFrame([new_row])
            df_new.to_sql("sku_production_plan", mem_conn, if_exists="append", index=False)

            # 3. Senaryo Çözümü
            wrapped_conn = NoCloseConnectionWrapper(mem_conn)
            with patch(
                "src.scheduling.schedule_cpsat.get_db_connection",
                return_value=wrapped_conn,
            ):
                scenario_meta = run_cpsat_scheduling(run_id=scenario_name)

            scenario_sched = pd.read_sql(
                f"SELECT * FROM production_schedule WHERE run_id = '{scenario_name}'",
                mem_conn,
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
