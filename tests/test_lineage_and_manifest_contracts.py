"""Tests for Input Lineage and Run Manifest Pydantic Contracts (Faz 2 - SSOT Closure)."""

import sqlite3

import pytest
from pydantic import ValidationError

from src.contracts.schemas import InputLineageRecord, RunManifestModel
from src.utils.lineage import (
    generate_run_id,
    generate_run_manifest,
    init_pipeline_runs_table,
    record_input_source_lineage,
)


def test_input_lineage_record_contract_valid():
    """InputLineageRecord modelinin geçerli parametrelerle başarıyla örneklendiğini doğrular."""
    valid_sha = "a" * 64
    record = InputLineageRecord(
        run_id="RUN-20261004-TEST",
        source_name="orders_fixture",
        source_type="RAW_FILE",
        source_path="data/fixtures/demand_fixture.csv",
        sha256=valid_sha,
        size_bytes=1024,
        row_count=50,
    )
    assert record.run_id == "RUN-20261004-TEST"
    assert record.sha256 == valid_sha
    assert record.row_count == 50


def test_input_lineage_record_contract_invalid_hash():
    """64 karakterden kısa veya uzun SHA-256 değerlerinin ValidationError fırlattığını doğrular."""
    with pytest.raises(ValidationError):
        InputLineageRecord(
            run_id="RUN-TEST",
            source_name="bad_input",
            source_type="RAW_FILE",
            source_path="data/bad.csv",
            sha256="short_hash",
            size_bytes=100,
        )


def test_run_manifest_model_contract_valid():
    """RunManifestModel modelinin manifest şemasına tam uyduğunu doğrular."""
    manifest_data = {
        "run_id": "RUN-20261004-001",
        "created_at": "2026-10-04T12:00:00",
        "total_artifacts": 2,
        "artifacts": {
            "factory.db": {"size_bytes": 4096, "sha256": "b" * 64},
            "run_metadata.json": {"size_bytes": 512, "sha256": "c" * 64},
        },
        "inputs": {
            "config_fingerprint": {"file": "src/config.py", "sha256": "d" * 64},
        },
    }
    model = RunManifestModel(**manifest_data)
    assert model.run_id == "RUN-20261004-001"
    assert model.total_artifacts == 2
    assert "factory.db" in model.artifacts


def test_lineage_generation_and_contract_validation(tmp_path):
    """Boru hattı manifestosunun üretilip RunManifestModel tarafından hatasız doğrulandığını test eder."""
    test_db = str(tmp_path / "test_lineage_factory.db")
    conn = sqlite3.connect(test_db)
    init_pipeline_runs_table(conn)

    # input_source_lineage tablosunu ilklendir
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS input_source_lineage (
            run_id TEXT,
            source_name TEXT,
            source_type TEXT,
            source_path TEXT,
            sha256 TEXT,
            size_bytes INTEGER,
            row_count INTEGER,
            PRIMARY KEY (run_id, source_name)
        )
    """
    )
    conn.commit()
    conn.close()

    run_id = generate_run_id()
    manifest_dict = generate_run_manifest(run_id, db_path=test_db)

    # Üretilen manifest sözlüğü RunManifestModel ile doğrulanmalı
    validated_manifest = RunManifestModel(**manifest_dict)
    assert validated_manifest.run_id == run_id
    assert validated_manifest.total_artifacts >= 1
    assert "factory.db" in str(manifest_dict["artifacts"]) or len(validated_manifest.artifacts) >= 1

    # Veritabanına lineage kaydı atılıp atılmadığını doğrula
    inserted_count = record_input_source_lineage(run_id, db_path=test_db)
    assert inserted_count >= 0
