"""The sealed run bundle must survive a copy/restore round trip."""

import hashlib
import sqlite3
from contextlib import closing

import pytest

from src.utils.bundle_restore_rehearsal import rehearse_bundle_restore
from src.utils.run_bundle import RunBundleError, seal_run_bundle


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed_bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with closing(sqlite3.connect(source / "factory.db")) as conn:
        conn.execute("CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        conn.execute("INSERT INTO pipeline_runs VALUES ('RUN-1', 'COMPLETED')")
        conn.commit()
    (source / "note.txt").write_text("research fixture", encoding="utf-8")
    seal_run_bundle(source, "RUN-1")
    return source


def test_rehearsal_restores_bundle_and_preserves_source(tmp_path):
    source = _sealed_bundle(tmp_path)
    manifest_hash = _sha256(source / "manifest.json")
    database_hash = _sha256(source / "factory.db")

    report = rehearse_bundle_restore(source, "RUN-1", expected_manifest_sha256=manifest_hash)

    assert report["status"] == "PASS"
    assert report["source_bundle"] == "source"
    assert report["payload_count"] == 2
    assert report["snapshot_verified"] and report["restored_verified"]
    assert report["source_unchanged"]
    assert _sha256(source / "manifest.json") == manifest_hash
    assert _sha256(source / "factory.db") == database_hash
    assert list(tmp_path.iterdir()) == [source]


def test_rehearsal_rejects_wrong_manifest_or_tampered_payload(tmp_path):
    source = _sealed_bundle(tmp_path)
    with pytest.raises(ValueError, match="source manifest SHA-256 mismatch"):
        rehearse_bundle_restore(source, "RUN-1", expected_manifest_sha256="0" * 64)

    manifest_hash = _sha256(source / "manifest.json")
    (source / "note.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(RunBundleError, match="Bundle hash mismatch"):
        rehearse_bundle_restore(source, "RUN-1", expected_manifest_sha256=manifest_hash)
