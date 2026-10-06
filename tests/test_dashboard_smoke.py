"""A fresh ACTIVE runtime renders without solving scenarios or mutating its database."""

import hashlib
import shutil
from pathlib import Path

from streamlit.testing.v1 import AppTest

import src.config as cfg
from src.scenarios.scenario_engine import ScenarioEngine


def test_dashboard_renders_active_plan_without_implicit_solves(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "data" / "factory.db"
    target = tmp_path / "factory.db"
    shutil.copy2(source, target)
    monkeypatch.setenv("FACTORY_DB_PATH", str(target))
    monkeypatch.setattr(cfg, "ECONOMIC_CONFIG", cfg.ECONOMIC_CONFIG.model_copy(update={"carbon_price_per_ton": 70.0}))
    before = hashlib.sha256(target.read_bytes()).hexdigest()

    def unexpected_solve(*args, **kwargs):
        raise AssertionError("Viewing a dashboard must not rerun the scenario matrix.")

    monkeypatch.setattr(ScenarioEngine, "run_all_scenarios", unexpected_solve)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert not app.error
    assert any(button.key == "compute_scenarios" for button in app.button)
    assert any("70 €/tCO₂e" in item.value for item in app.info)
    assert app.slider[0].value == 70
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
