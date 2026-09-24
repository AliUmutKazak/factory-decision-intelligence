import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def get_git_head_sha() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "UNKNOWN"


def main():
    print("=" * 60)
    print("1. Pipeline Calistiriliyor (main.py)...")
    print("=" * 60)

    result = subprocess.run([sys.executable, "main.py"], cwd=str(ROOT_DIR))
    if result.returncode != 0:
        print("[HATA] Pipeline kosusu basarisiz oldu!")
        sys.exit(1)

    # run_metadata.json içinden gerçek tekil run_id bilgisini al
    run_meta_path = ROOT_DIR / "reports" / "run_metadata.json"
    active_run_id = "UNKNOWN"
    if run_meta_path.exists():
        with open(run_meta_path, "r", encoding="utf-8") as f:
            rdata = json.load(f)
            active_run_id = rdata.get("run_id", "UNKNOWN")

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

    current_git_sha = get_git_head_sha()

    print("\n3. Tekil Lineage SHA-256 Manifest Olusturuluyor...")
    manifest_data = {
        "version": "1.0",
        "description": "Deterministic canonical baseline reference artifacts",
        "run_id": active_run_id,
        "git_sha": current_git_sha,
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

    print("\n4. artifacts/reference/ Klasoru Temizlenip Atomik Promote Ediliyor...")
    ref_dir = ROOT_DIR / "artifacts" / "reference"
    ref_dir.mkdir(parents=True, exist_ok=True)

    # Eski kalıntıları temizle (reference_run_metadata.json gibi çift başlılıkları önlemek için)
    for old_item in ref_dir.iterdir():
        if old_item.name not in [f.name for f in copied_files] and old_item.name != "manifest.json":
            if old_item.is_file():
                old_item.unlink()

    # Staging dosyalarını taşı
    for item in staging_dir.iterdir():
        dest_item = ref_dir / item.name
        if dest_item.exists():
            dest_item.unlink()
        shutil.copy2(item, dest_item)

    shutil.rmtree(staging_dir.parent)
    print("=" * 60)
    print(f"CANONICAL RUN SABITLENDI: {active_run_id} | Git: {current_git_sha[:8]}")
    print("=" * 60)


if __name__ == "__main__":
    main()