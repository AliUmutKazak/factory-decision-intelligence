import sys
import os

# Proje kök dizinini sys.path'e ekle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlite3
import pytest
from pathlib import Path
from src.config import DB_PATH
from src.energy.energy_analytics import compute_energy_analytics
from src.carbon.carbon_analytics import compute_carbon_analytics

@pytest.fixture(scope="session", autouse=True)
def ensure_full_pipeline_database():
    """
    Test oturumu başlamadan önce veritabanında tüm downstream
    tabloların (energy_kpis, carbon_kpis vb.) mevcut olduğundan emin olur.
    """
    if Path(DB_PATH).exists():
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='carbon_kpis'")
        has_carbon = cur.fetchone() is not None
        conn.close()

        if not has_carbon:
            try:
                compute_energy_analytics()
                compute_carbon_analytics()
            except Exception:
                pass
    yield