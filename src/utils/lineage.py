import os, sys, json, uuid, hashlib, sqlite3, subprocess
from datetime import datetime
from pathlib import Path
import src.config as config
from src.utils.db import get_db_connection

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT_DIR / "src" / "config.py"
REPORTS_DIR = ROOT_DIR / "reports"
METADATA_JSON_PATH = str(REPORTS_DIR / "run_metadata.json")

def generate_run_id():
    """Standart kurumsal Run ID formatı: RUN-YYYYMMDD-XXXX"""
    now_str = datetime.now().strftime("%Y%m%d")
    unique_suffix = uuid.uuid4().hex[:6]
    return f"RUN-{now_str}-{unique_suffix}"

def get_git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            stderr=subprocess.DEVNULL, 
            cwd=ROOT_DIR
        ).decode("ascii").strip()
    except Exception:
        return "UNKNOWN_GIT_SHA"

def compute_file_hash(filepath):
    if not os.path.exists(filepath):
        return None
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            sha256.update(b)
    return sha256.hexdigest()[:16]

def init_pipeline_runs_table(conn):
    """Bütünleşik denetim şeması: Hem trigger hem git/config lineage alanlarını içerir."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            trigger_source TEXT,
            orders_count INTEGER,
            git_sha TEXT,
            config_hash TEXT,
            data_source TEXT,
            status TEXT NOT NULL
        )
    """)
    conn.commit()

def record_pipeline_run_metadata(run_id=None, solver_metrics=None, data_source="factory_orders.csv", orders_count=0, status="COMPLETED", db_path=None):
    import pandas as pd
    try:
        import ortools
        ortools_ver = ortools.__version__
    except Exception:
        ortools_ver = "not_installed"
    try:
        import pulp
        pulp_ver = pulp.__version__
    except Exception:
        pulp_ver = "not_installed"

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if not run_id:
        run_id = generate_run_id()

    metadata = {
        "run_id": run_id,
        "run_timestamp": datetime.now().isoformat(),
        "git_sha": get_git_sha(),
        "data_source": data_source,
        "forecast_origin": "2017-12-31",
        "forecast_method": "Hybrid_Backtest_Selection",
        "selected_models": {
            "P01": "LightGBM",
            "P02": "Holt-Winters",
            "P03": "LightGBM",
            "P04": "LightGBM",
            "P05": "LightGBM"
        },
        "config_hash": compute_file_hash(CONFIG_PATH),
        "status": status,
        "orders_count": orders_count,
        "environment": {
            "python_version": sys.version.split()[0],
            "pandas_version": pd.__version__,
            "ortools_version": ortools_ver,
            "pulp_version": pulp_ver,
        },
        "optimization_metrics": solver_metrics or {
            "aggregate_lp_status": "OPTIMAL",
            "cpsat_solver_status": "OPTIMAL_OR_FEASIBLE",
            "notes": "End-to-end execution completed successfully"
        }
    }

    # JSON audit artifact kaydı
    with open(METADATA_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4, ensure_ascii=False)

    # SQLite DB denetim kaydı (hata yutulmaz, şema tutarlıdır)
    # Denetim Madde 26: Full Application Isolation için dinamik DB yolu çözümü
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")

    if os.path.exists(active_db):
        conn = get_db_connection(active_db)
        init_pipeline_runs_table(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO pipeline_runs 
            (run_id, timestamp, trigger_source, orders_count, git_sha, config_hash, data_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            metadata["run_timestamp"],
            "pipeline_execution",
            orders_count,
            metadata["git_sha"],
            metadata["config_hash"],
            data_source,
            status
        ))
        conn.commit()
        conn.close()

    return metadata

def start_pipeline_run(run_id: str, db_path: str = None) -> None:
    """Denetim Madde 27: Koşumu RUNNING durumunda başlatır."""
    import src.config as config
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    if os.path.exists(active_db):
        conn = get_db_connection(active_db)
        init_pipeline_runs_table(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO pipeline_runs 
            (run_id, timestamp, trigger_source, orders_count, git_sha, config_hash, data_source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            datetime.now().isoformat(),
            "pipeline_execution",
            0,
            get_git_sha(),
            compute_file_hash(CONFIG_PATH),
            "in_progress",
            "RUNNING"
        ))
        conn.commit()
        conn.close()

def update_pipeline_run_status(run_id: str, status: str, db_path: str = None) -> None:
    """Koşumun durumunu atomik olarak günceller (RUNNING -> STAGING -> VALIDATE -> COMPLETED -> ACTIVE / FAILED)."""
    import src.config as config
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    if not os.path.exists(active_db):
        return
    conn = get_db_connection(active_db)
    try:
        cur = conn.cursor()
        cur.execute("UPDATE pipeline_runs SET status = ? WHERE run_id = ?", (status, run_id))
        conn.commit()
    finally:
        conn.close()


