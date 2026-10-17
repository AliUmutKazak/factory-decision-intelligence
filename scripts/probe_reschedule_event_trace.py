"""Replay a chronological synthetic disruption trace through the published run path.

This is a single-policy, fixed-route laboratory rehearsal. Future events enter
only after the preceding version has been validated, sealed, and promoted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from time import perf_counter

from src.config import runtime_path_context
from src.contracts.schemas import RescheduleTriggerEvent
from src.scheduling.rescheduler import DynamicRescheduler


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_hash(path: Path) -> str:
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_events(path: Path) -> list[RescheduleTriggerEvent]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) < 2:
        raise ValueError("event trace needs at least two chronological events")
    events = [RescheduleTriggerEvent.model_validate(item) for item in data]
    times = [event.current_time_min for event in events]
    ids = [event.event_id for event in events]
    if times != sorted(set(times)) or len(ids) != len(set(ids)):
        raise ValueError("event times must strictly increase and event IDs must be unique")
    return events


def probe(reference_db: Path, expected_sha256: str, baseline_run_id: str, events_path: Path) -> dict:
    reference_db = reference_db.resolve()
    events_path = events_path.resolve()
    reference_hash = _sha256(reference_db)
    if reference_hash != expected_sha256.lower():
        raise ValueError("sealed reference database SHA-256 mismatch")
    events = _load_events(events_path)
    repo_root = Path(__file__).resolve().parents[1]
    code_files = (
        "scripts/probe_reschedule_event_trace.py",
        "src/scheduling/rescheduler.py",
        "src/scheduling/reschedule_candidate_audit.py",
        "src/scheduling/schedule_cpsat.py",
    )
    code_sha256 = {name: _code_hash(repo_root / name) for name in code_files}

    with tempfile.TemporaryDirectory(prefix="fdi-reschedule-trace-") as directory:
        root = Path(directory)
        db_path = root / "data" / "factory.db"
        db_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(f"{reference_db.as_uri()}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(db_path)) as target:
                source.backup(target)
                if target.execute("SELECT COUNT(*) FROM pipeline_runs WHERE status='ACTIVE'").fetchone()[0]:
                    raise ValueError("sealed reference already contains an ACTIVE run")
                updated = target.execute(
                    "UPDATE pipeline_runs SET status='ACTIVE' WHERE run_id=? AND status='COMPLETED'",
                    (baseline_run_id,),
                )
                if updated.rowcount != 1:
                    raise ValueError("expected exactly one completed baseline run")
                target.commit()

        attempts = []
        with runtime_path_context(
            base_dir=root,
            data_dir=db_path.parent,
            db_path=db_path,
            processed_dir=db_path.parent / "processed",
            reports_dir=root / "reports",
        ):
            engine = DynamicRescheduler(str(db_path))
            for index, event in enumerate(events, start=1):
                run_id = f"TRACE-{index:02d}"
                started = perf_counter()
                try:
                    _, schedule, metadata, stability, audit = engine.execute_reschedule(
                        event, new_run_id=run_id, persist_audit=True
                    )
                    with closing(sqlite3.connect(db_path)) as conn:
                        active = conn.execute("SELECT run_id FROM pipeline_runs WHERE status='ACTIVE'").fetchall()
                        if active != [(run_id,)]:
                            raise RuntimeError("published run is not the sole ACTIVE version")
                    attempts.append(
                        {
                            "event": event.model_dump(mode="json"),
                            "previous_run_id": audit.previous_run_id,
                            "published_run_id": run_id,
                            "accepted": True,
                            "solver_status": str(metadata.status.value),
                            "solver_metadata": metadata.model_dump(mode="json"),
                            "decision_tier": audit.decision_tier,
                            "local_repair_rejection": audit.repair_rejection_reason,
                            "task_count": len(schedule),
                            "stability": stability.model_dump(mode="json"),
                            "elapsed_seconds": round(perf_counter() - started, 4),
                        }
                    )
                except Exception as exc:
                    # Later events cannot be replayed from a rejected or failed version.
                    attempts.append(
                        {
                            "event": event.model_dump(mode="json"),
                            "attempted_run_id": run_id,
                            "accepted": False,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "elapsed_seconds": round(perf_counter() - started, 4),
                        }
                    )
                    break
            with closing(sqlite3.connect(db_path)) as conn:
                active = conn.execute("SELECT run_id FROM pipeline_runs WHERE status='ACTIVE'").fetchall()

    if _sha256(reference_db) != reference_hash:
        raise RuntimeError("sealed reference changed during trace replay")
    return {
        "experiment_type": "single-policy chronological synthetic reschedule trace",
        "source_db": str(reference_db),
        "source_db_sha256": reference_hash,
        "code_sha256": code_sha256,
        "events_path": str(events_path),
        "events_sha256": _sha256(events_path),
        "baseline_run_id": baseline_run_id,
        "attempts": attempts,
        "completed_all_events": len(attempts) == len(events) and all(row["accepted"] for row in attempts),
        "final_active_run_ids": [row[0] for row in active],
        "source_unchanged": True,
        "evidence_scope": "synthetic fixed-route local rehearsal; no factory actuals or service guarantee",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--baseline-run-id", required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.db, args.sha256, args.baseline_run_id, args.events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"completed_all_events": report["completed_all_events"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
