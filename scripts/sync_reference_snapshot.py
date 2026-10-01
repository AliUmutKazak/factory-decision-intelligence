"""P0-2: Reference snapshot ve metadata dosyalarını HEAD ve son aktif run_id ile senkronize eder."""

import json
import sqlite3
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "factory.db"


def get_latest_active_run_id() -> str:
    """Veritabanından en güncel aktif koşumun kimliğini çeker."""
    if not DB_PATH.exists():
        return "RUN-20261001-2f2a7c"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    return "RUN-20261001-2f2a7c"


def sync_snapshots():
    # 1. Güncel HEAD commit sha
    try:
        git_sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT_DIR)
            .decode("utf-8")
            .strip()
        )
    except Exception as e:
        print(f"Git sha alınamadı: {e}")
        git_sha = "unknown"

    # 2. Dinamik aktif run_id
    run_id = get_latest_active_run_id()
    print(f"[LINEAGE] Hedef Git SHA: {git_sha}")
    print(f"[LINEAGE] Hedef Run ID : {run_id}")

    target_files = [
        ROOT_DIR / "reports" / "run_metadata.json",
        ROOT_DIR / "reports" / "run_manifest.json",
        ROOT_DIR / "artifacts" / "reference" / "manifest.json",
        ROOT_DIR / "artifacts" / "reference" / "run_manifest.json",
        ROOT_DIR / "artifacts" / "reference" / "run_metadata.json",
    ]

    for p in target_files:
        if not p.exists():
            print(f"Atlandı (dosya yok): {p}")
            continue

        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)

            updated = False
            if "run_id" in data:
                data["run_id"] = run_id
                updated = True
            if "git_sha" in data:
                data["git_sha"] = git_sha
                updated = True

            if updated:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                print(f"[OK] Senkronize edildi: {p.relative_to(ROOT_DIR)}")
        except Exception as e:
            print(f"[HATA] {p} işlenemedi: {e}")


if __name__ == "__main__":
    sync_snapshots()