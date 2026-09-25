import os
import json
import sqlite3
import pytest
import pandas as pd
from src.config import DB_PATH, BASE_DIR
from src.utils.db import get_db_connection

DOWNSTREAM_TABLES = [
    "pipeline_runs",
    "forecast_demand",
    "forecast_model_lineage",
    "aggregate_plan",
    "sku_production_plan",
    "machine_capacity_plan",
    "mrp_plan",
    "production_schedule",
    "schedule_solver_metadata",
    "energy_kpis",
    "energy_profile_15min",
    "energy_machine_kpis",
    "carbon_kpis",
    "carbon_machine_kpis",
    "carbon_price_scenarios",
]

@pytest.fixture(scope="module")
def db_connection():
    """SQLite veritabanı bağlantı fixture'ı."""
    assert os.path.exists(DB_PATH), f"Veritabanı bulunamadı: {DB_PATH}"
    conn = get_db_connection(DB_PATH)
    yield conn
    conn.close()

def test_pipeline_runs_table_exists_and_populated(db_connection):
    """pipeline_runs tablosunun varlığını ve en az bir geçerli run içerdiğini denetler."""
    cursor = db_connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pipeline_runs'")
    assert cursor.fetchone() is not None, "pipeline_runs tablosu mevcut değil!"

    df_runs = pd.read_sql("SELECT * FROM pipeline_runs", db_connection)
    assert not df_runs.empty, "pipeline_runs tablosu boş!"
    assert "run_id" in df_runs.columns, "pipeline_runs tablosunda run_id kolonu eksik!"
    assert "status" in df_runs.columns, "pipeline_runs tablosunda status kolonu eksik!"

    # Simülasyon kalıntılarını hariç tutarak son resmi koşumu doğrula
    valid_runs = df_runs[~df_runs["run_id"].str.startswith("RUN-FAIL-SIM")]
    assert not valid_runs.empty, "Geçerli bir pipeline run kaydı bulunamadı!"
    last_status = valid_runs.iloc[-1]["status"]
    assert last_status in ("SUCCESS", "COMPLETED"), f"Son pipeline çalıştırma durumu geçerli değil: {last_status}"

def test_downstream_tables_have_run_id(db_connection):
    """Tüm downstream tablolarında run_id sütununun var olduğunu doğrular."""
    cursor = db_connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    existing_tables = [row[0] for row in cursor.fetchall()]

    for table in DOWNSTREAM_TABLES:
        assert table in existing_tables, f"Beklenen tablo veritabanında yok: {table}"
        columns = [col[1] for col in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
        assert "run_id" in columns, f"Tabloda 'run_id' sütunu bulunamadı: {table}"

def test_downstream_tables_have_no_null_run_ids(db_connection):
    """Hiçbir downstream tabloda NULL run_id kaydı bulunmadığını denetler."""
    cursor = db_connection.cursor()
    for table in DOWNSTREAM_TABLES:
        cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id IS NULL OR run_id = ''")
        null_count = cursor.fetchone()[0]
        assert null_count == 0, f"Tabloda {null_count} adet NULL veya boş run_id tespit edildi: {table}"

def test_downstream_run_id_matches_pipeline_runs(db_connection):
    """Downstream tablolardaki run_id değerlerinin pipeline_runs tablosunda kayıtlı olduğunu doğrular."""
    valid_runs = set(pd.read_sql("SELECT run_id FROM pipeline_runs", db_connection)["run_id"])
    cursor = db_connection.cursor()

    for table in DOWNSTREAM_TABLES:
        distinct_runs = [row[0] for row in cursor.execute(f"SELECT DISTINCT run_id FROM {table}").fetchall()]
        for run_id in distinct_runs:
            assert run_id in valid_runs, (
                f"Tablodaki run_id ({run_id}) pipeline_runs tablosunda bulunamadı (Orphan Record): {table}"
            )

def test_runtime_run_metadata_consistency(db_connection):
    """
    Runtime Validation:
    Canlı pipeline çıktısı olan reports/run_metadata.json dosyasının
    mevcut runtime DB (data/factory.db) ile tutarlılığını doğrular.
    """
    metadata_path = BASE_DIR / "reports" / "run_metadata.json"
    cursor = db_connection.cursor()

    # 1. Runtime DB'deki son resmi/aktif koşumu al
    cursor.execute(
        "SELECT run_id, status FROM pipeline_runs "
        "WHERE run_id NOT LIKE 'RUN-TEST-%' AND run_id NOT LIKE 'RUN-FAIL-%' "
        "ORDER BY timestamp DESC LIMIT 1"
    )
    latest_db_run = cursor.fetchone()
    assert latest_db_run is not None, "Runtime DB'de geçerli bir pipeline_run kaydı bulunamadı!"
    assert latest_db_run[1] in ("SUCCESS", "COMPLETED"), f"Runtime DB status geçerli değil: {latest_db_run[1]}"

    # 2. Metadata JSON varsa doğrula
    if metadata_path.exists():
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        assert "run_id" in metadata, "run_metadata.json dosyasında run_id eksik!"
        json_run_id = metadata["run_id"]

        # Eğer dosya sentetik değilse DB ile birebir eşleşmeli
        if not json_run_id.startswith(("RUN-TEST-", "RUN-FAIL-")):
            cursor.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (json_run_id,))
            row = cursor.fetchone()
            assert row is not None, f"Runtime DB'de JSON'daki run_id bulunamadı: {json_run_id}"
            assert row[0] in ("SUCCESS", "COMPLETED"), f"Runtime DB status geçerli değil: {row[0]}"


