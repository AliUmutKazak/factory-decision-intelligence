import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

# Proje kök dizinini belirle
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("=" * 60)
    print("1. Pipeline Calistiriliyor (main.py)...")
    print("=" * 60)

    # Proje kökündeki ana pipeline dosyasını çalıştır
    result = subprocess.run([sys.executable, "main.py"], cwd=str(ROOT_DIR))
    if result.returncode != 0:
        print("[HATA] Pipeline kosusu basarisiz oldu!")
        sys.exit(1)

    staging_dir = ROOT_DIR / "staging" / "reference_run"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    target_files = [
        ROOT_DIR / "data" / "processed" / "aggregate_plan.csv",
        ROOT_DIR / "data" / "processed" / "carbon_analytics.csv",
        ROOT_DIR / "data" / "processed" / "carbon_machine_kpis.csv",
        ROOT_DIR / "data" / "processed" / "energy_kpis.csv",
        ROOT_DIR / "data" / "processed" / "energy_profile_15min.csv",
        ROOT_DIR / "data" / "processed" / "factory_orders.csv",
        ROOT_DIR / "data" / "processed" / "forecast_demand.csv",
        ROOT_DIR / "data" / "processed" / "forecast_model_lineage.csv",
        ROOT_DIR / "data" / "processed" / "machine_capacity_plan.csv",
        ROOT_DIR / "data" / "processed" / "mrp_plan.csv",
        ROOT_DIR / "data" / "processed" / "production_schedule.csv",
        ROOT_DIR / "data" / "processed" / "schedule_solver_metadata.csv",
        ROOT_DIR / "data" / "processed" / "sku_production_plan.csv",
        ROOT_DIR / "data" / "factory.db",
        ROOT_DIR / "reports" / "forecast_model_metadata.json",
        ROOT_DIR / "reports" / "run_metadata.json",
        ROOT_DIR / "reports" / "schedule_solver_metadata.json",
    ]

    print("\n2. Dosyalar Staging Alanina Aliniyor...")
    copied_files = []
    for f in target_files:
        if f.exists():
            dest = staging_dir / f.name
            shutil.copy2(f, dest)
            copied_files.append(dest)
        else:
            print(f"[UYARI] Bulunamadi: {f.name}")

    print(f"Toplam {len(copied_files)} dosya staging'e alindi.")

    print("\n3. SHA-256 Manifest Olusturuluyor...")
    manifest_data = {
        "version": "1.0",
        "description": "Deterministic baseline reference artifacts",
        "files": {},
    }

    for fpath in sorted(copied_files):
        manifest_data["files"][fpath.name] = {
            "sha256": compute_sha256(fpath),
            "bytes": fpath.stat().st_size,
        }

    manifest_path = staging_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    print("\n4. Atomik Olarak artifacts/reference/ Dizinine Aktariliyor...")
    ref_dir = ROOT_DIR / "artifacts" / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)

    for item in staging_dir.iterdir():
        dest_item = ref_dir / item.name
        if dest_item.exists():
            dest_item.unlink()
        shutil.copy2(item, dest_item)

    shutil.rmtree(staging_dir.parent)
    print("=" * 60)
    print("REFERANS VE MANIFEST ESITLENDI!")
    print("=" * 60)


if __name__ == "__main__":
    main()