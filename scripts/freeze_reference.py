"""Freeze an ACTIVE run bundle into the immutable reference snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.utils.db import get_db_connection
from src.utils.run_bundle import verify_run_bundle


def run_cmd(cmd_list: list[str]) -> str:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        cmd_list,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Komut başarısız: {' '.join(cmd_list)}\n{result.stderr}")
    return result.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_active_run() -> dict[str, str]:
    db_path = BASE_DIR / "data" / "factory.db"
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT run_id, git_sha, config_hash, data_source, status "
            "FROM pipeline_runs WHERE status = 'ACTIVE' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise RuntimeError("ACTIVE pipeline run bulunamadı.")
    return {
        "run_id": str(row[0]),
        "git_sha": str(row[1] or "UNKNOWN"),
        "config_hash": str(row[2] or "UNKNOWN"),
        "data_source": str(row[3] or "UNKNOWN"),
        "status": str(row[4]),
    }


def copy_bundle_to_reference_staging(bundle: Path, staging: Path) -> None:
    processed = bundle / "data" / "processed"
    reports = bundle / "reports"
    db_file = bundle / "factory.db"

    if not db_file.exists():
        raise RuntimeError(f"Run bundle DB eksik: {db_file}")
    if not processed.exists():
        raise RuntimeError(f"Run bundle processed dizini eksik: {processed}")
    if not reports.exists():
        raise RuntimeError(f"Run bundle reports dizini eksik: {reports}")

    for path in sorted(processed.glob("*.*")):
        if path.is_file():
            shutil.copy2(path, staging / path.name)
    for path in sorted(reports.glob("*.*")):
        if path.is_file():
            shutil.copy2(path, staging / path.name)
    shutil.copy2(db_file, staging / "factory.db")


RUN_SCOPED_REFERENCE_FILES = {
    "forecast_demand.csv",
    "forecast_model_lineage.csv",
    "aggregate_plan.csv",
    "sku_production_plan.csv",
    "machine_capacity_plan.csv",
    "mrp_plan.csv",
    "production_schedule.csv",
    "energy_kpis.csv",
    "energy_profile_15min.csv",
    "energy_machine_kpis.csv",
    "carbon_analytics.csv",
    "carbon_machine_kpis.csv",
    "carbon_price_scenarios.csv",
}


def verify_csv_lineage(staging: Path, run_id: str) -> None:
    import pandas as pd

    for filename in sorted(RUN_SCOPED_REFERENCE_FILES):
        path = staging / filename
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if "run_id" not in df.columns:
            raise RuntimeError(f"Reference artifact run_id kolonsuz: {filename}")
        actual = {str(value) for value in df["run_id"].dropna().unique()}
        if actual != {run_id}:
            raise RuntimeError(f"Reference lineage mismatch: {filename}: {actual} != {{{run_id}}}")


def build_manifest(staging: Path, run: dict[str, str], bundle: Path) -> dict:
    files = {}
    for path in sorted(staging.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            files[path.name] = {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "logical_role": "run_database" if path.suffix == ".db" else "run_artifact",
                "schema_version": "1.0",
            }

    source_manifest = bundle / "manifest.json"
    return {
        "run_id": run["run_id"],
        "git_sha": run["git_sha"],
        "config_hash": run["config_hash"],
        "data_source": run["data_source"],
        "source_bundle": str(bundle.relative_to(BASE_DIR)).replace("\\", "/"),
        "source_bundle_manifest_sha256": (sha256(source_manifest) if source_manifest.exists() else None),
        "created_at": datetime.now(UTC).isoformat(),
        "files": files,
    }


def assert_versioned_snapshot_immutable(versioned_dir: Path, manifest: dict) -> None:
    if not versioned_dir.exists():
        return
    existing_manifest = versioned_dir / "manifest.json"
    if not existing_manifest.exists():
        raise RuntimeError(f"Mevcut versioned reference manifest eksik: {versioned_dir}")
    existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
    if existing.get("run_id") != manifest["run_id"]:
        raise RuntimeError("Versioned reference run_id uyuşmazlığı.")
    existing_files = existing.get("files", {})
    if existing_files != manifest.get("files", {}):
        raise RuntimeError("Immutable reference ihlali: aynı run_id için farklı payload üretildi.")


def freeze_reference_atomic(run_pipeline: bool = True) -> None:
    if run_pipeline:
        run_cmd([sys.executable, "main.py"])

    run = get_active_run()
    run_id = run["run_id"]
    bundle = BASE_DIR / "artifacts" / "runs" / run_id
    if not bundle.exists():
        raise RuntimeError(f"ACTIVE run bundle bulunamadı: {bundle}")
    verify_run_bundle(bundle, run_id)

    staging = BASE_DIR / "artifacts" / "staging_reference"
    reference = BASE_DIR / "artifacts" / "reference"
    backup = BASE_DIR / "artifacts" / "reference_backup"
    versioned = BASE_DIR / "artifacts" / "reference_runs" / run_id

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    copy_bundle_to_reference_staging(bundle, staging)
    verify_csv_lineage(staging, run_id)
    manifest = build_manifest(staging, run, bundle)
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    assert_versioned_snapshot_immutable(versioned, manifest)
    if not versioned.exists():
        shutil.copytree(staging, versioned)

    if backup.exists():
        shutil.rmtree(backup)
    had_reference = reference.exists()
    try:
        if had_reference:
            reference.rename(backup)
        staging.rename(reference)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if not reference.exists() and backup.exists():
            backup.rename(reference)
        raise

    print(f"[REFERENCE SEALED] run={run_id} git={run['git_sha'][:12]} files={len(manifest['files'])}")


if __name__ == "__main__":
    freeze_reference_atomic()
