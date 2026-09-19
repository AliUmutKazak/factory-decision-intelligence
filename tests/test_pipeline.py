import sys
import sqlite3
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

# Kök dizini modül arama yoluna ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    DB_PATH,
    PLANNING_HORIZON_WEEKS,
    WEEKLY_HOURS_PER_MACHINE,
    LABOR_COST_OVERTIME_HR,
    GRID_EMISSION_FACTOR,
    MRP_SERVICE_LEVEL_Z,
)


@pytest.fixture(scope="module")
def db_connection():
    """SQLite veritabanı bağlantısı sağlar."""
    assert DB_PATH.exists(), f"Veritabanı dosyası bulunamadı: {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


def test_ssot_config_parameters():
    """SSOT yapılandırma parametrelerinin doğruluğunu denetler."""
    assert PLANNING_HORIZON_WEEKS == 4, "Planlama ufku 4 hafta olmalı."
    assert WEEKLY_HOURS_PER_MACHINE == 96.0, "Haftalık standart kapasite 96 saat olmalı."
    assert LABOR_COST_OVERTIME_HR == 675.0, "Fazla mesai saatlik maliyeti 675 TL/saat olmalı."
    assert MRP_SERVICE_LEVEL_Z > 0, "MRP hizmet seviyesi faktörü pozitif olmalıdır."
    assert GRID_EMISSION_FACTOR == 0.440, "Şebeke elektrik emisyon faktörü 0.440 kgCO2e/kWh olmalı."


def test_database_tables_exist_and_non_empty(db_connection):
    """Gerekli tüm ana ve türetilmiş tabloların varlığını ve doluluğunu denetler."""
    required_tables = [
        # Çekirdek Tablolar
        "orders", "machines", "products", "materials", "bom", "routing", "changeover_matrix",
        # Analitik Çıktı Tabloları
        "forecast_demand", "aggregate_plan", "sku_production_plan",
        "production_schedule", "mrp_plan", "energy_kpis", "carbon_kpis",
        "energy_profile_15min", "carbon_price_scenarios"
    ]
    cursor = db_connection.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    existing_tables = [row[0] for row in cursor.fetchall()]

    for table in required_tables:
        assert table in existing_tables, f"Kritik tablo eksik: {table}"
        count = pd.read_sql(f"SELECT COUNT(*) as cnt FROM {table}", db_connection).iloc[0]["cnt"]
        assert count > 0, f"Tablo boş olamaz: {table}"


def test_forecasting_integrity(db_connection):
    """Tahminleme sonuçlarının sızıntısız ve eksiksiz olduğunu doğrular."""
    df = pd.read_sql("SELECT * FROM forecast_demand", db_connection)
    
    # 5 ürün x 28 gün = 140 satır
    assert len(df) == 140, f"Beklenen 140 tahmin kaydı, bulunan: {len(df)}"
    assert not df["forecast_demand"].isna().any(), "Tahminlerde NaN değer olamaz."
    assert (df["forecast_demand"] > 0).all(), "Tahmin değerleri kesinlikle pozitif olmalıdır."
    
    # Model seçim kontrolü
    assert set(df["product_id"].unique()) == {"P01", "P02", "P03", "P04", "P05"}
    assert set(df["model_used"].unique()).issubset({"Holt-Winters", "LightGBM"})


def test_scheduling_no_machine_overlap(db_connection):
    """CP-SAT kısıtı: Aynı tezgahtaki işlerin birbiriyle çakışmadığını matematiksel olarak kanıtlar."""
    df = pd.read_sql("SELECT * FROM production_schedule ORDER BY machine_id, start_min", db_connection)
    
    for machine_id, group in df.groupby("machine_id"):
        sorted_ops = group.sort_values(by="start_min").to_dict("records")
        for i in range(len(sorted_ops) - 1):
            current_op = sorted_ops[i]
            next_op = sorted_ops[i + 1]
            assert current_op["end_min"] <= next_op["start_min"], (
                f"Tezgah {machine_id} üzerinde kısıt ihlali! "
                f"İş {current_op['batch_id']} bitişi ({current_op['end_min']}) > "
                f"İş {next_op['batch_id']} başlangıcı ({next_op['start_min']})"
            )


def test_mrp_net_requirements_and_lead_times(db_connection):
    """Zaman fazlı MRP hesaplarının ve bütçe tutarlılığının testi."""
    mrp_df = pd.read_sql("SELECT * FROM mrp_plan", db_connection)
    
    assert len(mrp_df) > 0, "MRP planı boş olamaz."
    assert (mrp_df["projected_avail"] >= 0).all(), "Dönem sonu stoku eksiye düşemez (Net ihtiyaç tetiklenmeli)."
    
    # Geçmişe sarkan siparişlerde EXPEDITE uyarısı kontrolü
    past_due_orders = mrp_df[mrp_df["action_message"].str.contains("EXPEDITE", na=False)]
    assert len(past_due_orders) > 0, "En az bir siparişte EXPEDITE uyarısı bekleniyordu."


def test_sustainability_energy_and_carbon_coherence(db_connection):
    """Enerji profili ile GHG karbon muhasebesi arasındaki matematiksel tutarlılık testi."""
    e_kpi = pd.read_sql("SELECT * FROM energy_kpis", db_connection).iloc[0]
    c_kpi = pd.read_sql("SELECT * FROM carbon_kpis", db_connection).iloc[0]
    prof_df = pd.read_sql("SELECT * FROM energy_profile_15min", db_connection)

    # Tepe yük doğrulama
    max_profile_load = prof_df["total_load_kw"].max()
    assert np.isclose(e_kpi["peak_load_kw"], max_profile_load, atol=0.1), (
        f"KPI tepe yükü ({e_kpi['peak_load_kw']}) ile profil maksimumu ({max_profile_load}) uyuşmuyor."
    )

    # Karbon Kapsam 1 + 2 = Toplam
    assert np.isclose(c_kpi["total_tco2e"], c_kpi["scope_1_tco2e"] + c_kpi["scope_2_tco2e"], atol=0.001), (
        "Toplam karbon Kapsam 1 ve Kapsam 2 toplamına eşit olmalıdır."
    )
    assert c_kpi["kgco2e_per_unit"] > 0, "Birim karbon ayak izi pozitif olmalı."
