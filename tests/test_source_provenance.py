import json
from pathlib import Path

import pytest

from src.config import runtime_path_context
from src.utils.lineage import generate_run_manifest
from src.utils.source_provenance import read_run_source, sha256_file


def test_manifest_records_original_source_and_class(tmp_path):
    source = tmp_path / "original.csv"
    source.write_text("date,demand\n2026-01-01,3\n", encoding="utf-8")
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "factory_orders.csv").write_text("derived\n", encoding="utf-8")
    reports = tmp_path / "reports"
    with runtime_path_context(
        base_dir=tmp_path,
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        processed_dir=processed,
        reports_dir=reports,
    ):
        manifest = generate_run_manifest(
            "RUN-SOURCE-TEST",
            input_source_path=str(source),
            input_data_class="SYNTHETIC",
            expected_input_sha256=sha256_file(source),
        )
    dataset = manifest["inputs"]["input_dataset"]
    assert dataset["path"] == str(source)
    assert dataset["sha256"] == sha256_file(source)
    assert dataset["data_class"] == "SYNTHETIC"
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "RUN-SOURCE-TEST",
                "files": {"reports/run_manifest.json": {"sha256": sha256_file(reports / "run_manifest.json")}},
            }
        ),
        encoding="utf-8",
    )
    assert read_run_source(reports / "run_manifest.json", "RUN-SOURCE-TEST") == ("SYNTHETIC", str(source))
    assert read_run_source(reports / "run_manifest.json", "OTHER-RUN") == ("UNCLASSIFIED", None)
    (reports / "run_manifest.json").write_text("{}", encoding="utf-8")
    assert read_run_source(reports / "run_manifest.json", "RUN-SOURCE-TEST") == ("UNCLASSIFIED", None)


def test_changed_or_missing_source_fails_sealing(tmp_path):
    source = tmp_path / "original.csv"
    source.write_text("before", encoding="utf-8")
    expected = sha256_file(source)
    source.write_text("after", encoding="utf-8")
    with runtime_path_context(base_dir=tmp_path, data_dir=tmp_path, reports_dir=tmp_path / "reports"):
        with pytest.raises(ValueError, match="değişti"):
            generate_run_manifest("RUN-CHANGED", input_source_path=str(source), expected_input_sha256=expected)
        with pytest.raises(FileNotFoundError, match="girdi dosyası"):
            generate_run_manifest("RUN-MISSING", input_source_path=str(tmp_path / "missing.csv"))


def test_unclassified_legacy_manifest_is_not_presented_as_synthetic(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    manifest = reports / "run_manifest.json"
    manifest.write_text(json.dumps({"run_id": "RUN-OLD", "inputs": {"input_dataset": {"path": "x", "sha256": "y"}}}))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"run_id": "RUN-OLD", "files": {"reports/run_manifest.json": {"sha256": sha256_file(manifest)}}})
    )
    assert read_run_source(manifest, "RUN-OLD") == ("UNCLASSIFIED", None)
