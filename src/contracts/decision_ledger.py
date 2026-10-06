"""Decision Ledger (Madde 34).

Enterprise decision audit trail capturing the 'why' behind scheduling,
capacity, and re-sequencing actions to support explainable AI (Agentic Copilot).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class DecisionLedgerEntry:
    decision_id: str
    run_id: str
    decision_type: str  # e.g., 'RE_SEQUENCE', 'CAPACITY_OVERTIME', 'MAINTENANCE_BUFFER'
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
        """LLM ve son kullanıcı için doğal dilde açıklama metni üretir."""
        lines = [
            f"Decision: {self.decision_id} ({self.decision_type})",
            f"Trigger: {self.triggered_reason}",
            f"Action: {self.selected_action}",
            "Why:",
        ]
        for reason in self.why:
            lines.append(f"  - {reason}")
        if self.rejected_alternatives:
            lines.append("Rejected Alternatives:")
            for alt in self.rejected_alternatives:
                lines.append(f"  - {alt}")
        lines.append(f"Expected KPI Impact: {self.expected_kpi_impact}")
        lines.append(f"Solver: {self.solver_version} | Run: {self.run_id}")
        return "\n".join(lines)


class DecisionLedger:
    """Kurumsal karar izleme ve denetim yöneticisi."""

    def __init__(self) -> None:
        self.entries: list[DecisionLedgerEntry] = []

    def record(self, entry: DecisionLedgerEntry) -> None:
        self.entries.append(entry)

    def get_by_decision_id(self, decision_id: str) -> DecisionLedgerEntry | None:
        for entry in self.entries:
            if entry.decision_id == decision_id:
                return entry
        return None

    def get_by_run_id(self, run_id: str) -> list[DecisionLedgerEntry]:
        return [e for e in self.entries if e.run_id == run_id]

    def to_json(self) -> str:
        return json.dumps([e.to_dict() for e in self.entries], indent=2)
