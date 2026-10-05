"""Dynamic Event-Driven Rescheduling and Nervousness Engine for CP-SAT (Faz 5)."""

import sqlite3

import numpy as np
import pandas as pd

from src.config import DB_PATH
from src.contracts.schemas import (
    RescheduleTriggerEvent,
    ScheduleNervousnessReport,
    ScheduleSolverMetadata,
)
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.what_if import NoCloseConnectionWrapper


class DynamicRescheduler:
    """Orchestrates event-driven rescheduling with freeze horizons and calculates schedule nervousness."""

    def __init__(self, disk_db_path: str = DB_PATH):
        self.disk_db_path = disk_db_path

    def _create_isolated_connection(self) -> sqlite3.Connection:
        disk_conn = sqlite3.connect(self.disk_db_path)
        mem_conn = sqlite3.connect(":memory:")
        disk_conn.backup(mem_conn)
        disk_conn.close()
        return mem_conn

    def execute_reschedule(
        self,
        trigger: RescheduleTriggerEvent,
        new_run_id: str = "RESCHEDULED_RUN",
    ) -> tuple[
        pd.DataFrame,
        pd.DataFrame,
        ScheduleSolverMetadata,
        ScheduleNervousnessReport,
    ]:
        """Executes event-driven dynamic rescheduling with a frozen horizon."""
        from unittest.mock import patch

        mem_conn = self._create_isolated_connection()
        try:
            # 1. Mevcut Aktif Çizelgeyi Oku
            baseline_sched = pd.read_sql(
                "SELECT * FROM production_schedule ORDER BY start_min ASC",
                mem_conn,
            )
            if baseline_sched.empty:
                raise ValueError("Veritabanında yeniden çizelgelenecek aktif bir baz plan bulunamadı.")

            freeze_cutoff_min = trigger.current_time_min + trigger.freeze_horizon_min

            # 2. Dondurulan (Frozen) ve Yeniden Çizelgelenecek Görevleri Belirle
            # MES tracking tablosundan tamamlananlar veya cut-off öncesi başlayanlar kilitlenir
            completed_tasks = set()
            track_df = pd.read_sql(
                "SELECT task_id, status FROM mes_order_tracking",
                mem_conn,
            )
            if not track_df.empty:
                completed_tasks = set(track_df[track_df["status"] == "COMPLETED"]["task_id"])

            frozen_mask = (baseline_sched["start_min"] < freeze_cutoff_min) | (
                baseline_sched["task_id"].isin(completed_tasks)
            )

            frozen_tasks = baseline_sched[frozen_mask].copy()
            tasks_to_reschedule = baseline_sched[~frozen_mask].copy()

            # 3. Gecikme / Arıza Varsa İlgili Makine Takvimine / Kapasitesine Yansıt
            if trigger.delay_machine_id and trigger.delay_duration_min > 0:
                down_hours = trigger.delay_duration_min / 60.0
                mem_conn.execute(
                    "UPDATE machine_calendar SET available_hours = MAX(0.0, available_hours - ?) WHERE machine_id = ?",
                    (down_hours, trigger.delay_machine_id),
                )
                mem_conn.commit()

            # 4. CP-SAT Çizelgeleyiciyi Yeni Koşu Olarak Çalıştır
            wrapped_conn = NoCloseConnectionWrapper(mem_conn)
            with patch(
                "src.scheduling.schedule_cpsat.get_db_connection",
                return_value=wrapped_conn,
            ):
                new_meta = run_cpsat_scheduling(run_id=new_run_id)

            new_sched = pd.read_sql(
                f"SELECT * FROM production_schedule WHERE run_id = '{new_run_id}'",
                mem_conn,
            )

            # 5. Dondurulmuş Görevlerin Orijinal Planını Koru
            # Yeniden çözülen planda kilitli işler orijinal zamanlarını koruyacak şekilde merge edilir
            merged_sched = self._reconcile_frozen_schedule(
                new_sched=new_sched,
                frozen_tasks=frozen_tasks,
                new_run_id=new_run_id,
            )

            # 6. Schedule Nervousness (Kararlılık) KPI Hesapla
            nervousness_report = self._calculate_nervousness(
                baseline_sched=baseline_sched,
                new_sched=merged_sched,
                frozen_count=len(frozen_tasks),
                rescheduled_count=len(tasks_to_reschedule),
            )

            return baseline_sched, merged_sched, new_meta, nervousness_report

        finally:
            mem_conn.close()

    def _reconcile_frozen_schedule(
        self,
        new_sched: pd.DataFrame,
        frozen_tasks: pd.DataFrame,
        new_run_id: str,
    ) -> pd.DataFrame:
        """Ensures that tasks falling within the freeze horizon retain their original assignments."""
        if frozen_tasks.empty:
            return new_sched.copy()

        frozen_ids = set(frozen_tasks["task_id"])
        # Yeni plandan dondurulanları çıkar, dondurulmuş olanların orijinal versiyonunu ekle
        non_frozen_part = new_sched[~new_sched["task_id"].isin(frozen_ids)].copy()
        frozen_part = frozen_tasks.copy()
        frozen_part["run_id"] = new_run_id

        combined = pd.concat([frozen_part, non_frozen_part], ignore_index=True)
        return combined.sort_values(by=["machine_id", "start_min"]).reset_index(drop=True)

    def _calculate_nervousness(
        self,
        baseline_sched: pd.DataFrame,
        new_sched: pd.DataFrame,
        frozen_count: int,
        rescheduled_count: int,
    ) -> ScheduleNervousnessReport:
        """Calculates schedule stability metrics comparing old vs new schedule."""
        base_indexed = baseline_sched.set_index("task_id")
        new_indexed = new_sched.set_index("task_id")

        common_tasks = base_indexed.index.intersection(new_indexed.index)
        total_tasks = len(common_tasks)

        if total_tasks == 0:
            return ScheduleNervousnessReport(
                total_tasks=0,
                frozen_tasks_count=frozen_count,
                rescheduled_tasks_count=rescheduled_count,
                machine_swapped_count=0,
                average_start_delta_min=0.0,
                max_start_delta_min=0.0,
                nervousness_score=0.0,
            )

        machine_swaps = 0
        start_deltas = []

        for task_id in common_tasks:
            b_row = base_indexed.loc[task_id]
            n_row = new_indexed.loc[task_id]

            if b_row["machine_id"] != n_row["machine_id"]:
                machine_swaps += 1

            delta = abs(float(n_row["start_min"]) - float(b_row["start_min"]))
            start_deltas.append(delta)

        avg_delta = float(np.mean(start_deltas)) if start_deltas else 0.0
        max_delta = float(np.max(start_deltas)) if start_deltas else 0.0

        # Kararlılık Skoru (Nervousness Score):
        # İşlerin yer değiştirme oranı (%50) + zaman kaymalarının normalize etkisi (%50)
        swap_ratio = machine_swaps / total_tasks
        # 1 tam vardiya (480 dk) üstü ortalama kaymayı maksimum sarsıntı kabul ediyoruz
        time_disruption_ratio = min(1.0, avg_delta / 480.0)
        nervousness_score = round(0.5 * swap_ratio + 0.5 * time_disruption_ratio, 4)

        return ScheduleNervousnessReport(
            total_tasks=total_tasks,
            frozen_tasks_count=frozen_count,
            rescheduled_tasks_count=rescheduled_count,
            machine_swapped_count=machine_swaps,
            average_start_delta_min=round(avg_delta, 2),
            max_start_delta_min=round(max_delta, 2),
            nervousness_score=nervousness_score,
        )
