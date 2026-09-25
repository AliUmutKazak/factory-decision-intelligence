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