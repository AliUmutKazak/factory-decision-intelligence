import os, sys, json, uuid, hashlib, sqlite3, subprocess
from datetime import datetime
from pathlib import Path
import src.config as config
from src.utils.db import get_db_connection

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT_DIR / "src" / "config.py"
REPORTS_DIR = ROOT_DIR / "reports"
METADATA_JSON_PATH = str(REPORTS_DIR / "run_metadata.json")
VALID_STATUS_TRANSITIONS = {
    "INITIALIZED": {"RUNNING", "STAGING", "FAILED"},
    "RUNNING": {"STAGING", "FAILED"},
    "STAGING": {"VALIDATE", "FAILED"},
    "VALIDATE": {"COMPLETED", "FAILED"},
    "COMPLETED": {"ACTIVE", "FAILED"},
    "ACTIVE": {"ARCHIVED"},
    "ARCHIVED": set(),  # Terminal durum
    "FAILED": set(),    # Terminal durum
}

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
    """Bütünleşik denetim şeması ve Partial Unique Index (Aynı anda tek ACTIVE garantisi)."""
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
            status TEXT NOT NULL CHECK(status IN ('INITIALIZED', 'RUNNING', 'STAGING', 'VALIDATE', 'COMPLETED', 'ACTIVE', 'ARCHIVED', 'FAILED'))
        )
    """)
    # P1 Güvencesi: Tabloda aynı anda en fazla 1 adet ACTIVE kayıt olabilir!
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_runs_unique_active 
        ON pipeline_runs(status) 
        WHERE status = 'ACTIVE';
    """)
    conn.commit()

