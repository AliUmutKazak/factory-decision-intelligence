"""Decision audit trail for explainable operational decisions."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.db import get_db_connection


@dataclass
class DecisionLedgerEntry:
    decision_id: str
    run_id: str
    decision_type: str
    input_state: dict[str, Any]
    triggered_reason: str
    selected_action: str
    why: list[str] = field(default_factory=list)
    rejected_alternatives: list[str] = field(default_factory=list)
    expected_kpi_impact: dict[str, Any] = field(default_factory=dict)
    model_version: str = "v1.0.0"
    solver_version: str = "CP-SAT"
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def explain(self) -> str:
        lines = [
            f"Decision: {self.decision_id} ({self.decision_type})",
            f"Trigger: {self.triggered_reason}",
            f"Action: {self.selected_action}",
            "Why:",
        ]
        lines.extend(f"  - {reason}" for reason in self.why)
        if self.rejected_alternatives:
            lines.append("Rejected Alternatives:")
            lines.extend(f"  - {alt}" for alt in self.rejected_alternatives)
        lines.append(f"Expected KPI Impact: {self.expected_kpi_impact}")
        lines.append(f"Solver: {self.solver_version} | Run: {self.run_id}")
        return "\n".join(lines)


class DecisionLedger:
    """Decision ledger with optional durable SQLite persistence.

    ``db_path=None`` preserves the lightweight in-memory behavior expected by
    isolated unit tests. Production callers pass the runtime database path so
    decisions survive process restarts and can be queried by run lineage.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.entries: list[DecisionLedgerEntry] = []
        self.db_path = str(db_path) if db_path is not None else None
        if self.db_path:
            self._ensure_table()

    def _ensure_table(self) -> None:
        with closing(get_db_connection(self.db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_ledger (
                    decision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    input_state_json TEXT NOT NULL,
                    triggered_reason TEXT NOT NULL,
                    selected_action TEXT NOT NULL,
                    why_json TEXT NOT NULL,
                    rejected_alternatives_json TEXT NOT NULL,
                    expected_kpi_impact_json TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    solver_version TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decision_ledger_run ON decision_ledger(run_id, timestamp)")
            conn.commit()

    @staticmethod
    def _from_row(row) -> DecisionLedgerEntry:
        return DecisionLedgerEntry(
            decision_id=row[0],
            run_id=row[1],
            decision_type=row[2],
            input_state=json.loads(row[3]),
            triggered_reason=row[4],
            selected_action=row[5],
            why=json.loads(row[6]),
            rejected_alternatives=json.loads(row[7]),
            expected_kpi_impact=json.loads(row[8]),
            model_version=row[9],
            solver_version=row[10],
            timestamp=row[11],
        )

    def record(self, entry: DecisionLedgerEntry) -> None:
        if self.db_path is None:
            if any(e.decision_id == entry.decision_id for e in self.entries):
                raise ValueError(f"Duplicate decision_id: {entry.decision_id}")
            self.entries.append(entry)
            return

        with closing(get_db_connection(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO decision_ledger (
                    decision_id, run_id, decision_type, input_state_json,
                    triggered_reason, selected_action, why_json,
                    rejected_alternatives_json, expected_kpi_impact_json,
                    model_version, solver_version, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.decision_id,
                    entry.run_id,
                    entry.decision_type,
                    json.dumps(entry.input_state, ensure_ascii=False, sort_keys=True),
                    entry.triggered_reason,
                    entry.selected_action,
                    json.dumps(entry.why, ensure_ascii=False),
                    json.dumps(entry.rejected_alternatives, ensure_ascii=False),
                    json.dumps(entry.expected_kpi_impact, ensure_ascii=False, sort_keys=True),
                    entry.model_version,
                    entry.solver_version,
                    entry.timestamp,
                ),
            )
            conn.commit()

    def get_by_decision_id(self, decision_id: str) -> DecisionLedgerEntry | None:
        if self.db_path is None:
            return next((e for e in self.entries if e.decision_id == decision_id), None)

        with closing(get_db_connection(self.db_path)) as conn:
            row = conn.execute(
                "SELECT decision_id, run_id, decision_type, input_state_json, "
                "triggered_reason, selected_action, why_json, rejected_alternatives_json, "
                "expected_kpi_impact_json, model_version, solver_version, timestamp "
                "FROM decision_ledger WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_run_id(self, run_id: str) -> list[DecisionLedgerEntry]:
        if self.db_path is None:
            return [e for e in self.entries if e.run_id == run_id]

        with closing(get_db_connection(self.db_path)) as conn:
            return self.read_by_run_id(conn, run_id)

    @classmethod
    def read_by_run_id(cls, conn, run_id: str) -> list[DecisionLedgerEntry]:
        """Query an existing connection without creating tables or reopening the DB.

        Callers can resolve ACTIVE and read its ledger from the same SQLite
        snapshot even if the canonical database file is atomically replaced.
        A run without recorded decisions legitimately has an empty history.
        """
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_ledger'").fetchone():
            return []
        rows = conn.execute(
            "SELECT decision_id, run_id, decision_type, input_state_json, "
            "triggered_reason, selected_action, why_json, rejected_alternatives_json, "
            "expected_kpi_impact_json, model_version, solver_version, timestamp "
            "FROM decision_ledger WHERE run_id = ? ORDER BY timestamp, decision_id",
            (run_id,),
        ).fetchall()
        return [cls._from_row(row) for row in rows]

    def to_json(self) -> str:
        if self.db_path is None:
            entries = self.entries
        else:
            with closing(get_db_connection(self.db_path)) as conn:
                run_ids = [
                    row[0]
                    for row in conn.execute("SELECT DISTINCT run_id FROM decision_ledger ORDER BY run_id").fetchall()
                ]
            entries = [entry for run_id in run_ids for entry in self.get_by_run_id(run_id)]
        return json.dumps([e.to_dict() for e in entries], indent=2, ensure_ascii=False)
