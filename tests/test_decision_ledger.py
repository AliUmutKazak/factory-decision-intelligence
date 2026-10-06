"""Tests for Decision Ledger (Madde 34)."""

import json
import sqlite3

import pytest

from src.contracts.decision_ledger import DecisionLedger, DecisionLedgerEntry


def test_decision_ledger_record_and_explain():
    ledger = DecisionLedger()

    entry = DecisionLedgerEntry(
        decision_id="DEC-000431",
        run_id="RUN-2026-10-04-01",
        decision_type="RE_SEQUENCE",
        input_state={"machine_down": "M01", "down_duration_min": 360},
        triggered_reason="M01 unavailable for 360 min",
        selected_action="Re-sequence P03 -> P01",
        why=[
            "P03 has higher customer priority",
            "P03 material already available",
            "reduces weighted tardiness by 1.7h",
            "setup impact +12min",
        ],
        rejected_alternatives=[
            "Split batch P01 across M02 (exceeds overtime limit)",
            "Wait until M01 repairs (violates SLA due date)",
        ],
        expected_kpi_impact={
            "tardiness_reduction_hours": 1.7,
            "setup_penalty_minutes": 12,
        },
        solver_version="CP-SAT",
    )

    ledger.record(entry)

    # Sorgulama kontrolleri
    retrieved = ledger.get_by_decision_id("DEC-000431")
    assert retrieved is not None
    assert retrieved.selected_action == "Re-sequence P03 -> P01"
    assert len(retrieved.why) == 4

    # JSON serileştirme kontrolü
    json_out = ledger.to_json()
    data = json.loads(json_out)
    assert len(data) == 1
    assert data[0]["decision_id"] == "DEC-000431"

    # LLM/Copilot açıklama metni kontrolü
    explanation = retrieved.explain()
    assert "Trigger: M01 unavailable for 360 min" in explanation
    assert "P03 has higher customer priority" in explanation
    assert "CP-SAT" in explanation


def test_durable_decisions_survive_reopening_and_are_immutable(tmp_path):
    path = tmp_path / "decisions.db"
    entry = DecisionLedgerEntry(
        decision_id="D1",
        run_id="R1",
        decision_type="RESCHEDULE",
        input_state={"machine_id": "M01"},
        triggered_reason="breakdown",
        selected_action="new schedule version",
    )
    DecisionLedger(path).record(entry)
    reopened = DecisionLedger(path)
    assert reopened.get_by_run_id("R1") == [entry]
    assert reopened.get_by_run_id("OTHER") == []
    with pytest.raises(sqlite3.IntegrityError):
        reopened.record(entry)
    assert DecisionLedger(path).get_by_decision_id("D1") == entry
