"""Immutable run-bundle sealing and verification utilities."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class RunBundleError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seal_run_bundle(
    bundle_dir: str | Path,
    run_id: str,
    *,
    run_type: str = "PIPELINE",
    previous_run_id: str | None = None,
) -> dict:
    """Hash every bundle payload and atomically write its own manifest."""
    bundle = Path(bundle_dir)
    db_path = bundle / "factory.db"
    if not db_path.exists():
        raise RunBundleError(f"Run bundle database missing: {db_path}")

    files = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "manifest.json.tmp"}:
            continue
        relative = str(path.relative_to(bundle)).replace("\\", "/")
        files[relative] = {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }

    metadata = {}
    run_meta = bundle / "reports" / "run_metadata.json"
    if run_meta.exists():
        metadata = json.loads(run_meta.read_text(encoding="utf-8"))
        meta_run_id = metadata.get("run_id")
        if meta_run_id and str(meta_run_id) != str(run_id):
            raise RunBundleError(
                f"Bundle metadata run_id mismatch: {meta_run_id} != {run_id}"
            )

    manifest = {
        "run_id": run_id,
        "run_type": run_type,
        "previous_run_id": previous_run_id,
        "git_sha": metadata.get("git_sha"),
        "config_hash": metadata.get("config_hash"),
        "created_at": datetime.now(UTC).isoformat(),
        "files": files,
    }
    target = bundle / "manifest.json"
    temporary = bundle / "manifest.json.tmp"
    temporary.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(target)
    return manifest


def verify_run_bundle(bundle_dir: str | Path, expected_run_id: str) -> dict:
    """Fail closed if a sealed bundle is incomplete or any payload hash changed."""
    bundle = Path(bundle_dir)
    manifest_path = bundle / "manifest.json"
    if not manifest_path.exists():
        raise RunBundleError(f"Bundle manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if str(manifest.get("run_id")) != str(expected_run_id):
        raise RunBundleError(
            f"Bundle run_id mismatch: {manifest.get('run_id')} != {expected_run_id}"
        )

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise RunBundleError("Bundle manifest has no payload files.")
    for relative, expected in files.items():
        path = bundle / relative
        if not path.exists():
            raise RunBundleError(f"Bundle payload missing: {relative}")
        actual_hash = sha256_file(path)
        if actual_hash != expected.get("sha256"):
            raise RunBundleError(
                f"Bundle hash mismatch: {relative}: {actual_hash} != {expected.get('sha256')}"
            )
    return manifest
