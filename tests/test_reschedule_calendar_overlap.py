"""A machine outage crossing a closed night is not an impossible plan."""

import hashlib
import io
import sqlite3
import warnings
from contextlib import closing, redirect_stdout
from pathlib import Path

from src.config import runtime_path_context
from src.contracts.schemas import RescheduleTriggerEvent, SolverStatus
from src.scheduling.rescheduler import DynamicRescheduler


def test_late_outage_crossing_closed_night_preserves_feasibility(tmp_path):
    source = Path(__file__).resolve().parents[1] / "artifacts/reference/factory.db"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert source_hash == "8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf"
    db_path = tmp_path / "data/factory.db"
    db_path.parent.mkdir()
    with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as source_conn:
        with closing(sqlite3.connect(db_path)) as target_conn:
            source_conn.backup(target_conn)
            updated = target_conn.execute(
                "UPDATE pipeline_runs SET status='ACTIVE' WHERE run_id=? AND status='COMPLETED'",
                ("RUN-20261006-00a0d3",),
            )
            assert updated.rowcount == 1
            target_conn.commit()

    trigger = RescheduleTriggerEvent(
        event_id="CALENDAR-OVERLAP-REGRESSION",
        current_time_min=5500,
        freeze_horizon_min=120,
        delay_machine_id="M02",
        delay_duration_min=90,
        allow_local_repair=False,
    )
    with runtime_path_context(
        base_dir=tmp_path,
        data_dir=db_path.parent,
        db_path=db_path,
        processed_dir=db_path.parent / "processed",
        reports_dir=tmp_path / "reports",
    ):
        with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
            warnings.filterwarnings(
                "ignore", message="pandas only supports SQLAlchemy connectable", category=UserWarning
            )
            _, schedule, metadata, _, _ = DynamicRescheduler(str(db_path)).execute_reschedule(
                trigger, new_run_id="CALENDAR-OVERLAP-REGRESSION"
            )

    assert metadata.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert len(schedule) == 31
    m02 = schedule.loc[schedule.machine_id == "M02"]
    for row in m02.itertuples():
        assert row.end_min <= 5716 or row.start_min - row.setup_before_min >= 5806
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT run_id FROM pipeline_runs WHERE status='ACTIVE'").fetchall() == [
            ("CALENDAR-OVERLAP-REGRESSION",)
        ]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
