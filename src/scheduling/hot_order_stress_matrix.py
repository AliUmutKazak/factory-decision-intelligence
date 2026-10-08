"""Repeat labeled synthetic hot-order cases on one sealed G7 reference.

The matrix measures solver behavior and invokes the independent core audit.
It is laboratory evidence, not a factory service-level or fidelity claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.contracts.schemas import HotOrderInjection
from src.scheduling.hot_order_load_probe import probe_hot_order_replay
from src.utils.lineage import get_git_sha


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_hot_order_matrix(
    source_path: str | Path,
    baseline_run_id: str,
    *,
    expected_sha256: str,
    cases_path: str | Path,
    repeats: int = 3,
    scenario_limit_seconds: float = 2.0,
    dispatch_rule: str = "EDD",
) -> dict[str, Any]:
    """Run every declared case without modifying the reference database."""
    source = Path(source_path).resolve()
    cases_file = Path(cases_path).resolve()
    manifest_hash = _sha256(cases_file)
    manifest = json.loads(cases_file.read_text(encoding="utf-8"))
    if manifest.get("source_type") != "SYNTHETIC":
        raise ValueError("stress matrix requires an explicitly SYNTHETIC case manifest")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    if dispatch_rule not in {"FIFO", "EDD", "SPT", "Greedy"}:
        raise ValueError("dispatch_rule must be FIFO, EDD, SPT or Greedy")
    source_hash = _sha256(source)
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError(f"source DB SHA-256 mismatch: {source_hash}")

    seen_ids: set[str] = set()
    parsed_cases: list[tuple[str, HotOrderInjection]] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"].strip():
            raise ValueError("each case needs a nonempty case_id")
        case_id = case["case_id"]
        if case_id in seen_ids:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen_ids.add(case_id)
        order = HotOrderInjection.model_validate(case.get("hot_order"))
        parsed_cases.append((case_id, order))

    results: list[dict[str, Any]] = []
    for case_id, order in parsed_cases:
        report = probe_hot_order_replay(
            source,
            baseline_run_id,
            expected_sha256=expected_sha256,
            hot_order=order,
            repeats=repeats,
            scenario_limit_seconds=scenario_limit_seconds,
            reuse_active_baseline=True,
            scenario_dispatch_rule=dispatch_rule,
        )
        results.append({"case_id": case_id, "report": report})

    if _sha256(source) != source_hash:
        raise RuntimeError("sealed source DB changed during stress matrix")
    if _sha256(cases_file) != manifest_hash:
        raise RuntimeError("case manifest changed during stress matrix")
    accepted = sum(row["report"]["summary"]["scenario_accepted_count"] for row in results)
    attempts = len(results) * repeats
    return {
        "scope": "LAB_SYNTHETIC_HOT_ORDER_MATRIX_NO_FACTORY_VALIDATION_OR_SLO",
        "source_db_sha256": source_hash,
        "cases_manifest_sha256": manifest_hash,
        "cases_manifest_name": cases_file.name,
        "matrix_code_sha256": _sha256(Path(__file__).resolve()),
        "git_sha": get_git_sha(),
        "source_run_id": baseline_run_id,
        "dispatch_rule": dispatch_rule,
        "scenario_limit_seconds": scenario_limit_seconds,
        "repeats_per_case": repeats,
        "case_count": len(results),
        "attempt_count": attempts,
        "independently_accepted_count": accepted,
        "all_accepted": accepted == attempts,
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic G7 hot-order stress matrix")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--scenario-limit", type=float, default=2.0)
    parser.add_argument("--dispatch-rule", choices=("FIFO", "EDD", "SPT", "Greedy"), default="EDD")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = probe_hot_order_matrix(
        args.db,
        args.baseline_run_id,
        expected_sha256=args.expected_sha256,
        cases_path=args.cases,
        repeats=args.repeats,
        scenario_limit_seconds=args.scenario_limit,
        dispatch_rule=args.dispatch_rule,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["all_accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
