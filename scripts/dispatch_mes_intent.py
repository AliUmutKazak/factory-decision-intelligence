"""Manual, one-shot laboratory dispatch of one durable MES intent."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from src.integration.mes_reschedule_dispatcher import MESRescheduleDispatcher
from src.utils.db import resolve_db_path


def inspect_pending(db_path: Path) -> dict:
    """Report already-persisted intents without triggering a schema migration."""
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "mes_reschedule_outbox" not in tables or "mes_execution_events" not in tables:
            return {"status": "OUTBOX_UNAVAILABLE", "pending_intents": None}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(mes_execution_events)")}
        duration = "e.actual_duration_min" if "actual_duration_min" in columns else "NULL"
        rows = conn.execute(
            "SELECT o.event_id, o.run_id, e.event_type, e.machine_id, "
            f"{duration} AS outage_duration_min "
            "FROM mes_reschedule_outbox AS o "
            "JOIN mes_execution_events AS e ON e.event_id = o.event_id "
            "WHERE o.status = 'PENDING' ORDER BY o.event_id"
        ).fetchall()
    return {
        "status": "INSPECT_ONLY",
        "pending_intents": [
            {
                "event_id": row[0],
                "run_id": row[1],
                "event_type": row[2],
                "machine_id": row[3],
                "outage_duration_min": row[4],
            }
            for row in rows
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or explicitly dispatch one local MES reschedule intent")
    parser.add_argument("--db", type=Path, help="SQLite runtime path; defaults to FACTORY_DB_PATH")
    parser.add_argument("--event-id", type=int)
    parser.add_argument("--outage-duration-min", type=int)
    parser.add_argument("--freeze-horizon-min", type=int, default=60)
    parser.add_argument("--execute", action="store_true", help="Allow one ACTIVE-changing dispatch")
    args = parser.parse_args()
    if args.execute and args.event_id is None:
        parser.error("--execute requires --event-id")
    if args.db is not None:
        os.environ["FACTORY_DB_PATH"] = str(args.db.resolve())
    db_path = resolve_db_path()
    if not db_path.is_file():
        parser.error("runtime database is missing")
    if args.execute:
        result = MESRescheduleDispatcher().dispatch_one(
            args.event_id,
            outage_duration_min=args.outage_duration_min,
            freeze_horizon_min=args.freeze_horizon_min,
        )
    else:
        result = inspect_pending(db_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
