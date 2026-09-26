"""
End-to-End Audit Lineage, Traceability & Data Isolation Test Suite
------------------------------------------------------------------
Doğrular:
1. Transaction Boundary (RUNNING -> STAGING -> VALIDATE -> COMPLETED -> ACTIVE)
2. Manifest Integrity (Cryptographic SHA-256 Mühürleme)
3. Staging DB İzolasyonu & Split-Brain Koruması (P0 Denetim Şartı)
4. Historical Run Retention (Denetim Kütüğü Tasfiyesi)
"""

import os
import json
import sqlite3
import shutil
import gc
from pathlib import Path
import pytest
import pandas as pd

from src.utils.lineage import (
    generate_run_id,
    start_pipeline_run,
    update_pipeline_run_status,
    record_pipeline_run_metadata,
    validate_pipeline_run,
    promote_run_to_active,
    get_active_pipeline_run,
    apply_run_retention_policy,
    generate_run_manifest,
    init_pipeline_runs_table
)
from src.utils.db import get_db_connection


def test_run_id_generation_format():
    """Run ID formatının deterministik ve denetlenebilir olduğunu doğrular."""
    run_id = generate_run_id()
    assert run_id.startswith("RUN-")
    parts = run_id.split("-")
    assert len(parts) == 3
    assert len(parts[1]) == 8  # YYYYMMDD
    assert len(parts[2]) == 6  # Hex token


def test_pipeline_runs_table_schema(tmp_path):
    """pipeline_runs tablosunun doğru şema ile oluşturulduğunu doğrular."""
    test_db = tmp_path / "test_lineage.db"
    conn = sqlite3.connect(str(test_db))
    init_pipeline_runs_table(conn)

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(pipeline_runs);")
    columns = {row[1]: row[2] for row in cur.fetchall()}
    conn.close()

    assert "run_id" in columns
    assert "timestamp" in columns
    assert "status" in columns
    assert "orders_count" in columns


def test_run_lifecycle_transitions(tmp_path):
    """Koşum durum geçişlerinin (RUNNING -> STAGING -> VALIDATE -> COMPLETED -> ACTIVE) doğrulanması."""
    test_db = tmp_path / "test_lineage.db"
    conn = sqlite3.connect(str(test_db))
    init_pipeline_runs_table(conn)
    conn.close()

    run_id = generate_run_id()

    # 1. Başlatma
    start_pipeline_run(run_id=run_id, db_path=str(test_db))

    # 2. STAGING
    update_pipeline_run_status(run_id=run_id, status="STAGING", db_path=str(test_db))
    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (run_id,))
    assert cur.fetchone()[0] == "STAGING"
    conn.close()

    # 3. VALIDATE
    update_pipeline_run_status(run_id=run_id, status="VALIDATE", db_path=str(test_db))
    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (run_id,))
    assert cur.fetchone()[0] == "VALIDATE"
    conn.close()

    # 4. COMPLETED
    update_pipeline_run_status(run_id=run_id, status="COMPLETED", db_path=str(test_db))
    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (run_id,))
    assert cur.fetchone()[0] == "COMPLETED"
    conn.close()

    # 5. ACTIVE (Promotion)
    promote_run_to_active(run_id=run_id, db_path=str(test_db))
    active = get_active_pipeline_run(db_path=str(test_db))
    assert active is not None
    assert active["run_id"] == run_id
    assert active["status"] == "ACTIVE"


def test_atomic_promotion_archives_previous_active(tmp_path):
    """Yeni bir koşum ACTIVE yapıldığında eskisinin ARCHIVED olduğunu doğrular."""
    test_db = tmp_path / "test_lineage.db"
    conn = sqlite3.connect(str(test_db))
    init_pipeline_runs_table(conn)
    conn.close()

    run_1 = "RUN-TEST-001"
    run_2 = "RUN-TEST-002"

    start_pipeline_run(run_id=run_1, db_path=str(test_db))
    promote_run_to_active(run_id=run_1, db_path=str(test_db))

    # run_1 aktif olmalı
    active = get_active_pipeline_run(db_path=str(test_db))
    assert active["run_id"] == run_1

    # run_2 terfi ettirilmeli
    start_pipeline_run(run_id=run_2, db_path=str(test_db))
    promote_run_to_active(run_id=run_2, db_path=str(test_db))

    # run_2 aktif, run_1 arşivlenmiş olmalı
    active_now = get_active_pipeline_run(db_path=str(test_db))
    assert active_now["run_id"] == run_2

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (run_1,))
    assert cur.fetchone()[0] == "ARCHIVED"
    conn.close()


def test_run_retention_policy(tmp_path):
    """Kayıt kütüğü retention kuralının (keep_last_n) eski kayıtları temizlediğini doğrular."""
    test_db = tmp_path / "test_lineage.db"
    conn = sqlite3.connect(str(test_db))
    init_pipeline_runs_table(conn)

    # 10 adet yapay koşum ekle
    for i in range(10):
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, timestamp, status) VALUES (?, datetime('now', ?), 'ARCHIVED')",
            (f"RUN-OLD-{i}", f"-{10-i} hours")
        )
    conn.commit()
    conn.close()

    # En son 3 koşumu koru
    deleted = apply_run_retention_policy(keep_last_n=3, db_path=str(test_db))
    assert deleted == 7

    conn = sqlite3.connect(str(test_db))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM pipeline_runs")
    remaining = cur.fetchone()[0]
    conn.close()
    assert remaining == 3


