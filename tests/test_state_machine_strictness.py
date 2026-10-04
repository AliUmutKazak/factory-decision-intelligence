"""Tests for Pipeline State Machine and Active Run Strictness (Faz 1 - Madde 7 & 8)."""

import sqlite3

import pytest

from src.utils.lineage import (
    VALID_STATUS_TRANSITIONS,
    get_active_pipeline_run,
    init_pipeline_runs_table,
    update_pipeline_run_status,
)


def test_state_machine_transition_rules():
    """Doğrulanmış durum geçiş matrisinin kilitli kurallarını denetler."""
    assert "ACTIVE" in VALID_STATUS_TRANSITIONS["COMPLETED"]
    assert "FAILED" in VALID_STATUS_TRANSITIONS["INITIALIZED"]
    assert VALID_STATUS_TRANSITIONS["FAILED"] == set()
    assert VALID_STATUS_TRANSITIONS["ARCHIVED"] == set()


def test_state_machine_bypass_prevention(tmp_path):
    """Geçersiz veya bypass eden bir durum geçişinin kesin olarak ValueError fırlattığını doğrular."""
    test_db = str(tmp_path / "test_factory.db")

    conn = sqlite3.connect(test_db)
    init_pipeline_runs_table(conn)

    cur = conn.cursor()
    # 1. INITIALIZED durumunda bir kayıt ekle
    cur.execute(
        "INSERT INTO pipeline_runs (run_id, timestamp, status) VALUES (?, datetime('now'), ?)",
        ("RUN-TEST-01", "INITIALIZED"),
    )
    # 2. FAILED durumunda bir kayıt ekle
    cur.execute(
        "INSERT INTO pipeline_runs (run_id, timestamp, status) VALUES (?, datetime('now'), ?)",
        ("RUN-TEST-02", "FAILED"),
    )
    conn.commit()
    conn.close()

    # INITIALIZED -> Doğrudan COMPLETED'e geçiş denemesi (Bypass) engellenmeli
    with pytest.raises(ValueError, match=r"\[STATE MACHINE VIOLATION\]"):
        update_pipeline_run_status(
            run_id="RUN-TEST-01",
            status="COMPLETED",
            db_path=test_db,
        )

    # FAILED -> Doğrudan ACTIVE'e geçiş denemesi engellenmeli
    with pytest.raises(ValueError, match=r"\[STATE MACHINE VIOLATION\]"):
        update_pipeline_run_status(
            run_id="RUN-TEST-02",
            status="ACTIVE",
            db_path=test_db,
        )


def test_active_run_strictness_no_fallback():
    """Fallback kapalıyken (strict mode) get_active_pipeline_run davranışını denetler."""
    active_run = get_active_pipeline_run(allow_fallback=False)
    if active_run is not None:
        assert active_run.get("status") == "ACTIVE"
        assert "run_id" in active_run
