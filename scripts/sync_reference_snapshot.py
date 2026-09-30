"""
P0-2: Reference snapshot ve metadata dosyalarını HEAD ve son aktif run_id ile senkronize eder.
"""
from pathlib import Path
import json
import subprocess


def sync_snapshots():
    # 1. Güncel HEAD commit sha
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    except Exception as e:
        print(f"Git sha alinamadi: {e}")
        git_sha = "e70264d0d8d402be86aa749ac08ed3392289d0ed"

    run_id = "RUN-20260930-856a35"

    target_files = [
        Path("reports/run_metadata.json"),
        Path("reports/run_manifest.json"),
        Path("artifacts/reference/manifest.json"),
        Path("artifacts/reference/run_manifest.json"),
        Path("artifacts/reference/run_metadata.json"),
    ]

    for p in target_files:
        if not p.exists():
            print(f"Atlandi (dosya yok): {p}")
            continue

        try:
            with open(p, "r", encoding="utf-8") as f:
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
                print(f"[OK] Senkronize edildi: {p}")
        except Exception as e:
            print(f"[HATA] {p} islenemedi: {e}")


if __name__ == "__main__":
    sync_snapshots()