"""External fixed-route data must stay isolated from the production runtime."""

import hashlib
from pathlib import Path

import pytest

from src.scheduling.external_jsp_benchmark import run_orlibrary_fixed_jsp


def test_fixed_jsp_uses_production_solver_and_independent_checker_without_disk_writes(tmp_path):
    source = tmp_path / "jobshop1.txt"
    source.write_text(
        "instance demo\nSynthetic 2x2\n2 2\n0 3 1 2\n1 2 0 4\n",
        encoding="utf-8",
    )
    reference = Path(__file__).resolve().parents[1] / "artifacts/reference/factory.db"
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    reference_before = hashlib.sha256(reference.read_bytes()).hexdigest()

    report = run_orlibrary_fixed_jsp(
        source,
        "demo",
        expected_sha256=source_before,
        reference_db_path=reference,
        time_limit_seconds=5,
    )

    assert report["solver_status"] == "OPTIMAL"
    assert report["proven_optimal_for_model"] is True
    assert report["relative_makespan"] == 7
    assert report["comparable_static_jsp_subset"] is True
    assert all(report["neutrality_checks"].values())
    assert report["independent_check"]["status"] == "ACCEPTED"
    assert report["source_sha256"] == source_before
    assert report["reference_db_sha256"] == reference_before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_before
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == reference_before


def test_fixed_jsp_rejects_source_hash_mismatch_before_solving(tmp_path):
    source = tmp_path / "jobshop1.txt"
    source.write_text("instance demo\n1 1\n0 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        run_orlibrary_fixed_jsp(
            source,
            "demo",
            expected_sha256="0" * 64,
            reference_db_path=tmp_path / "unopened.db",
        )
    assert not (tmp_path / "unopened.db").exists()


def test_fixed_jsp_rejects_unsealed_reference_db(tmp_path):
    source = tmp_path / "jobshop1.txt"
    source.write_text("instance demo\n1 1\n0 1\n", encoding="utf-8")
    reference = tmp_path / "wrong.db"
    reference.write_bytes(b"not the sealed reference")
    with pytest.raises(ValueError, match="reference DB SHA-256 mismatch"):
        run_orlibrary_fixed_jsp(
            source,
            "demo",
            expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            reference_db_path=reference,
        )
