import os
import sys
import sqlite3
from pathlib import Path
import pandas as pd
import pytest

# Proje kök dizinini sys.path'e en başa ekle (Her ortamda sorunsuz import için)
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.utils.db import get_db_connection

from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    WEEKLY_HOURS_PER_MACHINE,
    LABOR_COST_OVERTIME_HR,
)

@pytest.fixture(scope="module")
def db_conn():
    assert DB_PATH.exists(), f"Veritabanı bulunamadı: {DB_PATH}"
    conn = get_db_connection(DB_PATH)
    yield conn
    conn.close()

def test_sqlite_tables_exist(db_conn):
    """Tüm kritik analitik tablolarının veritabanında mevcut ve dolu olduğunu doğrular."""
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    expected_tables = [
        "orders",
        "products",
        "machines",
        "routing",
        "changeover_matrix",
        "bom",
        "materials",
        "aggregate_plan",
        "sku_production_plan",
        "machine_capacity_plan",
        "mrp_plan",
        "production_schedule",
        "energy_kpis",
        "energy_profile_15min",
        "carbon_kpis",
    ]
    for tbl in expected_tables:
        assert tbl in tables, f"Tablo eksik: {tbl}"
        df = pd.read_sql(f"SELECT COUNT(*) as count FROM {tbl}", db_conn)
        assert df["count"].iloc[0] > 0, f"Tablo boş: {tbl}"

def test_mathematical_reconciliation_family_sku_schedule(db_conn):
    """
    Kritik OR Mutabakatı:
    Family Batches -> SKU Planned Units -> Scheduled Units arasında
    Largest Remainder yöntemiyle sıfır kayıp / tam korunum sağlandığını test eder.
    """
    sku_df = pd.read_sql("SELECT * FROM sku_production_plan WHERE period_week = 1", db_conn)
    sched_df = pd.read_sql("SELECT * FROM production_schedule WHERE operation_seq = 1", db_conn)
    
    total_sku_units = sku_df["planned_units"].sum()
    # Gerçek üretilen parça adedi 'production_units' kolonundadır
    total_sched_units = sched_df["production_units"].sum() if "production_units" in sched_df.columns else sched_df["lot_qty"].sum()

    assert total_sku_units == total_sched_units, (
        f"Matematiksel Adet Uyuşmazlığı: SKU Plan ({total_sku_units}) != Schedule ({total_sched_units})"
    )

def test_energy_physical_consistency(db_conn):
    """Fiziksel Enerji Kuralı: Peak Güç (kW) >= Ortalama Güç (kW) olmalıdır."""
    kpi_df = pd.read_sql("SELECT * FROM energy_kpis", db_conn)
    assert not kpi_df.empty, "energy_kpis tablosu boş!"
    
    avg_kw = kpi_df["avg_load_kw"].iloc[0]
    peak_kw = kpi_df["peak_load_kw"].iloc[0]
    
    assert peak_kw >= avg_kw, f"Fiziksel Kural İhlali: Peak ({peak_kw} kW) < Avg ({avg_kw} kW)"

def test_machine_no_overlap(db_conn):
    """Aynı makinede iki operasyonun zaman diliminin çakışmadığını doğrular."""
    sched_df = pd.read_sql("SELECT * FROM production_schedule", db_conn)
    
    for m, group in sched_df.groupby("machine_id"):
        sorted_ops = group.sort_values("start_min").to_dict("records")
        for i in range(len(sorted_ops) - 1):
            curr_end = sorted_ops[i]["end_min"]
            next_start = sorted_ops[i + 1]["start_min"]
            assert next_start >= curr_end, (
                f"Makine Çakışması ({m}): {sorted_ops[i]['batch_id']} bitiş {curr_end}, "
                f"{sorted_ops[i+1]['batch_id']} başlangıç {next_start}"
            )

def test_carbon_accounting_balance(db_conn):
    """Scope 1 + Scope 2 = Total GHG emisyon dengesini kontrol eder."""
    carbon_df = pd.read_sql("SELECT * FROM carbon_kpis", db_conn)
    assert not carbon_df.empty
    
    s1 = carbon_df["scope_1_tco2e"].iloc[0]
    s2 = carbon_df["scope_2_tco2e"].iloc[0]
    total = carbon_df["total_tco2e"].iloc[0]
    
    assert round(s1 + s2, 3) == round(total, 3), "Karbon muhasebesi toplam emisyon dengesi hatalı!"