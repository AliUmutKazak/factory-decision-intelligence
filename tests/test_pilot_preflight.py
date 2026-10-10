"""G4-T file intake: provenance and reject behavior without runtime writes."""

import json
from pathlib import Path

from src.integration.pilot_preflight import inspect_pilot_package
from src.utils.run_bundle import sha256_file


def package(tmp_path: Path) -> Path:
    files = {
        "orders": "order_id,lot_id,product_id,quantity,due_min\nO1,L1,P1,10,480\n",
        "machines": "machine_id\nM1\n",
        "routing": "product_id,operation_seq,machine_id,duration_min_per_unit\nP1,1,M1,2\n",
        "shifts": "machine_id,start_min,end_min\nM1,0,600\n",
        "current_plan": "lot_id,operation_seq,machine_id,start_min,end_min\nL1,1,M1,60,80\n",
        "actuals": "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty,reported_min\n"
        "L1,1,M1,61,82,9,1,90\n",
    }
    for name, content in files.items():
        (tmp_path / f"{name}.csv").write_text(content, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset_id": "SYNTHETIC-SMALL-01",
                "source_type": "SYNTHETIC",
                "origin": "2026-01-05T00:00:00+03:00",
                "quantity_unit": "piece",
                "time_unit": "minute",
                "max_actual_reporting_lag_min": 30,
                "files": {name: f"{name}.csv" for name in files},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_preflight_accepts_small_labeled_case_without_runtime_writes(tmp_path):
    manifest = package(tmp_path)
    before = {path.name: sha256_file(path) for path in tmp_path.iterdir()}
    report = inspect_pilot_package(manifest)
    assert report["status"] == "ACCEPTED"
    assert report["source_type"] == "SYNTHETIC"
    assert report["quantity_unit"] == "piece"
    assert report["files"]["orders"]["parsed_rows"] == 1
    assert report["files"]["orders"]["sha256"] == before["orders.csv"]
    assert report["scope"] == "FILE_PREFLIGHT_ONLY_NO_SOLVE_NO_PUBLICATION"
    assert report["actuals_timing"]["status"] == "ASSESSED"
    assert report["actuals_timing"]["max_observed_reporting_lag_min"] == 8
    assert report["baseline_coverage"]["status"] == "COMPLETE"
    assert report["baseline_coverage"]["expected_operations"] == 1
    assert {path.name: sha256_file(path) for path in tmp_path.iterdir()} == before


def test_preflight_reports_bad_rows_and_cross_file_references(tmp_path):
    manifest = package(tmp_path)
    orders = tmp_path / "orders.csv"
    orders.write_text(
        "order_id,lot_id,product_id,quantity,due_min\nO1,L1,P1,10,480\nO2,L2,P2,nan,500\nO3,L3,P3,5,600\n",
        encoding="utf-8",
    )
    routing = tmp_path / "routing.csv"
    routing.write_text("product_id,operation_seq,machine_id,duration_min_per_unit\nP1,1,MISSING,2\n", encoding="utf-8")
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    assert ("orders", 3, "invalid_value") in {
        (issue["file"], issue["line"], issue["code"]) for issue in report["rejections"]
    }
    codes = {issue["code"] for issue in report["rejections"]}
    assert {"unknown_machine", "unknown_product_route"} <= codes
    assert report["files"]["orders"]["parsed_rows"] == 2


def test_preflight_rejects_untrusted_paths_and_unowned_customer_data(tmp_path):
    manifest = package(tmp_path)
    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["source_type"] = "CUSTOMER"
    content["files"]["machines"] = "../outside.csv"
    manifest.write_text(json.dumps(content), encoding="utf-8")
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    codes = {issue["code"] for issue in report["rejections"]}
    assert {"path_outside_package", "missing_customer_authority"} <= codes


def test_preflight_rejects_invalid_manifest_and_missing_units(tmp_path):
    manifest = package(tmp_path)
    content = json.loads(manifest.read_text(encoding="utf-8"))
    del content["quantity_unit"]
    manifest.write_text(json.dumps(content), encoding="utf-8")
    assert "missing_quantity_unit" in {r["code"] for r in inspect_pilot_package(manifest)["rejections"]}
    manifest.write_text("{broken", encoding="utf-8")
    assert inspect_pilot_package(manifest)["rejections"][0]["code"] == "invalid_manifest"


def test_preflight_does_not_accept_unimplemented_alternative_machines(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "machines.csv").write_text("machine_id\nM1\nM2\n", encoding="utf-8")
    (tmp_path / "routing.csv").write_text(
        "product_id,operation_seq,machine_id,duration_min_per_unit\nP1,1,M1,2\nP1,1,M2,3\n",
        encoding="utf-8",
    )
    (tmp_path / "shifts.csv").write_text("machine_id,start_min,end_min\nM1,0,600\nM2,0,600\n", encoding="utf-8")
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    assert "unsupported_alternative_machine" in {issue["code"] for issue in report["rejections"]}


def test_preflight_rejects_late_and_out_of_order_actual_reports(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "routing.csv").write_text(
        "product_id,operation_seq,machine_id,duration_min_per_unit\nP1,1,M1,2\nP1,2,M1,2\n",
        encoding="utf-8",
    )
    (tmp_path / "current_plan.csv").write_text(
        "lot_id,operation_seq,machine_id,start_min,end_min\nL1,1,M1,60,80\nL1,2,M1,90,110\n",
        encoding="utf-8",
    )
    (tmp_path / "actuals.csv").write_text(
        "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty,reported_min\n"
        "L1,1,M1,61,82,9,1,130\nL1,2,M1,90,110,9,1,120\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    assert {"late_actual_report", "out_of_order_actual_report"} <= {issue["code"] for issue in report["rejections"]}


def test_preflight_rejects_actual_precedence_and_machine_overlap(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "routing.csv").write_text(
        "product_id,operation_seq,machine_id,duration_min_per_unit\nP1,1,M1,2\nP1,2,M1,2\n",
        encoding="utf-8",
    )
    (tmp_path / "actuals.csv").write_text(
        "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty,reported_min\n"
        "L1,1,M1,61,82,9,1,90\nL1,2,M1,70,100,9,1,105\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert {"actual_precedence", "actual_machine_overlap"} <= {issue["code"] for issue in report["rejections"]}


def test_preflight_rejects_overlapping_current_plan_on_same_machine(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "orders.csv").write_text(
        "order_id,lot_id,product_id,quantity,due_min\nO1,L1,P1,10,480\nO2,L2,P1,10,480\n",
        encoding="utf-8",
    )
    (tmp_path / "current_plan.csv").write_text(
        "lot_id,operation_seq,machine_id,start_min,end_min\nL1,1,M1,60,80\nL2,1,M1,70,90\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    assert ("current_plan", 3, "planned_machine_overlap") in {
        (issue["file"], issue["line"], issue["code"]) for issue in report["rejections"]
    }


def test_preflight_rejects_current_plan_precedence_and_allows_touching_intervals(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "routing.csv").write_text(
        "product_id,operation_seq,machine_id,duration_min_per_unit\nP1,1,M1,2\nP1,2,M1,2\n",
        encoding="utf-8",
    )
    plan = tmp_path / "current_plan.csv"
    plan.write_text(
        "lot_id,operation_seq,machine_id,start_min,end_min\nL1,1,M1,60,80\nL1,2,M1,70,90\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    assert "planned_precedence" in {issue["code"] for issue in report["rejections"]}

    plan.write_text(
        "lot_id,operation_seq,machine_id,start_min,end_min\nL1,1,M1,60,80\nL1,2,M1,80,100\n",
        encoding="utf-8",
    )
    assert inspect_pilot_package(manifest)["status"] == "ACCEPTED"


def test_preflight_reports_partial_baseline_without_claiming_complete_comparison(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "routing.csv").write_text(
        "product_id,operation_seq,machine_id,duration_min_per_unit\nP1,1,M1,2\nP1,2,M1,2\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert report["status"] == "ACCEPTED"
    assert report["baseline_coverage"] == {
        "status": "INCOMPLETE",
        "expected_operations": 2,
        "planned_operations": 1,
        "missing_operations": 1,
        "missing_examples": [["L1", 2]],
    }


def test_preflight_rejects_actual_quantity_above_order(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "actuals.csv").write_text(
        "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty,reported_min\n"
        "L1,1,M1,61,82,10,1,90\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    assert ("actuals", 2, "actual_quantity_exceeds_order") in {
        (issue["file"], issue["line"], issue["code"]) for issue in report["rejections"]
    }

    (tmp_path / "orders.csv").write_text(
        "order_id,lot_id,product_id,quantity,due_min\nO1,L1,P1,1000000000,480\n",
        encoding="utf-8",
    )
    (tmp_path / "actuals.csv").write_text(
        "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty,reported_min\n"
        "L1,1,M1,61,82,1000000001,0,90\n",
        encoding="utf-8",
    )
    assert "actual_quantity_exceeds_order" in {issue["code"] for issue in inspect_pilot_package(manifest)["rejections"]}


def test_preflight_does_not_claim_actual_latency_without_reporting_evidence(tmp_path):
    manifest = package(tmp_path)
    (tmp_path / "actuals.csv").write_text(
        "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty\nL1,1,M1,61,82,9,1\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert report["status"] == "REJECTED"
    assert "missing_reporting_time" in {issue["code"] for issue in report["rejections"]}
    assert report["actuals_timing"]["status"] == "NO_REPORTING_TIMES"

    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["files"].pop("actuals")
    manifest.write_text(json.dumps(content), encoding="utf-8")
    report = inspect_pilot_package(manifest)
    assert report["status"] == "ACCEPTED"
    assert report["actuals_timing"]["status"] == "NO_ACTUALS"

    content["files"]["actuals"] = "actuals.csv"
    content.pop("max_actual_reporting_lag_min")
    manifest.write_text(json.dumps(content), encoding="utf-8")
    (tmp_path / "actuals.csv").write_text(
        "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty,reported_min\n"
        "L1,1,M1,61,82,9,1,900\n",
        encoding="utf-8",
    )
    report = inspect_pilot_package(manifest)
    assert report["status"] == "ACCEPTED"
    assert report["actuals_timing"]["status"] == "NO_DECLARED_LAG_LIMIT"

    (tmp_path / "actuals.csv").write_text(
        "lot_id,operation_seq,machine_id,actual_start_min,actual_end_min,produced_qty,scrap_qty,reported_min\n"
        "L1,1,M1,61,82,9,1,80\n",
        encoding="utf-8",
    )
    assert "reported_before_completion" in {issue["code"] for issue in inspect_pilot_package(manifest)["rejections"]}
