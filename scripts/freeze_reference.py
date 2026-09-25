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

    # 1. Son basarili calismanin run_id ve git_sha bilgisini veritabanindan cek
    db_path = BASE_DIR / "data" / "factory.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT run_id, git_sha FROM pipeline_runs WHERE status IN ('SUCCESS', 'COMPLETED') ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row:
        print("[ERROR] pipeline_runs tablosunda basarili run bulunamadi!")
        sys.exit(1)

    run_id, git_sha = row[0], row[1]
    print(f"\n[INFO] Referans Alinacak Run: {run_id} | Git SHA: {git_sha}")

    # 2. Dizin Yollari
    ref_dir = BASE_DIR / "artifacts" / "reference"
    staging_dir = BASE_DIR / "artifacts" / "staging_reference"
    backup_dir = BASE_DIR / "artifacts" / "reference_backup"
    versioned_dir = BASE_DIR / "artifacts" / "reference_runs" / run_id

    # Temiz bir staging dizini ac
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    print("\n2. Dosyalar Izole Staging Alanina Hazirlaniyor...")

    # Kopyalanacak artifact kaynaklari
    sources = [
        BASE_DIR / "data" / "processed",
        BASE_DIR / "reports",
        BASE_DIR / "data" / "factory.db"
    ]

    copied_count = 0
    for src in sources:
        if src.is_dir():
            for item in src.iterdir():
                if item.is_file() and not item.name.endswith(".tmp") and item.name != "run_manifest.json":
                    shutil.copy2(item, staging_dir / item.name)
                    copied_count += 1
        elif src.is_file():
            shutil.copy2(src, staging_dir / src.name)
            copied_count += 1

    print(f"Toplam {copied_count} artifact staging alanina alindi.")

    # 3. Staging alaninda SHA-256 Manifest olustur
    print("\n3. Staging Icin Kriptografik SHA-256 Manifest Olusturuluyor...")
    import hashlib
    import json
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
            manifest_files[p.name] = {
                "sha256": get_full_sha256(p),
                "bytes": p.stat().st_size
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

        # B) Staging'i gercek referans dizinine atomik olarak tasi
        staging_dir.rename(ref_dir)

        # C) Basarili olduysa eski backup'i kaldir
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        print("============================================================")
        print(f"CANONICAL RUN ATOMIK OLARAK SABITLENDI: {run_id} | Git: {git_sha[:8]}")
        print("============================================================")

    except Exception as e:
        print(f"[FATAL] Atomic Swap sirasinda hata olustu: {e}")
        print("[ROLLBACK] Eski referans geri yukleniyor...")
        if backup_dir.exists() and not ref_dir.exists():
            backup_dir.rename(ref_dir)
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        sys.exit(1)

if __name__ == "__main__":
    freeze_reference_atomic()