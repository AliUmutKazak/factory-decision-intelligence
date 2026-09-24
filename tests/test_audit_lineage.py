import os
import json
import sqlite3
import pytest
import pandas as pd
from src.config import DB_PATH, BASE_DIR

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
    conn = sqlite3.connect(DB_PATH)
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
    
    last_status = df_runs.iloc[-1]["status"]
    assert last_status == "SUCCESS", f"Son pipeline çalıştırma durumu SUCCESS değil: {last_status}"

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

def test_run_metadata_report_consistency(db_connection):
    """reports/run_metadata.json dosyasının veritabanındaki son çalıştırma ile tutarlılığını test eder."""
    metadata_path = BASE_DIR / "reports" / "run_metadata.json"
    if metadata_path.exists():
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        assert "run_id" in metadata, "run_metadata.json dosyasında run_id eksik!"
        cursor = db_connection.cursor()
        cursor.execute("SELECT status, git_sha FROM pipeline_runs WHERE run_id = ?", (metadata["run_id"],))
        row = cursor.fetchone()
        assert row is not None, f"JSON'daki run_id veritabanında bulunamadı: {metadata['run_id']}"
        assert row[0] == metadata.get("status"), "DB status ile JSON status uyuşmuyor!"