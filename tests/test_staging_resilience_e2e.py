"""
End-to-End Orchestration & Staging Resilience Test (Audit Item 28)

Doğrulanacak Mimari Davranış:
1. RUN-A çalıştırılır -> Başarıyla tamamlanır ve canonical_db üzerinde ACTIVE statüsüne terfi eder.
2. RUN-B başlatılır -> Staging aşamasında simüle edilen bir hata nedeniyle FAILS olur.
3. İnceleme / Sağlama (Untouched Validation):
   - RUN-B'nin başarısızlığı canonical_db'yi kirletmez.
   - get_active_pipeline_run() sorgusu hâlâ eksiksiz olarak RUN-A'yı döndürür.
   - RUN-A'ya ait üretim çizelgesi ve KPI tabloları bozulmadan kalır.
"""

import os
import shutil
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

from main import run_end_to_end_pipeline
from src.utils.lineage import get_active_pipeline_run


def test_staging_switchover_failure_resilience(tmp_path, monkeypatch):
    test_workspace = tmp_path / "workspace"
    test_workspace.mkdir()

    repo_root = Path(__file__).resolve().parent.parent
    
    for folder in ["config", "data"]:
        src_folder = repo_root / folder
        if src_folder.exists():
            shutil.copytree(
                src_folder,
                test_workspace / folder,
                ignore=shutil.ignore_patterns("*.db", "*.db-journal", "staging_*")
            )

    monkeypatch.chdir(test_workspace)
    canonical_db = test_workspace / "data" / "factory.db"

    # 1. ADIM: RUN-A Başlatılır ve Başarıyla ACTIVE Olur
    success_a = run_end_to_end_pipeline()
    assert success_a is True, "RUN-A başarıyla tamamlanmalıydı."

    active_run_a = get_active_pipeline_run(db_path=str(canonical_db))
    assert active_run_a is not None, "RUN-A canonical DB'de ACTIVE olarak bulunmalı."
    run_a_id = active_run_a["run_id"]
    assert active_run_a["status"] == "ACTIVE"

    with sqlite3.connect(str(canonical_db)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM production_schedule WHERE run_id = ?", (run_a_id,))
        run_a_schedule_count = cursor.fetchone()[0]
    assert run_a_schedule_count > 0, "RUN-A çizelge kayıtları yazılmış olmalı."

    # 2. ADIM: RUN-B Başlatılır ve Validation Sırasında Çöker
    with patch("main.validate_pipeline_run", side_effect=RuntimeError("Simüle Edilmiş Kritik Staging / Solver Hatası")):
        with pytest.raises(RuntimeError, match="Simüle Edilmiş"):
            run_end_to_end_pipeline()

    # 3. ADIM: Sağlama (RUN-A UNTOUCHED Doğrulaması)
    current_active = get_active_pipeline_run(db_path=str(canonical_db))
    assert current_active is not None, "Kanonik DB'de aktif koşum kaybolmamalı."
    assert current_active["run_id"] == run_a_id, f"Aktif koşum RUN-A ({run_a_id}) kalmalıydı."
    assert current_active["status"] == "ACTIVE"

    with sqlite3.connect(str(canonical_db)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM production_schedule WHERE run_id = ?", (run_a_id,))
        count_after = cursor.fetchone()[0]
        assert count_after == run_a_schedule_count, "RUN-B çöküşü RUN-A verilerini etkilememeli!"