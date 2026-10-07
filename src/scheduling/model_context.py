"""Version-scoped disruption and movement constraints for replay and audit."""

import json
from dataclasses import asdict

import pandas as pd

from src.utils.db import persist_run_scoped_dataframe


def save_model_context(conn, run_id, earliest_start, frozen, flexible, maintenance):
    payload = {
        "earliest_start_min": earliest_start,
        "frozen_positions": frozen or {},
        "flexible_windows": flexible or {},
        "maintenance_overrides": [asdict(window) for window in maintenance or []],
    }
    persist_run_scoped_dataframe(
        conn,
        "schedule_model_context",
        pd.DataFrame([{"run_id": str(run_id), "payload_json": json.dumps(payload)}]),
        str(run_id),
    )


def load_model_context(conn, run_id):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schedule_model_context'").fetchone():
        row = conn.execute(
            "SELECT payload_json FROM schedule_model_context WHERE run_id = ?", (str(run_id),)
        ).fetchone()
        if row:
            return json.loads(row[0])
    row = conn.execute("SELECT trigger_source FROM pipeline_runs WHERE run_id = ?", (str(run_id),)).fetchone()
    if row and row[0] in {"pipeline_execution", "scheduled", "MANUAL"}:
        return {"earliest_start_min": 0, "frozen_positions": {}, "flexible_windows": {}, "maintenance_overrides": []}
    raise ValueError(
        "This historical version has no replayable model context; create a verified version before benchmarking it."
    )
