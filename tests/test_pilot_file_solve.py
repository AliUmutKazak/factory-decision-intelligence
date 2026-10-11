"""The file pilot is a guarded laboratory comparison, not a published plan."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.integration.pilot_file_solve import solve_pilot_file_package
from src.integration.pilot_preflight import inspect_pilot_package

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/pilot-solve"
REFERENCE = ROOT / "artifacts/reference/factory.db"


def _package(tmp_path):
    package = tmp_path / "package"
    shutil.copytree(EXAMPLE, package)
    return package


def _replace_csv(package, kind, content):
    target = package / f"{kind}.csv"
    target.write_bytes(content.encode("utf-8"))
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][kind]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_file_pilot_solves_one_shift_without_touching_inputs_or_runtime(tmp_path, monkeypatch):
    package = _package(tmp_path)
    runtime = tmp_path / "runtime" / "factory.db"
    monkeypatch.setenv("FACTORY_DB_PATH", str(runtime))
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in package.iterdir()}
    reference_before = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()

    result = solve_pilot_file_package(package / "manifest.json", time_limit_seconds=5)

    assert result["status"] == "ASSESSED"
    assert result["candidate"]["solver_status"] == "OPTIMAL"
    assert result["candidate"]["independent_check"] == "ACCEPTED"
    assert result["baseline"]["last_completion_min"] == 80
    assert result["candidate"]["last_completion_min"] == 20
    assert result["candidate"]["schedule"] == [
        {"lot_id": "EX-L1", "operation_seq": 1, "machine_id": "EX-M1", "start_min": 0, "end_min": 20}
    ]
    assert not runtime.exists()
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in package.iterdir()} == before
    assert hashlib.sha256(REFERENCE.read_bytes()).hexdigest() == reference_before


def test_file_pilot_rejects_actuals_before_solver(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("actuals must not be ignored by the solver bridge")

    monkeypatch.setattr("src.integration.pilot_file_solve.run_cpsat_scheduling", unexpected)
    result = solve_pilot_file_package(ROOT / "examples/pilot-package/manifest.json")
    assert result["status"] == "UNSUPPORTED"
    assert "actuals_or_wip_not_supported" in result["reasons"]


def test_file_pilot_rejects_calendar_it_cannot_map(tmp_path, monkeypatch):
    package = _package(tmp_path)
    _replace_csv(package, "shifts", "machine_id,start_min,end_min\nEX-M1,0,1500\n")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("unsupported shift must not reach the solver")

    monkeypatch.setattr("src.integration.pilot_file_solve.run_cpsat_scheduling", unexpected)
    result = solve_pilot_file_package(package / "manifest.json")
    assert result["preflight_status"] == "ACCEPTED"
    assert result["status"] == "UNSUPPORTED"
    assert "unsupported_shift_calendar" in result["reasons"]


def test_file_pilot_preserves_multiple_lot_quantities(tmp_path):
    package = _package(tmp_path)
    _replace_csv(
        package,
        "orders",
        "order_id,lot_id,product_id,quantity,due_min\nEX-O1,EX-L1,EX-P1,10,480\nEX-O2,EX-L2,EX-P1,10,480\n",
    )
    _replace_csv(
        package,
        "current_plan",
        "lot_id,operation_seq,machine_id,start_min,end_min,planned_qty\n"
        "EX-L1,1,EX-M1,60,80,10\nEX-L2,1,EX-M1,80,100,10\n",
    )
    result = solve_pilot_file_package(package / "manifest.json", time_limit_seconds=5)
    assert result["status"] == "ASSESSED"
    assert result["candidate"]["lot_count"] == 2
    assert result["candidate"]["operation_count"] == 2
    assert result["candidate"]["last_completion_min"] == 40
    assert result["candidate"]["independent_check"] == "ACCEPTED"


def test_file_pilot_rejects_wrong_reference_hash_before_solving(tmp_path):
    with pytest.raises(ValueError, match="reference DB SHA-256 mismatch"):
        solve_pilot_file_package(
            EXAMPLE / "manifest.json",
            reference_db_path=REFERENCE,
            expected_reference_sha256="0" * 64,
        )


def test_preflight_rejects_file_change_during_read(tmp_path, monkeypatch):
    from src.integration import pilot_preflight

    package = _package(tmp_path)
    original = pilot_preflight._read_csv

    def mutate_after_read(path, kind, configured, reject):
        result = original(path, kind, configured, reject)
        if kind == "orders":
            path.write_bytes(path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(pilot_preflight, "_read_csv", mutate_after_read)
    report = inspect_pilot_package(package / "manifest.json")
    assert report["status"] == "REJECTED"
    assert any(item["code"] == "file_changed_during_read" for item in report["rejections"])
