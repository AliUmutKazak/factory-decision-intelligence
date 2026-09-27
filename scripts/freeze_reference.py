"""
scripts/freeze_reference.py
----------------------------
Artifact Reference Snapshot Freezer (Production-Grade Atomic Swap).

Garantiler:
1. Versioned Immutable Snapshot: artifacts/reference_runs/<RUN_ID>/ altına arşivler.
2. Atomic Swap: Dosyaları tek tek silip kopyalamaz; os.replace ve backup-rollback mekanizmasıyla
   işletim sistemi seviyesinde atomik dizin değişimi yapar. Çökme anında referans asla yarım kalmaz.
"""

import os
import sys
import shutil
import sqlite3
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
from src.utils.db import get_db_connection

from src.utils.lineage import generate_run_manifest, compute_file_hash

def run_cmd(cmd_list):
    # Windows konsolunda UTF-8 (✓ vb. karakterler) kodlama hatası almamak için env zorlaması
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    res = subprocess.run(cmd_list, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", env=env)
    if res.returncode != 0:
        print(f"[ERROR] Komut basarisiz: {' '.join(cmd_list)}")
        print(res.stderr)
        sys.exit(1)
    return res.stdout

def freeze_reference_atomic():
    print("============================================================")
    print("1. Pipeline Calistiriliyor (main.py)...")
    print("============================================================")
    run_cmd([sys.executable, "main.py"])

    # 1. En guncel ACTIVE pipeline run'i ve git_sha bilgisini veritabanindan cek
    db_path = BASE_DIR / "data" / "factory.db"
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT run_id, git_sha, status FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row:
        print("[ERROR] pipeline_runs tablosunda ACTIVE durumunda run bulunamadi!")
        sys.exit(1)

    run_id, git_sha, status = row[0], row[1], row[2]
    print(f"\n[INFO] Referans Alinacak ACTIVE Run: {run_id} | Git SHA: {git_sha}")

    # 1.1. run_metadata.json ile SQLite ACTIVE run mutabakati
    meta_path = BASE_DIR / "reports" / "run_metadata.json"
    if not meta_path.exists():
        print(f"[ERROR] {meta_path} bulunamadi!")
        sys.exit(1)

    import json
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_data = json.load(f)

    if meta_data.get("run_id") != run_id:
        print(f"[ERROR] Metadata run_id ({meta_data.get('run_id')}) ile DB ACTIVE run_id ({run_id}) uyusmuyor!")
        sys.exit(1)

    # 2. Dizin Yollari
    ref_dir = BASE_DIR / "artifacts" / "reference"
    staging_dir = BASE_DIR / "artifacts" / "staging_reference"
    backup_dir = BASE_DIR / "artifacts" / "reference_backup"
    versioned_dir = BASE_DIR / "artifacts" / "reference_runs" / run_id

    # Temiz bir staging dizini ac
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    print("\n2. Dosyalar Izole Staging Alanina Hazirlaniyor (CANONICAL ALLOWLIST)...")

    # Madde 24: Single Source of Truth - Resmi Kanonik Çıktı Listesi (Allowlist)
    # reference_run_metadata.json gibi gayriresmi veya eski meta dosyalarının sızması engellenir.
    # Madde 25: Kurumsal Artifact Governance - Explicit Reference Artifact Catalog
    CANONICAL_REFERENCE_ARTIFACTS = {
        "data/processed/forecast_demand.csv": {
            "logical_role": "demand_forecast",
            "schema_version": "1.0.0",
        },
        "data/processed/aggregate_plan.csv": {
            "logical_role": "aggregate_production_plan",
            "schema_version": "1.0.0",
        },
        "data/processed/sku_production_plan.csv": {
            "logical_role": "sku_level_production_plan",
            "schema_version": "1.0.0",
        },
        "data/processed/production_schedule.csv": {
            "logical_role": "detailed_production_schedule",
            "schema_version": "1.0.0",
        },
        "data/processed/mrp_plan.csv": {
            "logical_role": "material_requirements_plan",
            "schema_version": "1.0.0",
        },
        "data/processed/energy_profile_15min.csv": {
            "logical_role": "energy_load_profile_15min",
            "schema_version": "1.0.0",
        },
        "data/processed/energy_kpis.csv": {
            "logical_role": "energy_consumption_kpis",
            "schema_version": "1.0.0",
        },
        "data/processed/carbon_analytics.csv": {
            "logical_role": "carbon_emission_analytics",
            "schema_version": "1.0.0",
        },
        "data/processed/carbon_machine_kpis.csv": {
            "logical_role": "machine_level_carbon_kpis",
            "schema_version": "1.0.0",
        },
        "data/processed/factory_orders.csv": {
            "logical_role": "factory_production_orders",
            "schema_version": "1.0.0",
        },
        "data/processed/machine_capacity_plan.csv": {
            "logical_role": "machine_capacity_utilization",
            "schema_version": "1.0.0",
        },
        "data/processed/forecast_model_lineage.csv": {
            "logical_role": "forecast_feature_lineage",
            "schema_version": "1.0.0",
        },
        "reports/forecast_model_metadata.json": {
            "logical_role": "forecast_model_hyperparameters",
            "schema_version": "1.0.0",
        },
        "reports/schedule_solver_metadata.json": {
            "logical_role": "optimization_solver_run_stats",
            "schema_version": "1.0.0",
        },
        "reports/schedule_solver_metadata.csv": {
            "logical_role": "optimization_solver_kpis_tabular",
            "schema_version": "1.0.0",
        },
        "data/factory.db": {
            "logical_role": "operational_system_database",
            "schema_version": "1.0.0",
        },
    }

    copied_count = 0
    catalog_metadata = {}
    for rel_path, meta in sorted(CANONICAL_REFERENCE_ARTIFACTS.items()):
        src_file = BASE_DIR / rel_path
        if src_file.exists() and src_file.is_file():
            shutil.copy2(src_file, staging_dir / src_file.name)
            copied_count += 1
            catalog_metadata[src_file.name] = meta
        else:
            print(f"  [UYARI] Kanonik artifact henüz mevcut değil veya opsiyonel: {rel_path}")

    print(f"Toplam {copied_count} kanonik artifact staging alanina alindi.")

    # 3. Staging alaninda SHA-256 Manifest olustur
    print("\n3. Staging Icin Kriptografik SHA-256 Manifest Olusturuluyor...")
    import hashlib
    from datetime import datetime

    def get_full_sha256(file_path):
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    manifest_files = {}
    for p in sorted(staging_dir.iterdir()):
        if p.is_file() and p.name != "manifest.json":
            file_meta = catalog_metadata.get(p.name, {})
            manifest_files[p.name] = {
                "sha256": get_full_sha256(p),
                "bytes": p.stat().st_size,
                "logical_role": file_meta.get("logical_role", "unknown"),
                "schema_version": file_meta.get("schema_version", "1.0.0"),
            }

    manifest_data = {
        "run_id": run_id,
        "git_sha": git_sha,
        "timestamp": datetime.now().isoformat(),
        "files": manifest_files
    }

    with open(staging_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    print(f"Manifest mühürlendi ({len(manifest_files)} dosya).")

    # 4. Versioned Immutable Snapshot Arsivle
    print(f"\n4. Versioned Snapshot Kaydediliyor -> {versioned_dir}...")
    if versioned_dir.exists():
        shutil.rmtree(versioned_dir)
    shutil.copytree(staging_dir, versioned_dir)

    # 5. ATOMIC DIRECTORY SWAP
    print("\n5. ATOMIK PROMOTION UYGULANIYOR (Directory Swap)...")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    had_previous_ref = ref_dir.exists()

    try:
        # A) Mevcut referans varsa backup'a tasi
        if had_previous_ref:
            ref_dir.rename(backup_dir)

        # B) Staging dizinini ana referans yap
        staging_dir.rename(ref_dir)

        # C) Basarili olduysa backup'i temizle
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        print("✓ Referans basariyla guncellendi (Atomic Swap OK).")

        # 6. Disk Artifact & Run Retention Senkronizasyonu (Madde 23)
        from src.utils.lineage import apply_run_retention_policy
        apply_run_retention_policy(keep_last_n=20, db_path=str(BASE_DIR / "data" / "factory.db"))
        print("✓ Disk artifact snapshot retention senkronizasyonu tamamlandı.")

    except Exception as e:
        print(f"[CRITICAL ERROR] Atomic Swap sirasinda hata olustu: {e}")
        # Rollback
        if not ref_dir.exists() and backup_dir.exists():
            backup_dir.rename(ref_dir)
            print("↺ Rollback yapildi: Eski referans geri yuklendi.")
        sys.exit(1)

if __name__ == "__main__":
    freeze_reference_atomic()