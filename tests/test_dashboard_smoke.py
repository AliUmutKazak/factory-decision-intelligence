"""A fresh ACTIVE runtime renders without solving scenarios or mutating its database."""

import hashlib
import shutil
import sqlite3
from pathlib import Path

from streamlit.testing.v1 import AppTest

import src.config as cfg
from src.scenarios.scenario_engine import ScenarioEngine


def test_dashboard_renders_active_plan_without_implicit_solves(tmp_path, monkeypatch, dashboard_lab_credentials):
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
    app.sidebar.text_input[0].set_value(dashboard_lab_credentials["read"]).run()
    assert not app.exception
    assert not app.error
    assert any(button.key == "compute_scenarios" for button in app.button)
    assert any("70 €/tCO₂e" in item.value for item in app.info)
    assert app.slider[0].value == 70
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


def test_what_if_review_is_visible_only_to_scenario_role_and_does_not_publish(
    tmp_path, monkeypatch, dashboard_lab_credentials
):
    source = Path(__file__).resolve().parents[1] / "data" / "factory.db"
    target = tmp_path / "factory.db"
    shutil.copy2(source, target)
    monkeypatch.setenv("FACTORY_DB_PATH", str(target))
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    with sqlite3.connect(target) as conn:
        active = conn.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE'").fetchone()[0]

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"), default_timeout=30).run()
    app.sidebar.text_input[0].set_value(dashboard_lab_credentials["scenario"]).run()
    app.session_state["what_if_candidate"] = {
        "active_run_id_at_simulation": active,
        "input": {"machine_id": "M01"},
        "baseline_solver": {"status": "FEASIBLE"},
        "candidate_solver": {"status": "FEASIBLE", "proven_optimal": False, "wall_time_seconds": 1.0},
        "comparison": {
            "baseline_makespan_min": 100,
            "scenario_makespan_min": 110,
            "makespan_delta_min": 10,
            "baseline_total_tardiness_min": 20,
            "scenario_total_tardiness_min": 25,
            "tardiness_delta_min": 5,
            "baseline_total_setup_min": 3,
            "scenario_total_setup_min": 4,
            "setup_delta_min": 1,
            "changed_existing_task_count": 1,
            "new_task_count": 0,
            "absolute_existing_start_shift_min": 5,
            "operation_changes": [{"task_id": "T1", "change_type": "CHANGED", "start_shift_min": 5}],
        },
    }
    app.run()
    assert not app.exception
    assert any("Aday plan karşılaştırması" in item.value for item in app.markdown)
    assert any(item.label == "Laboratuvar ön değerlendirmesi" for item in app.selectbox)
    app.sidebar.text_input[0].set_value(dashboard_lab_credentials["read"]).run()
    assert not app.exception
    assert not any("Aday plan karşılaştırması" in item.value for item in app.markdown)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
