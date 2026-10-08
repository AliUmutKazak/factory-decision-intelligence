"""A backup must restore the same logical data without touching its source."""

import hashlib
import sqlite3
from contextlib import closing

import pytest

from src.utils.sqlite_restore_rehearsal import rehearse_sqlite_backup_restore


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_offline_backup_restore_preserves_data_and_source(tmp_path):
    source = tmp_path / "factory.db"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, label TEXT NOT NULL)")
        conn.execute("CREATE TABLE operations (id INTEGER PRIMARY KEY, job_id INTEGER REFERENCES jobs(id))")
        conn.execute("CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        conn.execute("INSERT INTO jobs VALUES (1, 'sample')")
        conn.execute("INSERT INTO operations VALUES (1, 1)")
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-1', 'COMPLETED')")
        conn.commit()
    original_hash = _sha256(source)

    report = rehearse_sqlite_backup_restore(source, expected_sha256=original_hash)

    assert report["status"] == "PASS"
    assert report["source_sha256"] == original_hash == _sha256(source)
    assert len(report["logical_sha256"]) == 64
    assert report["table_count"] == 3
    assert report["pipeline_run_count"] == 1
    assert report["source_unchanged"] is True
    assert list(tmp_path.iterdir()) == [source]


def test_hash_mismatch_rejects_before_backup(tmp_path):
    source = tmp_path / "factory.db"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER)")
        conn.commit()
    with pytest.raises(ValueError, match="source SHA-256 mismatch"):
        rehearse_sqlite_backup_restore(source, expected_sha256="0" * 64)
    assert list(tmp_path.iterdir()) == [source]


def test_offline_rehearsal_rejects_wal_sidecar(tmp_path):
    source = tmp_path / "factory.db"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER)")
        conn.commit()
    source.with_name(source.name + "-wal").write_bytes(b"uncheckpointed data")
    with pytest.raises(ValueError, match="WAL file"):
        rehearse_sqlite_backup_restore(source, expected_sha256=_sha256(source))