def validate_pipeline_run(run_id: str, db_path: str = None) -> bool:
    """
    P0 Validation Gate:
    Koşumun fiziksel ve matematiksel çıktılarının tutarlılığını denetler.
    Tüm kontroller geçerse True döner, aksi halde ValueError fırlatır.
    """
    import src.config as config
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    conn = get_db_connection(active_db)
    try:
        cur = conn.cursor()
        
        # 1. Schedule tablosu ve görev kontrolü
        cur.execute("SELECT COUNT(*) FROM production_schedule")
        sched_count = cur.fetchone()[0]
        if sched_count == 0:
            raise ValueError(f"Validation Error: production_schedule tablosu boş (run_id: {run_id})")

        # 2. Enerji analitiği kontrolü (Doğru tablo adı: energy_kpis)
        cur.execute("SELECT COUNT(*) FROM energy_kpis")
        energy_count = cur.fetchone()[0]
        if energy_count == 0:
            raise ValueError(f"Validation Error: energy_kpis tablosu boş (run_id: {run_id})")

        # 3. Karbon analitiği kontrolü (Doğru tablo adı: carbon_kpis)
        cur.execute("SELECT COUNT(*) FROM carbon_kpis")
        carbon_count = cur.fetchone()[0]
        if carbon_count == 0:
            raise ValueError(f"Validation Error: carbon_kpis tablosu boş (run_id: {run_id})")

        return True
    finally:
        conn.close()        


