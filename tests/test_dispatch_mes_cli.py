"""The manual inspect path must not change the MES runtime."""

import sqlite3

from scripts.dispatch_mes_intent import inspect_pending
from src.utils.run_bundle import sha256_file


def test_pending_inspection_is_read_only(tmp_path):
    db = tmp_path / "factory.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE mes_execution_events (
                event_id INTEGER PRIMARY KEY, event_type TEXT, machine_id TEXT, actual_duration_min INTEGER
            );
            CREATE TABLE mes_reschedule_outbox (event_id INTEGER, run_id TEXT, status TEXT);
            INSERT INTO mes_execution_events VALUES (7, 'MACHINE_DOWN', 'M01', 45);
            INSERT INTO mes_reschedule_outbox VALUES (7, 'RUN-A', 'PENDING');
            """
        )
    before = sha256_file(db)
    report = inspect_pending(db)
    assert report == {
        "status": "INSPECT_ONLY",
        "pending_intents": [
            {
                "event_id": 7,
                "run_id": "RUN-A",
                "event_type": "MACHINE_DOWN",
                "machine_id": "M01",
                "outage_duration_min": 45,
            }
        ],
    }
    assert sha256_file(db) == before