def test_frozen_reference_metadata_consistency():
    """
    Reference Validation:
    artifacts/reference/run_metadata.json dosyasının, dondurulmuş
    referans veritabanı (artifacts/reference/factory.db) ile kapalı devre tutarlılığını doğrular.
    """
    ref_dir = BASE_DIR / "artifacts" / "reference"
    ref_metadata_path = ref_dir / "run_metadata.json"
    ref_db_path = ref_dir / "factory.db"

    if not ref_metadata_path.exists() or not ref_db_path.exists():
        pytest.skip("Frozen reference snapshot mevcut değil, test atlanıyor.")

    with open(ref_metadata_path, "r", encoding="utf-8") as f:
        ref_metadata = json.load(f)

    assert "run_id" in ref_metadata, "Reference run_metadata.json dosyasında run_id eksik!"

    with get_db_connection(ref_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, git_sha FROM pipeline_runs WHERE run_id = ?", (ref_metadata["run_id"],))
        row = cursor.fetchone()

    assert row is not None, f"Frozen reference DB'de referans run_id bulunamadı: {ref_metadata.get('run_id')}"
    assert row[0] in ("SUCCESS", "COMPLETED"), f"Frozen reference DB status geçerli değil: {row[0]}"

def test_historical_run_retention_policy(tmp_path):
    """Denetim Kapı 5: En güncel N koşumun korunduğunu ve eski koşumların temizlendiğini doğrular."""
    from src.utils.lineage import apply_run_retention_policy, init_pipeline_runs_table
    import sqlite3
    from datetime import datetime, timedelta

    temp_db = str(tmp_path / "test_retention.db")
    conn = get_db_connection(temp_db)
    init_pipeline_runs_table(conn)
    cur = conn.cursor()

    # 10 adet yapay koşum ekle (kronolojik)
    base_time = datetime(2026, 1, 1, 10, 0, 0)
    for i in range(10):
        t = (base_time + timedelta(hours=i)).isoformat()
        cur.execute("""
            INSERT INTO pipeline_runs (run_id, timestamp, trigger_source, orders_count, git_sha, config_hash, data_source, status)
            VALUES (?, ?, 'test', 100, 'sha', 'hash', 'test.csv', 'COMPLETED')
        """, (f"RUN-{i:03d}", t))
    conn.commit()
    conn.close()

    # Son 3 koşumu koru, 7 tanesini temizle
    deleted = apply_run_retention_policy(keep_last_n=3, db_path=temp_db)
    assert deleted == 7, f"7 eski koşum silinmeliydi, silinen: {deleted}"

    conn = get_db_connection(temp_db)
    cur = conn.cursor()
    cur.execute("SELECT run_id FROM pipeline_runs ORDER BY timestamp ASC")
    remaining = [row[0] for row in cur.fetchall()]
    conn.close()

    # En son eklenen 3 koşum kalmış olmalı (RUN-007, RUN-008, RUN-009)
    assert remaining == ["RUN-007", "RUN-008", "RUN-009"]

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

def test_p0_active_run_isolation_on_failure(tmp_path):
    """
    P0 Denetim Kanıtı:
    Yeni bir run çalışırken CP-SAT veya ara aşamada patlarsa,
    önceki başarılı koşumun downstream tabloları ve active_run_id'si korunur.
    Split-Brain durumu oluşamaz.
    """
    import sqlite3
    import uuid
    from src.utils.lineage import get_active_pipeline_run
    from src.config import DB_PATH

    active_before = get_active_pipeline_run(DB_PATH)
    assert active_before is not None, "Başlangıçta aktif bir koşum olmalı!"

    sim_run_id = f"RUN-FAIL-SIM-{uuid.uuid4().hex[:6]}"
    conn = get_db_connection(DB_PATH)
    try:
        # Simülasyon: Başarısız bir run kaydı açılıyor
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, timestamp, status) VALUES (?, datetime('now'), ?)",
            (sim_run_id, "FAILED")
        )
        conn.commit()

        # Active run sorgulandığında FAILED olan değil, önceki başarılı olan dönmeli
        active_after = get_active_pipeline_run(DB_PATH)
        assert active_after == active_before, f"Başarısız koşum aktif koşumu bozdu! Beklenen: {active_before}, Gelen: {active_after}"
    finally:
        # Test izolasyonu: Veritabanını kirletmemek için simülasyon kaydını temizle
        conn.execute("DELETE FROM pipeline_runs WHERE run_id = ?", (sim_run_id,))
        conn.commit()
        conn.close()    