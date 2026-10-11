"""Factory Decision Intelligence REST API."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel

from src.api.lab_auth import require_scope
from src.config import get_runtime_paths
from src.contracts.decision_ledger import DecisionLedger
from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    RescheduleTriggerEvent,
)
from src.scheduling.rescheduler import DynamicRescheduler
from src.scheduling.what_if import WhatIfEngine
from src.utils.db import get_active_run_id


class DynamicRescheduleRequest(BaseModel):
    trigger: RescheduleTriggerEvent
    new_run_id: str | None = None


app = FastAPI(
    title="Factory Decision Intelligence API",
    description=("Taktik LP, CP-SAT operasyonel çizelgeleme, what-if ve dinamik rescheduling servis katmanı"),
    version="1.0.0",
)
_solver_slots = BoundedSemaphore(value=1)


def acquire_solver_slot() -> Iterator[None]:
    """Bound the solver load of this local API process without queuing requests."""
    if not _solver_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "SOLVER_BUSY", "message": "Çözücü meşgul; isteği tekrar deneyin."},
            headers={"Retry-After": "1"},
        )
    try:
        yield
    finally:
        _solver_slots.release()


def _solver_timeout_error(exc: TimeoutError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "SOLVER_TIMEOUT",
            "message": "Çözücü zaman sınırında geçerli bir plan bulamadı; işlem yeniden denenebilir.",
        },
    )


def get_db() -> sqlite3.Connection:
    """Read one consistent database version without pinning the published file.

    Windows cannot atomically replace an open SQLite file. Copying the database
    through SQLite's backup API closes the file handle before an API handler
    reads ACTIVE and its related rows, while preserving one request snapshot.
    """
    path = Path(get_runtime_paths()["db_path"]).resolve()
    snapshot = sqlite3.connect(":memory:")
    try:
        source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            source.backup(snapshot)
        finally:
            source.close()
        snapshot.row_factory = sqlite3.Row
        return snapshot
    except (sqlite3.Error, OSError) as exc:
        snapshot.close()
        raise HTTPException(status_code=503, detail="Runtime database is unavailable.") from exc
    except Exception:
        snapshot.close()
        raise


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
    conn = None
    try:
        conn = get_db()
        active = get_active_run_id(conn)
        if not conn.execute("SELECT 1 FROM schedule_solver_metadata WHERE run_id = ?", (active,)).fetchone():
            raise RuntimeError("ACTIVE solver metadata is unavailable.")
        return {"status": "READY", "run_id": active}
    except (RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="Runtime database is unavailable.") from exc
    finally:
        if conn is not None:
            conn.close()


@app.get("/api/v1/schedule/current", tags=["Schedule Query"])
def get_current_schedule(
    limit: int = Query(100, ge=1, le=1000),
    _authorized: None = Depends(require_scope("read")),
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
def get_solver_metadata(_authorized: None = Depends(require_scope("read"))) -> dict[str, Any]:
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
def simulate_breakdown(
    event: MachineBreakdownEvent,
    _authorized: None = Depends(require_scope("scenario")),
    _slot: None = Depends(acquire_solver_slot),
) -> dict[str, Any]:
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
    except TimeoutError as exc:
        raise _solver_timeout_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="What-If arıza simülasyonu başarısız.",
        ) from exc


@app.post("/api/v1/schedule/what-if/hot-order", tags=["What-If Scenarios"])
def simulate_hot_order(
    injection: HotOrderInjection,
    _authorized: None = Depends(require_scope("scenario")),
    _slot: None = Depends(acquire_solver_slot),
) -> dict[str, Any]:
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
    except TimeoutError as exc:
        raise _solver_timeout_error(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="What-If acil sipariş simülasyonu başarısız.",
        ) from exc


@app.post("/api/v1/schedule/reschedule", tags=["Dynamic Rescheduling"])
def execute_dynamic_reschedule(
    request: DynamicRescheduleRequest,
    _authorized: None = Depends(require_scope("reschedule")),
    _slot: None = Depends(acquire_solver_slot),
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
    except TimeoutError as exc:
        raise _solver_timeout_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Yeniden çizelgeleme isteği kabul edilmedi.") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dinamik yeniden çizelgeleme başarısız.",
        ) from exc


@app.get("/api/v1/schedule/audit-log", tags=["Audit & Lineage"])
def get_reschedule_audit_log(
    limit: int = Query(50, ge=1, le=500),
    _authorized: None = Depends(require_scope("read")),
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
def get_active_run_decisions(_authorized: None = Depends(require_scope("read"))) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        active_run_id = require_active_run_id(conn)
        return [entry.to_dict() for entry in DecisionLedger.read_by_run_id(conn, active_run_id)]
    finally:
        conn.close()


@app.get("/api/v1/operations/status", tags=["Health & Monitoring"])
def get_operations_status(
    max_active_age_min: int = Query(1440, ge=1, le=43200),
    _authorized: None = Depends(require_scope("read")),
) -> dict[str, Any]:
    """Report ACTIVE publication age without interpreting naive legacy timestamps."""
    conn = get_db()
    try:
        run_id = require_active_run_id(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_runs)")}
        published = None
        if "published_at_utc" in columns:
            row = conn.execute("SELECT published_at_utc FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
            published = row[0] if row else None
        age_seconds = None
        state = "AGE_UNKNOWN"
        if published:
            try:
                moment = datetime.fromisoformat(published)
                if moment.tzinfo is not None:
                    age_seconds = int((datetime.now(UTC) - moment.astimezone(UTC)).total_seconds())
                    state = (
                        "CLOCK_SKEW"
                        if age_seconds < -60
                        else "STALE_ACTIVE"
                        if age_seconds > max_active_age_min * 60
                        else "READY"
                    )
            except ValueError:
                pass
        pending_intents = None
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mes_reschedule_outbox'").fetchone():
            pending_intents = conn.execute(
                "SELECT COUNT(*) FROM mes_reschedule_outbox WHERE status = 'PENDING'"
            ).fetchone()[0]
        return {
            "status": state,
            "run_id": run_id,
            "published_at_utc": published,
            "active_age_seconds": age_seconds,
            "max_active_age_min": max_active_age_min,
            "pending_mes_intents": pending_intents,
        }
    finally:
        conn.close()
