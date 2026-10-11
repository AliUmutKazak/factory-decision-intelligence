"""Rehearse a consistent ACTIVE SQLite snapshot and sealed bundle in scratch storage."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from src.utils.db import get_active_run_id
from src.utils.run_bundle import sha256_file, verify_run_bundle
from src.utils.runtime_lock import run_mutation_lock


def _check_runtime(conn: sqlite3.Connection) -> str:
    if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise ValueError("runtime SQLite integrity_check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("runtime SQLite foreign_key_check failed")
    run_id = get_active_run_id(conn)
    for table in ("production_schedule", "schedule_solver_metadata"):
        if not conn.execute(f"SELECT 1 FROM {table} WHERE run_id = ? LIMIT 1", (run_id,)).fetchone():
            raise ValueError(f"ACTIVE {table} is missing")
    return run_id


def rehearse_active_restore(db_path: str | Path, bundles_dir: str | Path) -> dict:
    """Never replace the source; both backup and restore targets are temporary."""
    db_path = Path(db_path).resolve()
    bundles_dir = Path(bundles_dir).resolve()
    if not db_path.is_file():
        raise ValueError("runtime database is missing")
    with run_mutation_lock(db_path), tempfile.TemporaryDirectory(prefix="fdi-active-restore-") as scratch:
        scratch_path = Path(scratch)
        snapshot_db = scratch_path / "snapshot.db"
        restored_db = scratch_path / "restored.db"
        with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot_db)) as snapshot:
                source.backup(snapshot)
                run_id = _check_runtime(snapshot)
                bundle = bundles_dir / run_id
                if not bundle.is_dir() or any(path.is_symlink() for path in bundle.rglob("*")):
                    raise ValueError("ACTIVE sealed bundle is missing or contains a symbolic link")
                source_manifest = verify_run_bundle(bundle, run_id)
                manifest_hash = sha256_file(bundle / "manifest.json")
                with closing(sqlite3.connect(restored_db)) as restored:
                    snapshot.backup(restored)
                    if _check_runtime(restored) != run_id:
                        raise ValueError("restored ACTIVE run differs from snapshot")
        restored_bundle = scratch_path / "restored_bundle"
        shutil.copytree(bundle, restored_bundle)
        if verify_run_bundle(restored_bundle, run_id) != source_manifest:
            raise ValueError("restored bundle manifest differs from source")
        if sha256_file(restored_bundle / "manifest.json") != manifest_hash:
            raise ValueError("restored bundle manifest hash differs from source")
        if sha256_file(snapshot_db) != sha256_file(restored_db):
            # SQLite backups may differ bytewise while representing the same data.
            with closing(sqlite3.connect(snapshot_db)) as snapshot, closing(sqlite3.connect(restored_db)) as restored:
                if list(snapshot.iterdump()) != list(restored.iterdump()):
                    raise ValueError("restored database differs logically from snapshot")
        return {
            "status": "PASS",
            "active_run_id": run_id,
            "bundle_manifest_sha256": manifest_hash,
            "snapshot_integrity": "ok",
            "restored_integrity": "ok",
            "restored_bundle_verified": True,
            "scope": "LOCAL_ACTIVE_SNAPSHOT_RESTORED_IN_SCRATCH_NO_LIVE_RTO_RPO_PROOF",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehearse a local ACTIVE SQLite and bundle restore")
    parser.add_argument("db_path", type=Path)
    parser.add_argument("bundles_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(rehearse_active_restore(args.db_path, args.bundles_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
