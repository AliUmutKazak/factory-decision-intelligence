"""A future or duplicate disruption must not enter chronological replay."""

import json

import pytest

from scripts.probe_reschedule_event_trace import _load_events, probe


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
