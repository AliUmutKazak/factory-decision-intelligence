"""The reschedule artifact reader must release SQLite before returning."""

import sqlite3
from contextlib import closing
from types import SimpleNamespace

from src.config import runtime_path_context
from src.scheduling.rescheduler import DynamicRescheduler


def test_artifact_reader_closes_database_connection(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    db_path = root / "data" / "factory.db"
    db_path.parent.mkdir(parents=True)
    real_connect = sqlite3.connect
    with closing(real_connect(db_path)) as conn:
        conn.execute("CREATE TABLE production_schedule (run_id TEXT, task_id TEXT)")
        conn.execute(
            "CREATE TABLE pipeline_runs (run_id TEXT, timestamp TEXT, trigger_source TEXT, "
            "orders_count INTEGER, git_sha TEXT, config_hash TEXT, data_source TEXT, status TEXT)"
        )
        conn.execute("INSERT INTO pipeline_runs (run_id, status) VALUES ('TEST-RUN', 'COMPLETED')")
        conn.commit()

    opened = []

    class TracedConnection(sqlite3.Connection):
        def close(self):
            self.was_closed = True
            return super().close()

    def traced_connect(*args, **kwargs):
        conn = real_connect(*args, factory=TracedConnection, **kwargs)
        conn.was_closed = False
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    audit = SimpleNamespace(previous_run_id="BASE", audit_id="AUD-1", trigger_event_id="EVT-1")
    with runtime_path_context(base_dir=root, data_dir=db_path.parent, db_path=db_path):
        engine = DynamicRescheduler(str(db_path))
        monkeypatch.setattr(engine, "_metadata_dict", lambda _meta, run_id: {"run_id": run_id})
        engine._write_run_artifacts("TEST-RUN", None, audit)

    assert len(opened) == 1
    assert opened[0].was_closed
    db_path.unlink()  # Windows refuses this if the SQLite handle is still open.
