"""Authoritative event-driven rescheduling and run-version governance."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from src.carbon.carbon_analytics import compute_carbon_analytics
from src.config import get_runtime_paths
from src.contracts.decision_ledger import DecisionLedger, DecisionLedgerEntry
from src.contracts.schemas import (
    RescheduleAuditEntry,
    RescheduleTriggerEvent,
    ScheduleNervousnessReport,
)
from src.energy.energy_analytics import compute_energy_analytics
from src.scheduling.maintenance import MaintenanceWindow
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.scheduling.what_if import NoCloseConnectionWrapper
from src.utils.runtime_lock import run_mutation_lock


class DynamicRescheduler:
    """Single production rescheduling orchestrator.

    Production semantics:
    ACTIVE -> isolated solve -> complete new run -> validate -> seal -> promote.
    The previous ACTIVE schedule is never updated in place.
    """

    RUN_SCOPED_INPUT_TABLES = (
        "orders",
        "forecast_demand",
        "forecast_model_lineage",
        "aggregate_plan",
        "sku_production_plan",
        "machine_capacity_plan",
        "mrp_plan",
        "machine_state_snapshot",
        "mes_order_tracking",
    )

    ARTIFACT_TABLES = {
        "orders": "factory_orders.csv",
        "forecast_demand": "forecast_demand.csv",
        "forecast_model_lineage": "forecast_model_lineage.csv",
        "aggregate_plan": "aggregate_plan.csv",
        "sku_production_plan": "sku_production_plan.csv",
        "machine_capacity_plan": "machine_capacity_plan.csv",
        "mrp_plan": "mrp_plan.csv",
        "production_schedule": "production_schedule.csv",
        "energy_kpis": "energy_kpis.csv",
        "energy_profile_15min": "energy_profile_15min.csv",
        "energy_machine_kpis": "energy_machine_kpis.csv",
        "carbon_kpis": "carbon_analytics.csv",
        "carbon_machine_kpis": "carbon_machine_kpis.csv",
        "carbon_price_scenarios": "carbon_price_scenarios.csv",
    }

    def __init__(self, disk_db_path: str | None = None):
        self.disk_db_path = str(disk_db_path or get_runtime_paths()["db_path"])

    def _get_active_run_id(self, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            raise ValueError("[RESCHEDULE] ACTIVE run bulunamadı; silent fallback yasaktır.")
        return str(row[0])

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                (table_name,),
            ).fetchone()
            is not None
        )

    def _clone_run_scoped_table(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        source_run_id: str,
        target_run_id: str,
    ) -> None:
        if not self._table_exists(conn, table_name):
            return

        info = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if not info or "run_id" not in {row[1] for row in info}:
            return

        # Integer surrogate primary keys must be regenerated. Business keys are
        # retained; run_id changes provide version identity where applicable.
        columns = [row[1] for row in info if not (row[5] == 1 and str(row[2]).upper().startswith("INTEGER"))]
        if "run_id" not in columns:
            return

        conn.execute(f"DELETE FROM {table_name} WHERE run_id = ?", (target_run_id,))
        insert_cols = ", ".join(f'"{col}"' for col in columns)
        select_expr = ", ".join("?" if col == "run_id" else f'"{col}"' for col in columns)
        conn.execute(
            f"INSERT INTO {table_name} ({insert_cols}) SELECT {select_expr} FROM {table_name} WHERE run_id = ?",
            (target_run_id, source_run_id),
        )

    def _clone_run_scoped_inputs(
        self,
        conn: sqlite3.Connection,
        source_run_id: str,
        target_run_id: str,
    ) -> None:
        for table_name in self.RUN_SCOPED_INPUT_TABLES:
            self._clone_run_scoped_table(conn, table_name, source_run_id, target_run_id)
        conn.commit()

    def _build_frozen_positions(
        self,
        baseline_sched: pd.DataFrame,
        trigger: RescheduleTriggerEvent,
        completed_tasks: set,
    ) -> dict[str, tuple[str, float, float]]:
        cutoff = trigger.current_time_min + trigger.freeze_horizon_min
        frozen = baseline_sched[
            (baseline_sched["start_min"] < cutoff) | baseline_sched["task_id"].isin(completed_tasks)
        ]
        return {
            str(row["task_id"]): (
                str(row["machine_id"]),
                float(row["start_min"]),
                float(row["end_min"]),
            )
            for _, row in frozen.iterrows()
        }

    def _create_new_run_record(
        self,
        conn: sqlite3.Connection,
        new_run_id: str,
        previous_run_id: str,
    ) -> None:
        row = conn.execute(
            "SELECT orders_count, git_sha, config_hash, data_source FROM pipeline_runs WHERE run_id = ?",
            (previous_run_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"[RESCHEDULE] Baseline run bulunamadı: {previous_run_id}")

        conn.execute(
            """
            INSERT INTO pipeline_runs
            (run_id, timestamp, trigger_source, orders_count, git_sha,
             config_hash, data_source, status)
            VALUES (?, datetime('now'), ?, ?, ?, ?, ?, 'RUNNING')
            """,
            (
                new_run_id,
                f"RESCHEDULE:{previous_run_id}",
                row[0],
                row[1],
                row[2],
                row[3],
            ),
        )

    @staticmethod
    def _metadata_dict(meta, run_id: str) -> dict:
        if hasattr(meta, "model_dump"):
            payload = meta.model_dump(mode="json")
        elif hasattr(meta, "__dict__"):
            payload = dict(meta.__dict__)
        else:
            payload = {}
        payload["run_id"] = run_id
        return payload

    def _persist_solver_metadata(
        self,
        conn: sqlite3.Connection,
        new_run_id: str,
        meta,
    ) -> None:
        if not self._table_exists(conn, "schedule_solver_metadata"):
            return
        solver_cols = [row[1] for row in conn.execute("PRAGMA table_info(schedule_solver_metadata)").fetchall()]
        payload = self._metadata_dict(meta, new_run_id)
        row = {key: value for key, value in payload.items() if key in solver_cols}
        if not row:
            return
        conn.execute(
            "DELETE FROM schedule_solver_metadata WHERE run_id = ?",
            (new_run_id,),
        )
        pd.DataFrame([row]).to_sql("schedule_solver_metadata", conn, if_exists="append", index=False)

    def _persist_audit_entry(self, conn: sqlite3.Connection, audit: RescheduleAuditEntry) -> None:
        conn.execute("""CREATE TABLE IF NOT EXISTS reschedule_audit_log (
            audit_id TEXT PRIMARY KEY, trigger_event_id TEXT NOT NULL,
            previous_run_id TEXT NOT NULL, new_run_id TEXT NOT NULL,
            trigger_timestamp_min REAL, freeze_horizon_min REAL,
            affected_machine_id TEXT, delay_duration_min REAL, reason TEXT,
            total_tasks INTEGER, frozen_tasks_count INTEGER, rescheduled_tasks_count INTEGER,
            machine_swapped_count INTEGER, avg_start_delta_min REAL, nervousness_score REAL
        )""")
        conn.execute(
            """
            INSERT OR REPLACE INTO reschedule_audit_log (
                audit_id, trigger_event_id, previous_run_id, new_run_id,
                trigger_timestamp_min, freeze_horizon_min, affected_machine_id,
                delay_duration_min, reason, total_tasks, frozen_tasks_count,
                rescheduled_tasks_count, machine_swapped_count, avg_start_delta_min,
                nervousness_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit.audit_id,
                audit.trigger_event_id,
                audit.previous_run_id,
                audit.new_run_id,
                audit.trigger_timestamp_min,
                audit.freeze_horizon_min,
                audit.affected_machine_id,
                audit.delay_duration_min,
                audit.reason,
                audit.total_tasks,
                audit.frozen_tasks_count,
                audit.rescheduled_tasks_count,
                audit.machine_swapped_count,
                audit.avg_start_delta_min,
                audit.nervousness_score,
            ),
        )

    def _persist_rescheduled_version(
        self,
        conn: sqlite3.Connection,
        new_df: pd.DataFrame,
        new_run_id: str,
        audit: RescheduleAuditEntry,
        meta,
    ) -> None:
        self._create_new_run_record(conn, new_run_id, audit.previous_run_id)
        self._clone_run_scoped_inputs(conn, audit.previous_run_id, new_run_id)

        from src.utils.db import migrate_schedule_commitments

        migrate_schedule_commitments(conn)
        conn.execute("DELETE FROM production_schedule WHERE run_id = ?", (new_run_id,))
        new_df.to_sql("production_schedule", conn, if_exists="append", index=False)
        self._persist_solver_metadata(conn, new_run_id, meta)
        self._persist_audit_entry(conn, audit)
        conn.commit()

    def _artifact_dirs(self, run_id: str) -> tuple[Path, Path, Path]:
        runtime = get_runtime_paths()
        configured_db = Path(runtime["db_path"]).resolve()
        actual_db = Path(self.disk_db_path).resolve()
        staging = actual_db.parent / "reschedule_runs" / run_id
        processed = staging / "data" / "processed"
        reports = staging / "reports"
        bundle = Path(runtime["base_dir"]) / "artifacts" / "runs" / run_id
        return processed, reports, bundle

    def _write_run_artifacts(self, run_id: str, meta, audit: RescheduleAuditEntry) -> tuple[Path, Path]:
        processed_dir, reports_dir, _ = self._artifact_dirs(run_id)
        processed_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.disk_db_path) as conn:
            for table_name, filename in self.ARTIFACT_TABLES.items():
                if not self._table_exists(conn, table_name):
                    continue
                cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
                if "run_id" not in cols:
                    continue
                df = pd.read_sql(
                    f"SELECT * FROM {table_name} WHERE run_id = ?",
                    conn,
                    params=(run_id,),
                )
                if not df.empty:
                    df.to_csv(processed_dir / filename, index=False)

            schedule_df = pd.read_sql(
                "SELECT * FROM production_schedule WHERE run_id = ?",
                conn,
                params=(run_id,),
            )
            if not schedule_df.empty:
                accounting_cols = [
                    col
                    for col in (
                        "task_id",
                        "machine_id",
                        "schedule_week",
                        "regular_minutes",
                        "overtime_minutes",
                        "setup_overtime_minutes",
                    )
                    if col in schedule_df.columns
                ]
                if accounting_cols:
                    schedule_df[accounting_cols].to_csv(processed_dir / "task_weekly_accounting.csv", index=False)

            run_row = conn.execute(
                "SELECT timestamp, trigger_source, orders_count, git_sha, config_hash, "
                "data_source, status FROM pipeline_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()

        solver_payload = self._metadata_dict(meta, run_id)
        (reports_dir / "schedule_solver_metadata.json").write_text(
            json.dumps(solver_payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        run_payload = {
            "run_id": run_id,
            "run_timestamp": run_row[0] if run_row else None,
            "trigger_source": run_row[1] if run_row else None,
            "orders_count": run_row[2] if run_row else 0,
            "git_sha": run_row[3] if run_row else None,
            "config_hash": run_row[4] if run_row else None,
            "data_source": run_row[5] if run_row else None,
            "status": run_row[6] if run_row else "COMPLETED",
            "reschedule": {
                "previous_run_id": audit.previous_run_id,
                "audit_id": audit.audit_id,
                "trigger_event_id": audit.trigger_event_id,
            },
        }
        (reports_dir / "run_metadata.json").write_text(
            json.dumps(run_payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return processed_dir, reports_dir

    def _record_decision(
        self,
        new_run_id: str,
        trigger: RescheduleTriggerEvent,
        report: ScheduleNervousnessReport,
        audit: RescheduleAuditEntry,
        meta,
    ) -> None:
        ledger = DecisionLedger(self.disk_db_path)
        ledger.record(
            DecisionLedgerEntry(
                decision_id=f"DEC-{uuid.uuid4().hex[:12].upper()}",
                run_id=new_run_id,
                decision_type="DYNAMIC_RESCHEDULE",
                input_state={
                    "previous_run_id": audit.previous_run_id,
                    "machine_id": trigger.delay_machine_id,
                    "delay_duration_min": trigger.delay_duration_min,
                    "freeze_horizon_min": trigger.freeze_horizon_min,
                },
                triggered_reason=trigger.reason,
                selected_action=f"Promote immutable reschedule version {new_run_id}",
                why=[
                    "ACTIVE schedule was not mutated in place",
                    "Frozen tasks were enforced as solver-level hard constraints",
                    "CP-SAT returned an accepted feasible schedule",
                ],
                rejected_alternatives=[
                    "Overwrite the ACTIVE schedule in place",
                    "Use an unversioned heuristic-only repair as production truth",
                ],
                expected_kpi_impact={
                    "nervousness_score": report.nervousness_score,
                    "average_start_delta_min": report.average_start_delta_min,
                    "machine_swapped_count": report.machine_swapped_count,
                    "makespan_min": getattr(meta, "makespan_min", None),
                },
            )
        )

    def _seal_run_bundle(
        self,
        run_id: str,
        previous_run_id: str,
        processed_dir: Path,
        reports_dir: Path,
    ) -> Path:
        _, _, bundle_dir = self._artifact_dirs(run_id)
        if bundle_dir.exists():
            raise ValueError(f"Immutable bundle already exists: {bundle_dir}")
        bundle_processed = bundle_dir / "data" / "processed"
        bundle_reports = bundle_dir / "reports"
        bundle_processed.mkdir(parents=True, exist_ok=True)
        bundle_reports.mkdir(parents=True, exist_ok=True)

        for path in processed_dir.glob("*.*"):
            shutil.copy2(path, bundle_processed / path.name)
        for path in reports_dir.glob("*.*"):
            shutil.copy2(path, bundle_reports / path.name)

        from src.utils.run_bundle import export_run_database

        export_run_database(self.disk_db_path, bundle_dir / "factory.db", run_id)

        files = {}
        for path in sorted(bundle_dir.rglob("*")):
            if not path.is_file() or path.name == "manifest.json":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files[str(path.relative_to(bundle_dir)).replace("\\", "/")] = {
                "sha256": digest,
                "bytes": path.stat().st_size,
            }
        manifest = {
            "run_id": run_id,
            "previous_run_id": previous_run_id,
            "run_type": "DYNAMIC_RESCHEDULE",
            "files": files,
        }
        (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return bundle_dir

    def scan_pending_mes_events(
        self, mem_conn: sqlite3.Connection, current_time_min: int
    ) -> list[RescheduleTriggerEvent]:
        active_run_id = self._get_active_run_id(mem_conn)
        query = """
            SELECT event_id, task_id, machine_id, event_type, event_timestamp_min,
                   actual_duration_min, delay_reason
            FROM mes_execution_events
            WHERE run_id = ?
              AND event_timestamp_min <= ?
              AND (event_type LIKE '%DELAY%' OR event_type LIKE '%BREAKDOWN%'
                   OR event_type LIKE '%STOP%')
            ORDER BY event_timestamp_min DESC
        """
        events_df = pd.read_sql(query, mem_conn, params=(active_run_id, current_time_min))
        triggers = []
        for _, row in events_df.iterrows():
            triggers.append(
                RescheduleTriggerEvent(
                    event_id=str(row["event_id"]),
                    current_time_min=int(row["event_timestamp_min"]),
                    freeze_horizon_min=60,
                    delay_machine_id=row["machine_id"],
                    delay_duration_min=int(row["actual_duration_min"] or 0),
                    reason=(f"{row['event_type']}: {row['delay_reason'] or 'Unspecified deviation'}"),
                )
            )
        return triggers

    def execute_reschedule(
        self,
        trigger: RescheduleTriggerEvent,
        new_run_id: str | None = None,
        persist_audit: bool = True,
    ):
        with run_mutation_lock(self.disk_db_path):
            return self._execute_reschedule(trigger, new_run_id, persist_audit)

    def _execute_reschedule(
        self,
        trigger: RescheduleTriggerEvent,
        new_run_id: str | None = None,
        persist_audit: bool = True,
    ):
        disk_conn = sqlite3.connect(self.disk_db_path)
        created_version = False
        try:
            previous_run_id = self._get_active_run_id(disk_conn)
            baseline_sched = pd.read_sql(
                "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY start_min",
                disk_conn,
                params=(previous_run_id,),
            )
            if baseline_sched.empty:
                raise ValueError(f"[RESCHEDULE] ACTIVE schedule bulunamadı: {previous_run_id}")

            new_run_id = new_run_id or f"RESCHED-{uuid.uuid4().hex[:10].upper()}"
            if new_run_id == previous_run_id:
                raise ValueError("[RESCHEDULE] new_run_id ACTIVE run ile aynı olamaz.")
            if disk_conn.execute("SELECT 1 FROM pipeline_runs WHERE run_id = ?", (new_run_id,)).fetchone():
                raise ValueError(f"[RESCHEDULE] Run ID already exists: {new_run_id}")

            if self._table_exists(disk_conn, "mes_order_tracking"):
                track_df = pd.read_sql(
                    "SELECT task_id, status FROM mes_order_tracking WHERE run_id = ?",
                    disk_conn,
                    params=(previous_run_id,),
                )
            else:
                track_df = pd.DataFrame(columns=["task_id", "status"])
            completed = set(track_df.loc[track_df["status"] == "COMPLETED", "task_id"]) if not track_df.empty else set()
            frozen = self._build_frozen_positions(baseline_sched, trigger, completed)

            mem_conn = sqlite3.connect(":memory:")
            disk_conn.backup(mem_conn)
            try:
                self._clone_run_scoped_inputs(mem_conn, previous_run_id, new_run_id)
                outage_windows = []
                if trigger.delay_machine_id and trigger.delay_duration_min > 0:
                    # Committed tasks retain their exact positions. The delay
                    # applies to the mutable queue after those commitments.
                    committed_end = max(
                        (end for machine, _, end in frozen.values() if machine == trigger.delay_machine_id),
                        default=trigger.current_time_min,
                    )
                    outage_start = max(trigger.current_time_min, int(committed_end))
                    outage_windows = [
                        MaintenanceWindow(
                            trigger.delay_machine_id,
                            outage_start,
                            outage_start + trigger.delay_duration_min,
                            "RESCHEDULE_DELAY",
                            trigger.reason,
                        )
                    ]

                meta = run_cpsat_scheduling(
                    run_id=new_run_id,
                    connection=NoCloseConnectionWrapper(mem_conn),
                    frozen_task_positions=frozen,
                    persist_outputs=False,
                    maintenance_overrides=outage_windows,
                    earliest_start_min=trigger.current_time_min,
                    reference_schedule=baseline_sched,
                )
                new_sched = pd.read_sql(
                    "SELECT * FROM production_schedule WHERE run_id = ?",
                    mem_conn,
                    params=(new_run_id,),
                )
            finally:
                mem_conn.close()

            if new_sched.empty:
                raise ValueError("[RESCHEDULE] Solver yeni schedule üretmedi.")

            for task_id, (machine, start, end) in frozen.items():
                row = new_sched[new_sched["task_id"].astype(str) == task_id]
                if row.empty:
                    raise ValueError(f"[RESCHEDULE] Frozen task missing: {task_id}")
                current = row.iloc[0]
                if (
                    str(current["machine_id"]) != machine
                    or abs(float(current["start_min"]) - start) > 1e-6
                    or abs(float(current["end_min"]) - end) > 1e-6
                ):
                    raise ValueError(f"[RESCHEDULE] Frozen constraint violated: {task_id}")

            report = self._calculate_nervousness(
                baseline_sched,
                new_sched,
                len(frozen),
                max(0, len(baseline_sched) - len(frozen)),
            )
            audit = RescheduleAuditEntry(
                audit_id=f"AUD-{uuid.uuid4().hex[:8].upper()}",
                trigger_event_id=trigger.event_id,
                previous_run_id=previous_run_id,
                new_run_id=new_run_id,
                trigger_timestamp_min=trigger.current_time_min,
                freeze_horizon_min=trigger.freeze_horizon_min,
                affected_machine_id=trigger.delay_machine_id,
                delay_duration_min=trigger.delay_duration_min,
                reason=trigger.reason,
                total_tasks=report.total_tasks,
                frozen_tasks_count=report.frozen_tasks_count,
                rescheduled_tasks_count=report.rescheduled_tasks_count,
                machine_swapped_count=report.machine_swapped_count,
                avg_start_delta_min=report.average_start_delta_min,
                nervousness_score=report.nervousness_score,
            )

            if persist_audit:
                created_version = True
                self._persist_rescheduled_version(disk_conn, new_sched, new_run_id, audit, meta)
                disk_conn.commit()
                disk_conn.close()
                disk_conn = None

                # Schedule-dependent analytics are recomputed for the new run;
                # they are never inherited from the previous ACTIVE version.
                processed_dir, reports_dir, _ = self._artifact_dirs(new_run_id)
                compute_energy_analytics(
                    run_id=new_run_id, db_path=self.disk_db_path, processed_dir=processed_dir, reports_dir=reports_dir
                )
                compute_carbon_analytics(
                    run_id=new_run_id, db_path=self.disk_db_path, processed_dir=processed_dir, reports_dir=reports_dir
                )
                processed_dir, reports_dir = self._write_run_artifacts(new_run_id, meta, audit)

                from src.utils.lineage import promote_run_to_active, update_pipeline_run_status, validate_pipeline_run

                update_pipeline_run_status(new_run_id, "STAGING", db_path=self.disk_db_path)
                update_pipeline_run_status(new_run_id, "VALIDATE", db_path=self.disk_db_path)

                validate_pipeline_run(
                    new_run_id,
                    db_path=self.disk_db_path,
                    reports_dir=str(reports_dir),
                )
                update_pipeline_run_status(new_run_id, "COMPLETED", db_path=self.disk_db_path)
                processed_dir, reports_dir = self._write_run_artifacts(new_run_id, meta, audit)
                self._record_decision(new_run_id, trigger, report, audit, meta)
                self._seal_run_bundle(
                    new_run_id,
                    previous_run_id,
                    processed_dir,
                    reports_dir,
                )
                # Final state transition: no schedule mutation occurs after this.
                promote_run_to_active(new_run_id, db_path=self.disk_db_path)

            return baseline_sched, new_sched, meta, report, audit
        except Exception:
            if created_version:
                from src.utils.lineage import update_pipeline_run_status

                with sqlite3.connect(self.disk_db_path) as failure_conn:
                    row = failure_conn.execute(
                        "SELECT status FROM pipeline_runs WHERE run_id = ?", (new_run_id,)
                    ).fetchone()
                if row and row[0] in {"RUNNING", "STAGING", "VALIDATE", "COMPLETED"}:
                    update_pipeline_run_status(new_run_id, "FAILED", db_path=self.disk_db_path)
            raise
        finally:
            if disk_conn is not None:
                disk_conn.close()

    def _calculate_nervousness(
        self,
        baseline_sched: pd.DataFrame,
        new_sched: pd.DataFrame,
        frozen_count: int,
        rescheduled_count: int,
    ) -> ScheduleNervousnessReport:
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
            baseline = base_indexed.loc[task_id]
            current = new_indexed.loc[task_id]
            if baseline["machine_id"] != current["machine_id"]:
                machine_swaps += 1
            start_deltas.append(abs(float(current["start_min"]) - float(baseline["start_min"])))

        avg_delta = float(np.mean(start_deltas)) if start_deltas else 0.0
        max_delta = float(np.max(start_deltas)) if start_deltas else 0.0
        swap_ratio = machine_swaps / total_tasks
        time_disruption_ratio = min(1.0, avg_delta / 10080.0)
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