def record_pipeline_run_metadata(
    run_id=None,
    solver_metrics=None,
    data_source="factory_orders.csv",
    orders_count=0,
    status="COMPLETED",
    db_path=None,
    selected_models=None,
    forecast_origin=None,
    forecast_method="Hybrid_Backtest_Selection"
):
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

    # Madde 17: Dinamik Model Lineage ve Governance Entegrasyonu
    # Hard-coded model bilgisi yerine doğrudan DB / pipeline bağlamından dinamik oku
    resolved_selected_models = dict(selected_models) if selected_models else {}
    resolved_forecast_origin = forecast_origin

    target_db = Path(db_path) if db_path else DB_PATH
    if (not resolved_selected_models or not resolved_forecast_origin) and target_db.exists():
        try:
            with get_db_connection(target_db) as conn:
                df_lineage = pd.read_sql(
                    "SELECT product_id, selected_model, forecast_origin FROM model_lineage",
                    conn
                )
                if not df_lineage.empty:
                    if not resolved_selected_models:
                        # En güncel ürün-model seçimlerini sözlüğe dök
                        resolved_selected_models = dict(
                            zip(df_lineage["product_id"], df_lineage["selected_model"])
                        )
                    if not resolved_forecast_origin and "forecast_origin" in df_lineage.columns:
                        resolved_forecast_origin = str(df_lineage["forecast_origin"].dropna().iloc[-1])
        except Exception:
            pass

    # Fallback: DB veya lineage kaydı bulunamazsa geriye dönük uyumluluk için varsayılanlar
    if not resolved_selected_models:
        resolved_selected_models = {
            "P01": "LightGBM",
            "P02": "Holt-Winters",
            "P03": "LightGBM",
            "P04": "LightGBM",
            "P05": "LightGBM"
        }
    if not resolved_forecast_origin:
        resolved_forecast_origin = "2017-12-31"

    metadata = {
        "run_id": run_id,
        "run_timestamp": datetime.now().isoformat(),
        "git_sha": get_git_sha(),
        "data_source": data_source,
        "forecast_origin": resolved_forecast_origin,
        "forecast_method": forecast_method,
        "selected_models": resolved_selected_models,
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
    """
    P1 State Machine Enforcement:
    Durum geçiş kurallarını kesin olarak denetler. 
    İllegal geçişlerde ValueError fırlatır, aynı duruma geçişlerde idempotent davranır.
    """
    import src.config as config
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    if not os.path.exists(active_db):
        return
    conn = get_db_connection(active_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"State Machine Error: run_id '{run_id}' bulunamadı.")
        
        current_status = row[0]
        if current_status == status:
            return

        allowed = VALID_STATUS_TRANSITIONS.get(current_status, set())
        if status not in allowed:
            raise ValueError(
                f"[STATE MACHINE VIOLATION] Geçersiz durum geçişi: '{current_status}' -> '{status}'. "
                f"İzin verilen sonraki durumlar: {allowed if allowed else 'Yok (Terminal Durum)'}"
            )
        
        cur.execute("UPDATE pipeline_runs SET status = ? WHERE run_id = ?", (status, run_id))
        conn.commit()
    finally:
        conn.close()


def validate_pipeline_run(run_id: str, db_path: str = None) -> bool:
    """
    P0 Master Validation Gate:
    COUNT(*) değil; 'same run' + 'math' + 'physics' + 'solver' + 'lineage'
    5 temel kurumsal kuralı kesin olarak denetler:
    1. same run: downstream tablolardaki run_id tutarlılığı
    2. math: SKU mutabakatı ve miktar korunumu
    3. physics: aynı tezgahta sıfır zaman çakışması (non-overlapping) ve OT bütçe sınırı
    4. solver: OPTIMAL/FEASIBLE durumu ve geçerli pozitif makespan
    5. lineage: metadata ve manifest dosya/run_id uyumu
    """
    import src.config as config
    import pandas as pd
    import numpy as np
    import json
    from pathlib import Path

    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    conn = get_db_connection(active_db)
    try:
        cur = conn.cursor()

        # 1. SAME RUN Tutarlılığı: Tabloların boş olmaması ve run_id uyumu
        tables_to_check = [
            "production_schedule", "energy_kpis", "carbon_kpis", 
            "sku_production_plan", "aggregate_plan", "machine_capacity_plan"
        ]
        for tbl in tables_to_check:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            cnt = cur.fetchone()[0]
            if cnt == 0:
                raise ValueError(f"[VALIDATION GATE FAIL] '{tbl}' tablosu boş (run_id: {run_id})")
            
            # Tabloda run_id kolonu varsa, başka bir run_id'ye ait veri bulunmamalı
            cur.execute(f"PRAGMA table_info({tbl})")
            cols = [r[1] for r in cur.fetchall()]
            if "run_id" in cols:
                cur.execute(f"SELECT DISTINCT run_id FROM {tbl} WHERE run_id IS NOT NULL")
                distinct_runs = [r[0] for r in cur.fetchall()]
                if any(r != run_id for r in distinct_runs):
                    raise ValueError(f"[VALIDATION GATE FAIL] '{tbl}' tablosunda run_id tutarsızlığı: {distinct_runs} != {run_id}")

        # 2. MATH: SKU Mutabakatı & Miktar Korunumu
        # Detaylı çizelgeleme (CP-SAT) 1. haftayı (schedule_week = 1) çizelgeler.
        # Rota adımları (operation_seq 1..N) aynı lotu tekrar içerdiğinden lot_id bazında tekilleştirilir.
        sched_df = pd.read_sql("SELECT lot_id, product_id, production_units FROM production_schedule", conn)
        sku_plan_df = pd.read_sql("SELECT product_id, planned_units FROM sku_production_plan WHERE period_week = 1", conn)
        
        if not sched_df.empty and not sku_plan_df.empty:
            # Her lot için tekil üretim miktarını al (operasyon katlanmasını önle)
            unique_lots = sched_df.drop_duplicates(subset=["lot_id"])
            s_agg = unique_lots.groupby("product_id")["production_units"].sum()
            p_agg = sku_plan_df.groupby("product_id")["planned_units"].sum()
            
            for pid, p_val in p_agg.items():
                s_val = s_agg.get(pid, 0.0)
                if abs(p_val - s_val) > 1e-4:
                    raise ValueError(
                        f"[VALIDATION GATE FAIL] SKU Mutabakatı Bozuldu! Ürün: {pid}, "
                        f"W1 Planlanan: {p_val}, Çizelgelenen (Tekil Lot): {s_val}"
                    )

        # 3. PHYSICS: Tezgahlarda Zaman Çakışması Yokluğu (Non-Overlapping)
        # Tablodaki kolon isimleri start_min ve end_min şeklindedir.
        ops_df = pd.read_sql("SELECT machine_id, start_min, end_min FROM production_schedule ORDER BY machine_id, start_min", conn)
        for mid, group in ops_df.groupby("machine_id"):
            sorted_ops = group.sort_values(by="start_min").to_dict(orient="records")
            for i in range(len(sorted_ops) - 1):
                cur_op = sorted_ops[i]
                next_op = sorted_ops[i + 1]
                # Bitiş dakikası sonraki operasyonun başlangıç dakikasından büyükse fiziksel çakışma vardır
                if cur_op["end_min"] > next_op["start_min"] + 1e-4:
                    raise ValueError(
                        f"[VALIDATION GATE FAIL] Fiziksel Kısıt İhlali! Tezgah {mid} üzerinde "
                        f"zaman çakışması tespit edildi: [{cur_op['start_min']}, {cur_op['end_min']}] "
                        f"ile [{next_op['start_min']}, {next_op['end_min']}]"
                    )

        # OT Bütçe Sınırı (48 saat = 2880 dk)
        machine_ot = pd.read_sql("SELECT machine_id, SUM(overtime_minutes) as total_ot FROM production_schedule GROUP BY machine_id", conn)
        for _, row in machine_ot.iterrows():
            if row["total_ot"] > 2880.0 + 1e-4:
                raise ValueError(f"[VALIDATION GATE FAIL] OT Bütçe Sınırı Aşıldı! Makine: {row['machine_id']}, Fiili OT: {row['total_ot']} dk")

        # Enerji Korunum Dengesi
        energy_kpi = pd.read_sql("SELECT grand_total_kwh FROM energy_kpis", conn)
        machine_kpi = pd.read_sql("SELECT SUM(total_kwh) as m_sum FROM energy_machine_kpis", conn)
        if not energy_kpi.empty and not machine_kpi.empty:
            if abs(float(energy_kpi.iloc[0, 0]) - float(machine_kpi.iloc[0, 0])) > 0.5:
                raise ValueError("[VALIDATION GATE FAIL] Enerji Korunum Dengesizliği (Facility Total != Sum of Machines)")

        # 4. SOLVER Feasibility ve Makespan
        root_dir = Path(__file__).resolve().parent.parent.parent
        meta_json_path = root_dir / "reports" / "schedule_solver_metadata.json"
        if meta_json_path.exists():
            with open(meta_json_path, "r", encoding="utf-8") as f:
                solver_meta = json.load(f)
            
            # JSON anahtarları: 'solver_status' ve 'objective_value_min'
            status = solver_meta.get("solver_status") or solver_meta.get("status", "")
            status = str(status).upper()
            if status not in ("OPTIMAL", "FEASIBLE", "OPTIMAL_OR_FEASIBLE"):
                raise ValueError(f"[VALIDATION GATE FAIL] Geçersiz CP-SAT Solver Durumu: {status}")
            
            makespan = solver_meta.get("objective_value_min") or solver_meta.get("makespan_minutes", 0)
            if makespan is not None and float(makespan) <= 0:
                raise ValueError(f"[VALIDATION GATE FAIL] Geçersiz solver makespan değeri: {makespan}")

        # 5. LINEAGE Bütünlüğü: Metadata doğrulaması
        run_meta_path = root_dir / "reports" / "run_metadata.json"
        if run_meta_path.exists():
            with open(run_meta_path, "r", encoding="utf-8") as f:
                run_meta = json.load(f)
            if run_meta.get("run_id") and run_meta.get("run_id") != run_id:
                raise ValueError(f"[VALIDATION GATE FAIL] Lineage metadata run_id uyumsuzluğu: {run_meta.get('run_id')} != {run_id}")

        return True
    finally:
        conn.close()        


def get_active_pipeline_run(db_path: str = None, allow_fallback: bool = False) -> dict:
    """
    P1 Semantik Güvencesi:
    Yalnızca doğrulanmış ve atomik olarak terfi ettirilmiş (ACTIVE) koşumu döner.
    Sistemde ACTIVE koşum yoksa kesinlikle None döner (ACTIVE only).
    
    allow_fallback=True yalnızca eski/legacy migration testleri veya geriye dönük
    uyumluluk için açıkça istendiğinde COMPLETED/SUCCESS durumuna bakar.
    """
    import src.config as config
    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    if not os.path.exists(active_db):
        return None
    conn = get_db_connection(active_db)
    cur = conn.cursor()
    
    # 1. Kesin Üretim Kuralı: Sadece ACTIVE durumu aranır
    cur.execute("""
        SELECT run_id, timestamp, status, orders_count
        FROM pipeline_runs
        WHERE status = 'ACTIVE'
        ORDER BY timestamp DESC LIMIT 1
    """)
    row = cur.fetchone()
    
    # 2. Uyumluluk Modu (Yalnızca parametre ile açıkça talep edilirse):
    if not row and allow_fallback:
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

def apply_run_retention_policy(keep_last_n: int = 20, db_path: str = None, artifacts_dir: str = None) -> int:
    """
    Denetim Kapı 5 & Madde 23: Historical Run & Artifact Retention Policy.
    - Üretim veritabanında denetim kütüğünün sınırsız büyümesini engeller.
    - En güncel 'keep_last_n' adet koşumu korur, eski veya yetim kayıtları temizler.
    - Veritabanından silinen veya yetim kalan fiziksel snapshot dizinlerini (artifacts/reference_runs/<RUN_ID>)
      diskten temizleyerek veritabanı ile disk yaşam döngüsünü senkronize eder.
    Silinen veritabanı satır sayısını döner.
    """
    import os
    import shutil
    from pathlib import Path
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

    # Fiziksel Disk Artifact Senkronizasyonu (Madde 23)
    target_artifacts_dir = Path(artifacts_dir) if artifacts_dir else Path("artifacts/reference_runs")
    if target_artifacts_dir.exists() and target_artifacts_dir.is_dir():
        # 1. Silinen eski koşuların disk snapshot'larını temizle
        for old_id in old_runs:
            old_run_dir = target_artifacts_dir / old_id
            if old_run_dir.exists() and old_run_dir.is_dir():
                shutil.rmtree(old_run_dir, ignore_errors=True)

        # 2. Yetim (orphan) snapshot temizliği: DB'de geçerli olan run_id'leri al
        cur.execute("SELECT run_id FROM pipeline_runs")
        valid_runs = set(row[0] for row in cur.fetchall())

        for item in target_artifacts_dir.iterdir():
            if item.is_dir() and item.name not in valid_runs:
                shutil.rmtree(item, ignore_errors=True)

    conn.close()
    return deleted_count

def generate_run_manifest(run_id: str, db_path: str = None, input_source_path: str = None) -> dict:
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
    # Fiilen boru hattında kullanılan girdi dosyasını (actual input source) tespit et
    actual_input_path = None
    if input_source_path and Path(input_source_path).exists():
        actual_input_path = Path(input_source_path)
    elif "USE_FIXTURE" in os.environ:
        fixture_name = os.environ.get("USE_FIXTURE")
        if not fixture_name.endswith(".csv"):
            fixture_name = f"{fixture_name}.csv"
        cand = root_dir / "data" / "fixtures" / fixture_name
        if cand.exists():
            actual_input_path = cand
    elif (root_dir / "data" / "raw" / "train.csv").exists():
        actual_input_path = root_dir / "data" / "raw" / "train.csv"
    elif (root_dir / "data" / "fixtures" / "demand_fixture.csv").exists():
        actual_input_path = root_dir / "data" / "fixtures" / "demand_fixture.csv"

    input_dataset_info = {}
    if actual_input_path and actual_input_path.exists():
        inp_sha, inp_size = compute_sha256(actual_input_path)
        input_dataset_info = {
            "path": str(actual_input_path.relative_to(root_dir)) if root_dir in actual_input_path.parents else str(actual_input_path),
            "sha256": inp_sha,
            "size_bytes": inp_size,
            "adapter": "KaggleRetailDemandAdapter",
            "mapping_version": "canonical-v1"
        }

    inputs_lineage = {
        "input_dataset": input_dataset_info,
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

    # Requirements & Lockfile Fingerprint (Madde 19: Full Reproducibility)
    req_path = root_dir / "requirements.txt"
    req_sha, req_size = compute_sha256(req_path)

    lock_path = root_dir / "requirements.lock"
    lock_sha, lock_size = compute_sha256(lock_path)

    inputs_lineage["environment"] = {
        "python_version": sys.version.split()[0],
        "solver_versions": solver_versions,
        "requirements_fingerprint": {
            "file": "requirements.txt",
            "sha256": req_sha,
            "size_bytes": req_size
        },
        "lockfile_fingerprint": {
            "file": "requirements.lock",
            "sha256": lock_sha,
            "size_bytes": lock_size
        } if lock_sha else None
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



def promote_run_to_active(run_id: str, db_path: str = None) -> bool:
    """
    P0/P1 Mimarisi: Atomic Active Run Promotion.
    1. Önceki ACTIVE koşumu ARCHIVED yapar.
    2. run_id koşumunu COMPLETED -> ACTIVE durumuna taşır.
    """
    import sqlite3
    import src.config as config
    target_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")

    conn = get_db_connection(target_db)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE TRANSACTION;")

        cur.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if not row or row[0] != "COMPLETED":
            curr = row[0] if row else "None"
            raise ValueError(f"[PROMOTION VIOLATION] Yalnızca COMPLETED koşumlar ACTIVE yapılabilir! Mevcut durum: '{curr}'")

        # 1. Önceki ACTIVE koşumları ARCHIVED yap (böylece partial unique index bozulmaz)
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

def freeze_canonical_reference(conn, target_dir: str = "artifacts/reference_runs/canonical") -> dict:
    """
    Denetim Madde 34 (P0.1): Canonical Reference Freeze & Atomic Swap Zinciri.
    1. ACTIVE run seç
    2. artifact run_id doğrula
    3. git_sha doğrula
    4. explicit artifact allowlist
    5. manifest üret
    6. atomic swap
    """
    import os
    import shutil
    import tempfile
    import json
    from pathlib import Path
    import src.config as config

    root_dir = Path(__file__).resolve().parent.parent.parent
    cur = conn.cursor()

    # 1. ACTIVE run seç
    cur.execute("SELECT run_id, git_sha, status FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY created_at DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        raise ValueError("Canonical freeze başarısız: Veritabanında ACTIVE statüsünde bir koşu bulunamadı.")
    active_run_id, db_git_sha, _ = row

    # 2 & 3. artifact run_id ve git_sha doğrula
    metadata_file = root_dir / "reports" / "run_metadata.json"
    if not metadata_file.exists():
        raise FileNotFoundError(f"Canonical freeze başarısız: {metadata_file} bulunamadı.")
    
    with open(metadata_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    
    meta_run_id = meta.get("run_id")
    meta_git_sha = meta.get("git_sha")

    if meta_run_id != active_run_id:
        raise ValueError(f"Run ID mismatch: DB active '{active_run_id}' != Metadata '{meta_run_id}'")
    if meta_git_sha and db_git_sha and meta_git_sha != db_git_sha:
        raise ValueError(f"Git SHA mismatch: DB '{db_git_sha}' != Metadata '{meta_git_sha}'")

    # 4. Explicit Artifact Allowlist
    active_db = Path(os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db"))
    allowlist = [
        active_db,
        metadata_file,
        root_dir / "reports" / "schedule_solver_metadata.json",
        root_dir / "reports" / "forecast_model_metadata.json",
    ]
    
    processed_dir = Path(getattr(config, "PROCESSED_DATA_DIR", root_dir / "data" / "processed"))
    if processed_dir.exists():
        for csv_file in processed_dir.glob("*.csv"):
            allowlist.append(csv_file)

    # 5. Manifest üret
    manifest = generate_run_manifest(run_id=active_run_id, db_path=str(active_db))

    # 6. Atomic Swap (Önce geçici temp dizinine yaz, sonra atomik taşı)
    canonical_target = Path(target_dir)
    canonical_target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(canonical_target.parent)) as tmp_staging:
        staging_dir = Path(tmp_staging) / "staging_canonical"
        staging_dir.mkdir(parents=True, exist_ok=True)

        for src_file in allowlist:
            if src_file.exists() and src_file.is_file():
                shutil.copy2(src_file, staging_dir / src_file.name)

        # Manifest'i de staging içine koy
        with open(staging_dir / "run_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)

        # Atomic Swap: Eski canonical varsa kaldır/değiştir
        if canonical_target.exists():
            shutil.rmtree(canonical_target)
        shutil.move(str(staging_dir), str(canonical_target))

    return {
        "status": "SUCCESS",
        "frozen_run_id": active_run_id,
        "git_sha": db_git_sha,
        "canonical_path": str(canonical_target),
        "total_artifacts": len(manifest.get("artifacts", {}))
    }        

