"""A future or duplicate disruption must not enter chronological replay."""

import hashlib
import json

import pytest

from scripts.probe_reschedule_event_trace import _load_events, probe
from src.contracts.schemas import RescheduleTriggerEvent
from src.scheduling.rescheduler import DynamicRescheduler


@pytest.mark.parametrize(
    "times,ids",
    [
        ([600, 500], ["first", "second"]),
        ([600, 600], ["first", "second"]),
        ([600, 700], ["same", "same"]),
    ],
)
def test_event_trace_rejects_ambiguous_sequence(tmp_path, times, ids):
    path = tmp_path / "events.json"
    path.write_text(
        json.dumps([{"event_id": event_id, "current_time_min": time} for time, event_id in zip(times, ids)]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="strictly increase|unique"):
        _load_events(path)


def test_wrong_reference_hash_rejected_before_database_is_opened(tmp_path):
    source = tmp_path / "factory.db"
    source.write_bytes(b"untouched sealed source")
    events = tmp_path / "events.json"
    events.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        probe(source, "0" * 64, "BASE", events)
    assert source.read_bytes() == b"untouched sealed source"


def test_dispatch_comparison_requires_full_solver(tmp_path):
    source = tmp_path / "factory.db"
    source.write_bytes(b"sealed fixture")
    events = tmp_path / "events.json"
    events.write_text("[]", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="full solver"):
        probe(source, digest, "BASE", events, dispatch_rule="EDD")


def test_production_rescheduler_rejects_partial_experimental_dispatch(tmp_path):
    db_path = tmp_path / "never-opened.db"
    engine = DynamicRescheduler(str(db_path))
    trigger = RescheduleTriggerEvent(event_id="LAB-GUARD", current_time_min=0)
    with pytest.raises(ValueError, match="Experimental dispatch"):
        engine.execute_reschedule(trigger, experimental_dispatch_rule="EDD")
    with pytest.raises(ValueError, match="Experimental dispatch"):
        engine.execute_reschedule(
            trigger.model_copy(update={"allow_local_repair": False}),
            experimental_dispatch_rule="UNKNOWN",
        )
    assert not db_path.exists()
