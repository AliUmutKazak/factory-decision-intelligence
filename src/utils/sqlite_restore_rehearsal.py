"""Read-only G3 laboratory rehearsal for a sealed SQLite reference database.

This checks that SQLite's online backup API produces a restorable database.
Both backup and restored copy live in a temporary directory; this module does
not replace the runtime database or restore a complete run artifact bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _logical_sha256(conn: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for statement in conn.iterdump():
        digest.update(statement.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _validate_copy(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise ValueError("SQLite integrity_check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign_key_check failed")


def rehearse_sqlite_backup_restore(source_path: str | Path, *, expected_sha256: str) -> dict[str, Any]:
    """Back up and restore an offline, hash-pinned SQLite file in temporary storage."""
    source_path = Path(source_path).resolve()
    source_sha256 = _sha256(source_path)
    if source_sha256.lower() != expected_sha256.lower():
        raise ValueError(f"source SHA-256 mismatch: {source_sha256}")
    if source_path.with_name(source_path.name + "-wal").exists():
        raise ValueError("offline rehearsal refuses a source with a WAL file")

    with tempfile.TemporaryDirectory(prefix="fdi-restore-rehearsal-") as scratch:
        backup_path = Path(scratch) / "snapshot.db"
        restored_path = Path(scratch) / "restored.db"
        source = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
        try:
            source.execute("PRAGMA query_only = ON")
            _validate_copy(source)
            with closing(sqlite3.connect(backup_path)) as backup:
                source.backup(backup)
                _validate_copy(backup)
                source_digest = _logical_sha256(source)
                snapshot_digest = _logical_sha256(backup)
                if source_digest != snapshot_digest:
                    raise ValueError("snapshot differs logically from source")
                with closing(sqlite3.connect(restored_path)) as restored:
                    backup.backup(restored)
                    _validate_copy(restored)
                    restored_digest = _logical_sha256(restored)
                    if snapshot_digest != restored_digest:
                        raise ValueError("restored database differs logically from snapshot")
                    table_count = restored.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchone()[0]
                    run_table = restored.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pipeline_runs'"
                    ).fetchone()
                    run_count = (
                        restored.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] if run_table else None
                    )
        finally:
            source.close()
        if _sha256(source_path) != source_sha256:
            raise ValueError("source database changed during rehearsal")
        return {
            "status": "PASS",
            "source_sha256": source_sha256,
            "code_sha256": _sha256(Path(__file__).resolve()),
            "snapshot_sha256": _sha256(backup_path),
            "restored_sha256": _sha256(restored_path),
            "logical_sha256": snapshot_digest,
            "sqlite_version": sqlite3.sqlite_version,
            "python_version": platform.python_version(),
            "table_count": table_count,
            "pipeline_run_count": run_count,
            "integrity_check": "ok",
            "foreign_key_check": "ok",
            "source_unchanged": True,
            "scope": "LAB_OFFLINE_SQLITE_DB_ONLY_NO_LIVE_OR_BUNDLE_RECOVERY_PROOF",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline SQLite backup and restore rehearsal")
    parser.add_argument("source", type=Path)
    parser.add_argument("--sha256", required=True, help="Expected SHA-256 of the offline source database")
    args = parser.parse_args()
    print(json.dumps(rehearse_sqlite_backup_restore(args.source, expected_sha256=args.sha256), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
