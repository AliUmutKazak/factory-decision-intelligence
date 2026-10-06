"""Failures found while closing run isolation and rescheduling regressions."""

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import src.config as cfg
from src.config import get_runtime_paths, runtime_path_context
from src.utils.lineage import apply_run_retention_policy, init_pipeline_runs_table, start_pipeline_run
from src.utils.run_bundle import RunBundleError, export_run_database, seal_run_bundle, verify_run_bundle


def test_ambiguous_active_runs_fail_closed():
    from src.utils.db import get_active_run_id
    from src.utils.lineage import get_active_pipeline_run

    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE pipeline_runs(run_id TEXT, status TEXT)")
        conn.executemany("INSERT INTO pipeline_runs VALUES (?, 'ACTIVE')", [("A",), ("B",)])
        with pytest.raises(RuntimeError, match="Multiple ACTIVE"):
            get_active_run_id(conn)


def test_runtime_paths_do_not_leak_into_another_thread(tmp_path):
    canonical = get_runtime_paths()["db_path"]
    with ThreadPoolExecutor(max_workers=1) as executor:
        with runtime_path_context(db_path=tmp_path / "staging.db"):
            assert get_runtime_paths()["db_path"] == tmp_path / "staging.db"
            assert executor.submit(lambda: get_runtime_paths()["db_path"]).result() == canonical
    assert get_runtime_paths()["db_path"] == canonical


def test_staging_context_takes_precedence_over_environment_database(tmp_path, monkeypatch):
    from src.data.preprocessing import get_erp_product_mapping
    from src.scenarios.closed_loop import ClosedLoopEngine
    from src.scenarios.scenario_engine import ScenarioEngine
    from src.utils.db import get_db_connection
    from src.utils.lineage import update_pipeline_run_status

    external = tmp_path / "environment.db"
    staging = tmp_path / "staging.db"
    monkeypatch.setenv("FACTORY_DB_PATH", str(external))
    with runtime_path_context(db_path=staging):
        with get_db_connection(cfg.DB_PATH) as conn:
            conn.execute("CREATE TABLE staged(value INTEGER)")
            conn.execute(
                "CREATE TABLE erp_product_mapping(source_product_code TEXT, internal_product_id TEXT, "
                "is_in_scope INTEGER, source_system TEXT, status TEXT)"
            )
            conn.execute("INSERT INTO erp_product_mapping VALUES ('777', 'STAGED_SKU', 1, 'KAGGLE', 'active')")
        start_pipeline_run("STAGED", db_path=None)
        update_pipeline_run_status("STAGED", "STAGING")
        assert ScenarioEngine().db_path == str(staging)
        assert ClosedLoopEngine().db_path == str(staging)
        assert get_erp_product_mapping()[0][777] == "STAGED_SKU"
        assert ScenarioEngine(str(external)).db_path == str(external)
    assert not external.exists()
    with sqlite3.connect(staging) as conn:
        assert conn.execute("SELECT run_id, status FROM pipeline_runs").fetchone() == ("STAGED", "STAGING")


def test_validation_uses_context_reports_before_environment_reports(tmp_path, monkeypatch):
    from src.utils.db import get_active_run_id
    from src.utils.lineage import validate_pipeline_run

    paths = get_runtime_paths()
    staging = tmp_path / "staging.db"
    reports = tmp_path / "staging-reports"
    shutil.copy2(paths["db_path"], staging)
    shutil.copytree(paths["reports_dir"], reports)
    with sqlite3.connect(staging) as conn:
        active = get_active_run_id(conn)
    wrong_reports = tmp_path / "environment-reports"
    monkeypatch.setenv("FACTORY_REPORTS_DIR", str(wrong_reports))
    with runtime_path_context(db_path=staging, reports_dir=reports):
        assert validate_pipeline_run(active)
    assert not wrong_reports.exists()


def test_reference_source_survives_run_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "BASE_DIR", tmp_path)
    reference = tmp_path / "artifacts" / "reference"
    reference.mkdir(parents=True)
    (reference / "manifest.json").write_text(json.dumps({"run_id": "REFERENCE"}))
    db = tmp_path / "factory.db"
    with sqlite3.connect(db) as conn:
        init_pipeline_runs_table(conn)
        conn.executemany(
            "INSERT INTO pipeline_runs(run_id, timestamp, status) VALUES (?, ?, ?)",
            [
                ("REFERENCE", "2026-01-01", "ARCHIVED"),
                ("OLD", "2026-01-02", "ARCHIVED"),
                ("LIVE", "2026-01-03", "ACTIVE"),
            ],
        )
    apply_run_retention_policy(keep_last_n=1, db_path=str(db))
    with sqlite3.connect(db) as conn:
        assert {row[0] for row in conn.execute("SELECT run_id FROM pipeline_runs")} == {"REFERENCE", "LIVE"}


