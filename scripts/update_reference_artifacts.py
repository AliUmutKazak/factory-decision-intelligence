import datetime
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from src.utils.lineage import get_active_pipeline_run

root = Path(".")
ref_dir = root / "artifacts" / "reference"
ref_dir.mkdir(parents=True, exist_ok=True)

# 1. Git SHA ve Aktif Run ID
git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
active_info = get_active_pipeline_run()
if isinstance(active_info, dict):
    run_id = active_info["run_id"]
else:
    run_id = str(active_info or "RUN-REFERENCE")

print(f"[REFERENCE SEAL] Run ID: {run_id} | Git SHA: {git_sha[:8]}")

# 2. Şablon dosya listesi ve rolleri
file_definitions = {
    "aggregate_plan.csv": ("data/processed", "aggregate_production_plan"),
    "carbon_analytics.csv": ("data/processed", "carbon_emission_analytics"),
    "carbon_machine_kpis.csv": ("data/processed", "machine_level_carbon_kpis"),
    "energy_kpis.csv": ("data/processed", "energy_consumption_kpis"),
    "energy_profile_15min.csv": ("data/processed", "energy_load_profile_15min"),
    "factory.db": ("data", "operational_system_database"),
    "factory_orders.csv": ("data/processed", "factory_production_orders"),
    "forecast_demand.csv": ("data/processed", "demand_forecast"),
    "forecast_model_lineage.csv": ("data/processed", "forecast_feature_lineage"),
    "forecast_model_metadata.json": ("reports", "forecast_model_hyperparameters"),
    "machine_capacity_plan.csv": ("data/processed", "machine_capacity_utilization"),
    "mrp_plan.csv": ("data/processed", "material_requirements_plan"),
    "production_schedule.csv": ("data/processed", "detailed_production_schedule"),
    "schedule_solver_metadata.json": ("reports", "optimization_solver_run_stats"),
    "sku_production_plan.csv": ("data/processed", "sku_level_production_plan"),
}

files_meta = {}

for fname, (source_folder, logical_role) in file_definitions.items():
    src = root / source_folder / fname
    dst = ref_dir / fname

    if src.exists():
        shutil.copy2(src, dst)
    elif not dst.exists():
        print(f"Uyarı: {fname} kaynağı bulunamadı!")
        continue

    with open(dst, "rb") as bf:
        sha = hashlib.sha256(bf.read()).hexdigest()

    files_meta[fname] = {
        "sha256": sha,
        "bytes": dst.stat().st_size,
        "logical_role": logical_role,
        "schema_version": "1.0.0",
    }

manifest_payload = {
    "run_id": run_id,
    "git_sha": git_sha,
    "timestamp": datetime.datetime.now().isoformat(),
    "files": files_meta,
}

manifest_file = ref_dir / "manifest.json"
manifest_file.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[OK] Reference manifest başarıyla mühürlendi ({len(files_meta)} dosya).")