import os
import shutil
import sys

# Proje kök dizinini sys.path'e ekle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from pathlib import Path

import pytest

from src.carbon.carbon_analytics import compute_carbon_analytics
from src.config import DB_PATH
from src.energy.energy_analytics import compute_energy_analytics
from src.utils.db import get_db_connection


@pytest.fixture(scope="session", autouse=True)
def ensure_full_pipeline_database():
    """
    Test oturumu başlamadan önce veritabanında tüm downstream
    tabloların (energy_kpis, carbon_kpis vb.) mevcut olduğundan emin olur.
    """
    if Path(DB_PATH).exists():
        conn = get_db_connection(DB_PATH)
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


@pytest.fixture(autouse=True)
def isolate_mutating_integration_tests(request, tmp_path, monkeypatch, ensure_full_pipeline_database):
    """Each API/MES solve starts from the same sealed baseline, not another test's ACTIVE run."""
    if request.module.__name__.split(".")[-1] not in {
        "test_api_server",
        "test_dynamic_rescheduler",
        "test_execution_feedback",
        "test_frozen_horizon",
        "test_rescheduler",
        "test_mes_integration",
        "test_objective_policies",
    }:
        return
    import src.config as cfg

    source = Path(cfg.get_runtime_paths()["db_path"])
    if not source.exists():
        pytest.fail("Run python main.py before integration tests.")
    root = tmp_path / "runtime"
    (root / "data").mkdir(parents=True)
    target = root / "data" / "factory.db"
    shutil.copy2(source, target)
    monkeypatch.setattr(cfg, "BASE_DIR", root)
    monkeypatch.setenv("FACTORY_DB_PATH", str(target))
    monkeypatch.setenv("FACTORY_PROCESSED_DIR", str(root / "data" / "processed"))
    monkeypatch.setenv("FACTORY_REPORTS_DIR", str(root / "reports"))
