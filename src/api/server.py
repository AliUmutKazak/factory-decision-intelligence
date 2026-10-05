"""Factory Decision Intelligence - REST API Servis Katmanı (Faz 6)."""

import sqlite3
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel

from src.config import DB_PATH
from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    RescheduleTriggerEvent,
)
from src.scheduling.rescheduler import DynamicRescheduler
from src.scheduling.what_if import WhatIfEngine


class DynamicRescheduleRequest(BaseModel):
    trigger: RescheduleTriggerEvent
    new_run_id: str | None = None

app = FastAPI(
    title="Factory Decision Intelligence API",
    description="Taktik LP, CP-SAT Operasyonel Çizelgeleme, What-If ve Dinamik Rescheduling Servisi",
    version="1.0.0",
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/health", tags=["Health & Monitoring"])
def health_check() -> dict[str, str]:
    return {"status": "HEALTHY", "service": "factory-decision-intelligence"}


@app.get(
    "/api/v1/schedule/current", tags=["Schedule Query"]
)
def get_current_schedule(
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        df = pd.read_sql(
            "SELECT * FROM production_schedule ORDER BY start_min ASC LIMIT ?",
            conn,
            params=(limit,),
        )
        return df.to_dict(orient="records")
    finally:
        conn.close()


@app.get(
    "/api/v1/schedule/solver-metadata", tags=["Schedule Query"]
)
def get_solver_metadata() -> dict[str, Any]:
    conn = get_db()
    try:
        df = pd.read_sql(
            "SELECT * FROM schedule_solver_metadata ORDER BY id DESC LIMIT 1",
            conn,
        )
        if df.empty:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Henüz çözücü meta verisi kaydedilmemiş.",
            )
        return df.iloc[0].to_dict()
    finally:
        conn.close()


@app.post(
    "/api/v1/schedule/what-if/breakdown", tags=["What-If Scenarios"]
)
def simulate_breakdown(event: MachineBreakdownEvent) -> dict[str, Any]:
    try:
        engine = WhatIfEngine()
        b_meta, s_meta, report, sc_df = engine.simulate_breakdown(event)
        return {
            "status": "SUCCESS",
            "scenario_type": "MACHINE_BREAKDOWN",
            "comparison_report": report.model_dump(),
            "solver_status": s_meta.status,
            "tasks_count": len(sc_df),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"What-If arıza simülasyonu başarısız: {str(exc)}",
        ) from exc


@app.post(
    "/api/v1/schedule/what-if/hot-order", tags=["What-If Scenarios"]
)
def simulate_hot_order(injection: HotOrderInjection) -> dict[str, Any]:
    try:
        engine = WhatIfEngine()
        b_meta, s_meta, report, sc_df = engine.simulate_hot_order(injection)
        return {
            "status": "SUCCESS",
            "scenario_type": "HOT_ORDER_INJECTION",
            "comparison_report": report.model_dump(),
            "solver_status": s_meta.status,
            "tasks_count": len(sc_df),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"What-If acil sipariş simülasyonu başarısız: {str(exc)}",
        ) from exc


@app.post("/api/v1/schedule/reschedule", tags=["Dynamic Rescheduling"])
def execute_dynamic_reschedule(
    request: DynamicRescheduleRequest,
) -> dict[str, Any]:
    try:
        rescheduler = DynamicRescheduler()
        base_df, new_df, n_meta, n_rep, audit = rescheduler.execute_reschedule(
            trigger=request.trigger,
            new_run_id=request.new_run_id,
        )
        return {
            "status": "SUCCESS",
            "audit_id": audit.audit_id,
            "previous_run_id": audit.previous_run_id,
            "new_run_id": audit.new_run_id,
            "nervousness_report": n_rep.model_dump(),
            "solver_status": n_meta.status,
            "new_makespan_min": n_meta.makespan_min,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Dinamik yeniden çizelgeleme başarısız: {str(exc)}",
        ) from exc


@app.get("/api/v1/schedule/audit-log", tags=["Audit & Lineage"])
def get_reschedule_audit_log(
    limit: int = Query(50, ge=1, le=500),
) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        df = pd.read_sql(
            "SELECT * FROM reschedule_audit_log ORDER BY created_at DESC LIMIT ?",
            conn,
            params=(limit,),
        )
        return df.to_dict(orient="records")
    finally:
        conn.close()