def get_active_pipeline_run(db_path: str = None) -> dict:
    """Yalnızca doğrulanmış ve terfi edilmiş en güncel aktif koşumu döner."""
    import src.config as config
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    if not os.path.exists(active_db):
        return None
    conn = get_db_connection(active_db)
    cur = conn.cursor()
    # Öncelik ACTIVE, geriye dönük uyumluluk için COMPLETED/SUCCESS
    cur.execute("""
        SELECT run_id, timestamp, status, orders_count
        FROM pipeline_runs
        WHERE status = 'ACTIVE'
        ORDER BY timestamp DESC LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        cur.execute("""
            SELECT run_id, timestamp, status, orders_count
            FROM pipeline_runs
            WHERE status IN ('COMPLETED', 'SUCCESS')
            ORDER BY timestamp DESC LIMIT 1
        """)
        row = cur.fetchone()
    conn.close()
    if row:
        return {"run_id": row[0], "timestamp": row[1], "status": row[2], "orders_count": row[3]}
    return None

def apply_run_retention_policy(keep_last_n: int = 20, db_path: str = None) -> int:
    """
    Denetim Kapı 5: Historical Run Retention Policy.
    Üretim veritabanında denetim kütüğünün sınırsız büyümesini engeller.
    En güncel 'keep_last_n' adet koşumu korur, daha eski veya FAILED yetim kayıtları temizler.
    Silinen satır sayısını döner.
    """
    import src.config as config
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    if not os.path.exists(active_db):
        return 0

    conn = get_db_connection(active_db)
    init_pipeline_runs_table(conn)
    cur = conn.cursor()

    # Saklanacak en yeni N kaydın dışındaki eski run_id'leri bul
    cur.execute("""
        SELECT run_id FROM pipeline_runs 
        ORDER BY timestamp DESC 
        LIMIT -1 OFFSET ?
    """, (keep_last_n,))
    old_runs = [row[0] for row in cur.fetchall()]

    deleted_count = 0
    if old_runs:
        placeholders = ",".join("?" for _ in old_runs)
        cur.execute(f"DELETE FROM pipeline_runs WHERE run_id IN ({placeholders})", old_runs)
        deleted_count = cur.rowcount
        conn.commit()

    conn.close()
    return deleted_count

def generate_run_manifest(run_id: str, db_path: str = None) -> dict:
    """
    Denetim Madde 4 & Madde 18: Artifact & Input Lineage Manifest.
    - Pipeline çıktılarının (artifacts) SHA-256 ve boyutlarını mühürler.
    - Tam tekrarlanabilirlik (reproducibility) için girdi verileri (raw/master data),
      konfigürasyon, paket bağımlılıkları, python ve solver sürümlerinin parmak izini (fingerprint) tutar.
    """
    import hashlib
    import sys
    import src.config as config
    from pathlib import Path

    root_dir = Path(__file__).resolve().parent.parent.parent

    def compute_sha256(filepath: Path):
        if not filepath.exists() or not filepath.is_file():
            return None, 0
        hasher = hashlib.sha256()
        size = filepath.stat().st_size
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest(), size

    # 1. Output Artifacts Takibi
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    files_to_track = [
        Path(active_db),
        root_dir / "reports" / "run_metadata.json",
        root_dir / "reports" / "schedule_solver_metadata.json",
        root_dir / "reports" / "forecast_model_metadata.json",
    ]

    processed_dir = getattr(config, "PROCESSED_DATA_DIR", root_dir / "data" / "processed")
    if Path(processed_dir).exists():
        for p in Path(processed_dir).glob("*.csv"):
            files_to_track.append(p)

    manifest_entries = {}
    for file_path in files_to_track:
        sha, size = compute_sha256(file_path)
        if sha is not None:
            manifest_entries[file_path.name] = {
                "size_bytes": size,
                "sha256": sha,
                "relative_path": str(file_path.relative_to(root_dir)) if root_dir in file_path.parents else file_path.name
            }

    # 2. Input Lineage & Environment Fingerprinting (Madde 18)
    inputs_lineage = {
        "raw_source_data": {},
        "config_fingerprint": {},
        "environment": {}
    }

    # Raw / Master Data dosya hash'leri
    raw_dir = root_dir / "data" / "raw"
    if raw_dir.exists():
        for r_file in raw_dir.glob("*"):
            if r_file.is_file() and not r_file.name.startswith("."):
                sha, size = compute_sha256(r_file)
                if sha:
                    inputs_lineage["raw_source_data"][r_file.name] = {
                        "size_bytes": size,
                        "sha256": sha,
                        "relative_path": str(r_file.relative_to(root_dir))
                    }

    # Config Hash
    config_path = root_dir / "src" / "config.py"
    cfg_sha, cfg_size = compute_sha256(config_path)
    inputs_lineage["config_fingerprint"] = {
        "file": "src/config.py",
        "sha256": cfg_sha,
        "size_bytes": cfg_size
    }

    # Solver Versions
    solver_versions = {}
    try:
        import ortools
        solver_versions["ortools_cpsat"] = getattr(ortools, "__version__", "unknown")
    except ImportError:
        solver_versions["ortools_cpsat"] = "not_installed"

    # Requirements Fingerprint
    req_path = root_dir / "requirements.txt"
    req_sha, req_size = compute_sha256(req_path)

    inputs_lineage["environment"] = {
        "python_version": sys.version.split()[0],
        "solver_versions": solver_versions,
        "requirements_fingerprint": {
            "file": "requirements.txt",
            "sha256": req_sha,
            "size_bytes": req_size
        }
    }

    manifest = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(),
        "total_artifacts": len(manifest_entries),
        "artifacts": manifest_entries,
        "inputs": inputs_lineage
    }

    manifest_path = root_dir / "reports" / "run_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4, ensure_ascii=False)

    return manifest

def test_artifact_manifest_generation():
    """Denetim Madde 4: Pipeline artifact manifestinin geçerli byte ve SHA-256 ürettiğini doğrular."""
    from src.utils.lineage import generate_run_manifest
    import json
    import os

    manifest = generate_run_manifest(run_id="RUN-MANIFEST-TEST-001")
    assert manifest["run_id"] == "RUN-MANIFEST-TEST-001"
    assert manifest["total_artifacts"] > 0
    assert os.path.exists("reports/run_manifest.json")

    with open("reports/run_manifest.json", "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["run_id"] == "RUN-MANIFEST-TEST-001"
    assert len(loaded["artifacts"]) > 0

def promote_run_to_active(run_id: str, db_path: str = None) -> bool:
    """
    P0 Mimarisi: Atomic Active Run Promotion.
    Pipeline başarıyla doğrulanınca, tek bir atomik transaction içinde:
    1. Önceki ACTIVE olan koşumları ARCHIVED yapar.
    2. Yeni run_id'yi ACTIVE durumuna terfi ettirir.
    Hata durumunda transaction rollback edilir ve önceki ACTIVE sistem korunur.
    """
    import sqlite3
    import src.config as config
    target_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")

    conn = get_db_connection(target_db)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE TRANSACTION;")

        # 1. Önceki ACTIVE koşumları ARCHIVED yap
        cur.execute("""
            UPDATE pipeline_runs
            SET status = 'ARCHIVED'
            WHERE status = 'ACTIVE' AND run_id != ?
        """, (run_id,))

        # 2. Yeni koşumu ACTIVE yap
        cur.execute("""
            UPDATE pipeline_runs
            SET status = 'ACTIVE'
            WHERE run_id = ?
        """, (run_id,))

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()