def test_run_snapshot_excludes_other_run_data(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "snapshot.db"
    with sqlite3.connect(source) as conn:
        init_pipeline_runs_table(conn)
        conn.executemany(
            "INSERT INTO pipeline_runs(run_id,timestamp,status) VALUES (?, '2026-01-01', ?)",
            [("OLD", "ARCHIVED"), ("NEW", "COMPLETED")],
        )
        pd.DataFrame([{"run_id": "OLD", "quantity": 100}, {"run_id": "NEW", "quantity": 200}]).to_sql(
            "orders", conn, index=False
        )
    export_run_database(source, target, "NEW")
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT run_id,quantity FROM orders").fetchall() == [("NEW", 200)]
        assert conn.execute("SELECT run_id FROM pipeline_runs").fetchall() == [("NEW",)]
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2


def test_retention_of_external_database_does_not_remove_canonical_bundle(tmp_path, monkeypatch):
    root = tmp_path / "project"
    monkeypatch.setattr(cfg, "BASE_DIR", root)
    bundle = root / "artifacts" / "runs" / "CANONICAL"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"run_id":"CANONICAL"}')
    external = tmp_path / "external" / "factory.db"
    external.parent.mkdir()
    with sqlite3.connect(external) as conn:
        init_pipeline_runs_table(conn)
    apply_run_retention_policy(db_path=str(external))
    assert (bundle / "manifest.json").exists()


def test_existing_run_cannot_be_restarted(tmp_path):
    db = tmp_path / "factory.db"
    start_pipeline_run("IMMUTABLE", db_path=str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE pipeline_runs SET status='ACTIVE' WHERE run_id='IMMUTABLE'")
    with pytest.raises(ValueError, match="already exists"):
        start_pipeline_run("IMMUTABLE", db_path=str(db))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM pipeline_runs").fetchone()[0] == "ACTIVE"


def test_bundle_verifier_rejects_tampered_and_unlisted_payloads(tmp_path):
    (tmp_path / "factory.db").write_bytes(b"snapshot")
    seal_run_bundle(tmp_path, "SEALED")
    verify_run_bundle(tmp_path, "SEALED")
    (tmp_path / "extra.csv").write_text("unsealed")
    with pytest.raises(RunBundleError, match="file sets"):
        verify_run_bundle(tmp_path, "SEALED")
    (tmp_path / "extra.csv").unlink()
    (tmp_path / "factory.db").write_bytes(b"changed")
    with pytest.raises(RunBundleError, match="hash mismatch"):
        verify_run_bundle(tmp_path, "SEALED")
    (tmp_path / "production_schedule.csv").write_text("task_id,start_min\n1,480\n")
    seal_run_bundle(tmp_path, "SEALED")
    with pytest.raises(RunBundleError, match="no run_id"):
        verify_run_bundle(tmp_path, "SEALED")


def test_writer_lock_supports_nested_rescheduler_calls(tmp_path):
    from src.utils.runtime_lock import run_mutation_lock

    with run_mutation_lock(tmp_path / "factory.db"):
        with run_mutation_lock(tmp_path / "factory.db"):
            assert True


def test_sealing_failure_preserves_active_database_and_caches(tmp_path, monkeypatch):
    from contextlib import ExitStack

    import main

    monkeypatch.chdir(tmp_path)
    db = tmp_path / "data" / "factory.db"
    db.parent.mkdir()
    processed, reports = tmp_path / "data" / "processed", tmp_path / "reports"
    processed.mkdir()
    reports.mkdir()
    (processed / "sentinel.csv").write_text("previous run\n")
    (reports / "sentinel.json").write_text('{"run_id":"PREVIOUS"}')
    with sqlite3.connect(db) as conn:
        init_pipeline_runs_table(conn)
        conn.execute("INSERT INTO pipeline_runs(run_id,timestamp,status) VALUES ('PREVIOUS','2026-01-01','ACTIVE')")
        pd.DataFrame([{"run_id": "PREVIOUS", "task_id": 1, "start_min": 480, "end_min": 540}]).to_sql(
            "production_schedule", conn, index=False
        )
    monkeypatch.setenv("FACTORY_CANONICAL_DB", str(db))
    previous_paths = get_runtime_paths()
    with ExitStack() as stack:
        for function in (
            "run_preprocessing",
            "initialize_database",
            "run_forecast_benchmark",
            "run_planning_pipeline",
            "run_mrp_engine",
            "solve_cpsat_schedule",
            "compute_energy_analytics",
            "compute_carbon_analytics",
            "validate_pipeline_run",
        ):
            stack.enter_context(patch(f"main.{function}"))
        stack.enter_context(patch("main.generate_run_manifest", return_value={"total_artifacts": 0}))
        stack.enter_context(patch("main.seal_run_bundle", side_effect=RuntimeError("seal failure")))
        with pytest.raises(RuntimeError, match="seal failure"):
            main.run_end_to_end_pipeline()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT run_id FROM pipeline_runs WHERE status='ACTIVE'").fetchone()[0] == "PREVIOUS"
        assert conn.execute("SELECT run_id,start_min,end_min FROM production_schedule").fetchall() == [
            ("PREVIOUS", 480, 540)
        ]
    assert (processed / "sentinel.csv").read_text() == "previous run\n"
    assert json.loads((reports / "sentinel.json").read_text()) == {"run_id": "PREVIOUS"}
    assert get_runtime_paths() == previous_paths
