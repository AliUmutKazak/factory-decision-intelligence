"""G3 laboratory copy/restore check for one immutable run bundle.

The source is never replaced. Snapshot and restored copies are temporary, and
this is not a live disaster-recovery or remote-backup procedure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from src.utils.run_bundle import verify_run_bundle


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rehearse_bundle_restore(
    source_bundle: str | Path,
    run_id: str,
    *,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Copy, restore, and verify a hash-pinned offline run bundle in scratch storage."""
    source_bundle = Path(source_bundle).resolve()
    manifest_path = source_bundle / "manifest.json"
    source_manifest_hash = _sha256(manifest_path)
    if source_manifest_hash.lower() != expected_manifest_sha256.lower():
        raise ValueError(f"source manifest SHA-256 mismatch: {source_manifest_hash}")
    if any(path.is_symlink() for path in source_bundle.rglob("*")):
        raise ValueError("bundle restore rehearsal refuses symbolic links")
    manifest = verify_run_bundle(source_bundle, run_id)

    with tempfile.TemporaryDirectory(prefix="fdi-bundle-restore-") as scratch:
        snapshot = Path(scratch) / "snapshot"
        restored = Path(scratch) / "restored"
        shutil.copytree(source_bundle, snapshot)
        snapshot_manifest = verify_run_bundle(snapshot, run_id)
        shutil.copytree(snapshot, restored)
        restored_manifest = verify_run_bundle(restored, run_id)
        if manifest != snapshot_manifest or manifest != restored_manifest:
            raise ValueError("restored manifest differs from source")
        if _sha256(restored / "manifest.json") != source_manifest_hash:
            raise ValueError("restored manifest hash differs from source")

        database = restored / "factory.db"
        with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("restored SQLite integrity_check failed")
            if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("restored SQLite foreign_key_check failed")
            run_count = conn.execute("SELECT COUNT(*) FROM pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()[0]
            if run_count != 1:
                raise ValueError(f"restored database expected one pipeline run {run_id!r}, found {run_count}")

        verify_run_bundle(restored, run_id)
        if _sha256(manifest_path) != source_manifest_hash:
            raise ValueError("source manifest changed during rehearsal")
        verify_run_bundle(source_bundle, run_id)
        return {
            "status": "PASS",
            "source_bundle": source_bundle.name,
            "run_id": run_id,
            "manifest_sha256": source_manifest_hash,
            "code_sha256": _sha256(Path(__file__).resolve()),
            "payload_count": len(manifest["files"]),
            "payload_bytes": sum(int(entry["bytes"]) for entry in manifest["files"].values()),
            "snapshot_verified": True,
            "restored_verified": True,
            "restored_sqlite_integrity": "ok",
            "restored_sqlite_foreign_keys": "ok",
            "source_unchanged": True,
            "scope": "LAB_OFFLINE_SEALED_BUNDLE_ONLY_NO_LIVE_RTO_RPO_PROOF",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline sealed run-bundle restore rehearsal")
    parser.add_argument("source_bundle", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            rehearse_bundle_restore(
                args.source_bundle,
                args.run_id,
                expected_manifest_sha256=args.manifest_sha256,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
