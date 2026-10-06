"""Factory Decision Intelligence REST API."""

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel

from src.config import get_runtime_paths
from src.contracts.decision_ledger import DecisionLedger
from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    RescheduleTriggerEvent,
)
from src.scheduling.rescheduler import DynamicRescheduler
from src.scheduling.what_if import WhatIfEngine
from src.utils.db import get_active_run_id, get_db_connection


class DynamicRescheduleRequest(BaseModel):
    trigger: RescheduleTriggerEvent
    new_run_id: str | None = None


app = FastAPI(
    title="Factory Decision Intelligence API",
    description=("Taktik LP, CP-SAT operasyonel çizelgeleme, what-if ve dinamik rescheduling servis katmanı"),
    version="1.0.0",
)


def get_db() -> sqlite3.Connection:
    conn = get_db_connection(get_runtime_paths()["db_path"])
    conn.row_factory = sqlite3.Row
    return conn


def require_active_run_id(conn: sqlite3.Connection) -> str:
    try:
        return get_active_run_id(conn)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="ACTIVE run bulunamadı.") from exc


@app.get("/health", tags=["Health & Monitoring"])
def health_check() -> dict[str, str]:
    return {"status": "HEALTHY", "service": "factory-decision-intelligence"}


@app.get("/ready", tags=["Health & Monitoring"])
def readiness_check() -> dict[str, str]:
    if not Path(get_runtime_paths()["db_path"]).is_file():
        raise HTTPException(status_code=503, detail="Runtime database is unavailable.")
    conn = get_db()
    try:
        active = get_active_run_id(conn)
        if not conn.execute("SELECT 1 FROM schedule_solver_metadata WHERE run_id = ?", (active,)).fetchone():
            raise RuntimeError("ACTIVE solver metadata is unavailable.")
        return {"status": "READY", "run_id": active}
    except (RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/v1/schedule/current", tags=["Schedule Query"])
def get_current_schedule(
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        active_run_id = require_active_run_id(conn)
        df = pd.read_sql(
            "SELECT * FROM production_schedule WHERE run_id = ? ORDER BY start_min ASC LIMIT ?",
            conn,
            params=(active_run_id, limit),
        )
        return df.to_dict(orient="records")
    finally:
        conn.close()


@app.get("/api/v1/schedule/solver-metadata", tags=["Schedule Query"])
def get_solver_metadata() -> dict[str, Any]:
    conn = get_db()
    try:
        active_run_id = require_active_run_id(conn)
        df = pd.read_sql(
            "SELECT * FROM schedule_solver_metadata WHERE run_id = ? ORDER BY rowid DESC LIMIT 1",
            conn,
            params=(active_run_id,),
        )
        if df.empty:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ACTIVE run için solver metadata bulunamadı.",
            )
        return df.iloc[0].to_dict()
    finally:
        conn.close()


@app.post("/api/v1/schedule/what-if/breakdown", tags=["What-If Scenarios"])
def simulate_breakdown(event: MachineBreakdownEvent) -> dict[str, Any]:
    try:
        engine = WhatIfEngine()
        _, scenario_meta, report, scenario_df = engine.simulate_breakdown(event)
        return {
            "status": "SUCCESS",
            "scenario_type": "MACHINE_BREAKDOWN",
            "comparison_report": report.model_dump(),
            "solver_status": scenario_meta.status,
            "tasks_count": len(scenario_df),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"What-If arıza simülasyonu başarısız: {exc}",
        ) from exc


@app.post("/api/v1/schedule/what-if/hot-order", tags=["What-If Scenarios"])
def simulate_hot_order(injection: HotOrderInjection) -> dict[str, Any]:
    try:
        engine = WhatIfEngine()
        _, scenario_meta, report, scenario_df = engine.simulate_hot_order(injection)
        return {
            "status": "SUCCESS",
            "scenario_type": "HOT_ORDER_INJECTION",
            "comparison_report": report.model_dump(),
            "solver_status": scenario_meta.status,
            "tasks_count": len(scenario_df),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"What-If acil sipariş simülasyonu başarısız: {exc}",
        ) from exc


@app.post("/api/v1/schedule/reschedule", tags=["Dynamic Rescheduling"])
def execute_dynamic_reschedule(
    request: DynamicRescheduleRequest,
) -> dict[str, Any]:
    try:
        rescheduler = DynamicRescheduler()
        _, _, new_meta, nervousness, audit = rescheduler.execute_reschedule(
            trigger=request.trigger,
            new_run_id=request.new_run_id,
        )
        return {
            "status": "SUCCESS",
            "audit_id": audit.audit_id,
            "previous_run_id": audit.previous_run_id,
            "new_run_id": audit.new_run_id,
            "nervousness_report": nervousness.model_dump(),
            "solver_status": new_meta.status,
            "new_makespan_min": new_meta.makespan_min,
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dinamik yeniden çizelgeleme başarısız: {exc}",
        ) from exc


@app.get("/api/v1/schedule/audit-log", tags=["Audit & Lineage"])
def get_reschedule_audit_log(
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        active_run_id = require_active_run_id(conn)
        df = pd.read_sql(
            "SELECT * FROM reschedule_audit_log "
            "WHERE new_run_id = ? OR previous_run_id = ? "
            "ORDER BY rowid DESC LIMIT ?",
            conn,
            params=(active_run_id, active_run_id, limit),
        )
        return df.to_dict(orient="records")
    finally:
        conn.close()


@app.get("/api/v1/decisions", tags=["Audit & Lineage"])
def get_active_run_decisions() -> list[dict[str, Any]]:
    conn = get_db()
    try:
        active_run_id = require_active_run_id(conn)
    finally:
        conn.close()

    ledger = DecisionLedger(get_runtime_paths()["db_path"])
    return [entry.to_dict() for entry in ledger.get_by_run_id(active_run_id)]
