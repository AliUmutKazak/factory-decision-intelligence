"""A local ACTIVE version and its sealed bundle restore together."""

import shutil
import sqlite3

import pytest

from src.utils.active_restore_rehearsal import rehearse_active_restore
from src.utils.run_bundle import RunBundleError, seal_run_bundle, sha256_file


def _runtime(tmp_path):
    db_path = tmp_path / "factory.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL);
            CREATE TABLE production_schedule (run_id TEXT NOT NULL, task_id TEXT NOT NULL);
            CREATE TABLE schedule_solver_metadata (run_id TEXT NOT NULL, status TEXT NOT NULL);
            INSERT INTO pipeline_runs VALUES ('RUN-1', 'ACTIVE');
            INSERT INTO production_schedule VALUES ('RUN-1', 'TASK-1');
            INSERT INTO schedule_solver_metadata VALUES ('RUN-1', 'FEASIBLE');
            """
        )
    bundle = tmp_path / "bundles" / "RUN-1"
    bundle.mkdir(parents=True)
    shutil.copy2(db_path, bundle / "factory.db")
    seal_run_bundle(bundle, "RUN-1")
    return db_path, bundle


def test_active_snapshot_and_bundle_restore_without_changing_source(tmp_path):
    db_path, bundle = _runtime(tmp_path)
    before = sha256_file(db_path)
    manifest_before = sha256_file(bundle / "manifest.json")
    report = rehearse_active_restore(db_path, bundle.parent)
    assert report["status"] == "PASS"
    assert report["active_run_id"] == "RUN-1"
    assert report["bundle_manifest_sha256"] == manifest_before
    assert sha256_file(db_path) == before
    assert sha256_file(bundle / "manifest.json") == manifest_before


def test_active_restore_rejects_corrupt_bundle(tmp_path):
    db_path, bundle = _runtime(tmp_path)
    (bundle / "factory.db").write_bytes(b"corrupt")
    with pytest.raises(RunBundleError, match="hash mismatch"):
        rehearse_active_restore(db_path, bundle.parent)