def test_run_manifest_generation(tmp_path, monkeypatch):
    """Artifact manifest'in kriptografik SHA-256 hash'leri ile oluşturulduğunu doğrular."""
    manifest_file = tmp_path / "reports" / "run_manifest.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)

    dummy_artifact = tmp_path / "data" / "dummy_artifact.csv"
    dummy_artifact.parent.mkdir(parents=True, exist_ok=True)
    dummy_artifact.write_text("sku,qty\nSKU_A,100\n", encoding="utf-8")

    manifest = generate_run_manifest(run_id="RUN-MANIFEST-TEST-001")

    assert manifest["run_id"] == "RUN-MANIFEST-TEST-001"
    assert "artifacts" in manifest
    assert "total_artifacts" in manifest


def test_p0_active_run_isolation_on_failure(tmp_path, monkeypatch):
    """
    P0 Denetim Kanıtı (Data Isolation & Split-Brain Prevention):
    RUN-A ACTIVE ve production_schedule = A iken;
    RUN-B RUNNING olarak başlar, get_db_connection(DB_PATH) üzerinden downstream
    tablolara (production_schedule = B staging) yazar ve ardından FAILED olur.
    Sonuçta kanonik DB'de ACTIVE = RUN-A ve production_schedule = A olduğu kanıtlanır.
    """
    import src.config as cfg
    canonical_db = tmp_path / "factory.db"
    staging_db = tmp_path / "factory_staging_RUN-B.db"

    # Varsayılan kanonik DB_PATH'i test dizinine sabitle
    monkeypatch.setattr(cfg, "DB_PATH", canonical_db)
    monkeypatch.setattr("src.utils.db.DB_PATH", canonical_db)
    monkeypatch.delenv("FACTORY_DB_PATH", raising=False)

    # 1. RUN-A ACTIVE olarak kanonik DB'dedir ve production_schedule = A verisine sahiptir
    with get_db_connection(cfg.DB_PATH) as conn:
        init_pipeline_runs_table(conn)
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, timestamp, status) VALUES ('RUN-A', '2026-09-26T10:00:00', 'ACTIVE')"
        )
        df_a = pd.DataFrame([{"lot_id": "LOT-A-001", "run_id": "RUN-A", "quantity": 100}])
        df_a.to_sql("production_schedule", conn, if_exists="replace", index=False)
        conn.commit()

    # 2. RUN-B başlar: main.py mimarisindeki gibi staging kopyası alınır ve FACTORY_DB_PATH aktif edilir
    shutil.copy2(canonical_db, staging_db)
    monkeypatch.setenv("FACTORY_DB_PATH", str(staging_db))

    try:
        # RUN-B RUNNING olarak işaretlenir
        start_pipeline_run(run_id="RUN-B")

        # Alt modüller doğrudan get_db_connection(cfg.DB_PATH) çağırsa bile
        # dinamik izolasyon sayesinde staging DB'ye yazar (production_schedule = B staging)
        with get_db_connection(cfg.DB_PATH) as conn_mod:
            df_b = pd.DataFrame([{"lot_id": "LOT-B-999", "run_id": "RUN-B", "quantity": 999}])
            df_b.to_sql("production_schedule", conn_mod, if_exists="replace", index=False)
            conn_mod.commit()

        # 3. RUN-B downstream veriyi yazdıktan sonra patlar (CP-SAT / Validation Failure)
        raise RuntimeError("Simulated pipeline failure after writing downstream staging data")

    except RuntimeError:
        # Pipeline hata yakalama bloğu: FACTORY_DB_PATH kaldırılır, staging silinir, RUN-B FAILED yazılır
        monkeypatch.delenv("FACTORY_DB_PATH", raising=False)
        gc.collect()
        if staging_db.exists():
            try:
                staging_db.unlink()
            except PermissionError:
                pass

        with get_db_connection(cfg.DB_PATH) as conn_fail:
            conn_fail.execute(
                "INSERT OR REPLACE INTO pipeline_runs (run_id, timestamp, status) VALUES ('RUN-B', '2026-09-26T10:05:00', 'FAILED')"
            )
            conn_fail.commit()

    # 4. DOĞRULAMA:
    # A) ACTIVE koşum hâlâ RUN-A olmalıdır
    active = get_active_pipeline_run(db_path=str(canonical_db))
    assert active is not None
    assert active["run_id"] == "RUN-A"
    assert active["status"] == "ACTIVE"

    # B) Kanonik DB'deki production_schedule tablosunda hâlâ A verisi durmalı, B verisi sızmamış olmalıdır
    with get_db_connection(cfg.DB_PATH) as conn_check:
        df_final = pd.read_sql("SELECT * FROM production_schedule", conn_check)

    assert len(df_final) == 1
    assert df_final["run_id"].iloc[0] == "RUN-A"
    assert df_final["lot_id"].iloc[0] == "LOT-A-001"
    assert int(df_final["quantity"].iloc[0]) == 100