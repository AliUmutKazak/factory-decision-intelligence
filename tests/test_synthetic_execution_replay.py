"""Hand-checkable G6-T execution semantics and fail-closed cases."""

import copy
import json
from pathlib import Path

from src.execution.synthetic_replay import replay_execution, replay_file

CASE = Path("examples/g6-partial-interruption.json")


def case():
    return json.loads(CASE.read_text(encoding="utf-8"))


def test_partial_interruption_and_final_quantity_conservation():
    example = case()
    interrupted = replay_execution({**example, "events": example["events"][:3]})
    assert interrupted["status"] == "ACCEPTED"
    assert interrupted["final_state"] == "INTERRUPTED"
    assert interrupted["remaining_units"] == 6
    assert interrupted["trace"][-1]["frozen"] is True

    completed = replay_file(CASE)
    assert completed["status"] == "ACCEPTED"
    assert (completed["good_units"], completed["scrap_units"], completed["remaining_units"]) == (9, 1, 0)
    assert completed["final_state"] == "COMPLETED"
    assert completed["trace"][-1]["frozen"] is False
    assert len(completed["input_sha256"]) == 64
    assert len(completed["implementation_sha256"]) == 64


def test_exact_replay_is_idempotent_but_conflicting_duplicate_is_rejected():
    example = case()
    example["events"].insert(2, copy.deepcopy(example["events"][1]))
    accepted = replay_execution(example)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["duplicate_events_ignored"] == 1
    assert accepted["good_units"] == 9

    example["events"][2]["quantity"] = 5
    rejected = replay_execution(example)
    assert rejected["issue"]["code"] == "conflicting_duplicate"

    example["events"][1]["quantity"] = 1
    example["events"][2]["quantity"] = True  # True == 1 in Python, but is not an identical event.
    assert replay_execution(example)["issue"]["code"] == "conflicting_duplicate"


def test_invalid_transitions_and_incomplete_completion_are_rejected():
    example = case()
    example["events"] = [example["events"][3]]
    assert replay_execution(example)["issue"]["code"] == "invalid_transition"

    example = case()
    example["events"] = [example["events"][0], example["events"][-1]]
    assert replay_execution(example)["issue"]["code"] == "incomplete_quantity"

    example = case()
    example["events"].insert(3, {"event_id": "bad", "type": "PRODUCE", "occurred_min": 75, "quantity": 1})
    assert replay_execution(example)["issue"]["code"] == "invalid_transition"


def test_overproduction_time_regression_and_unsupported_rework_are_rejected():
    example = case()
    example["events"][4]["quantity"] = 7
    assert replay_execution(example)["issue"]["code"] == "quantity_exceeds_plan"

    example = case()
    example["events"][1]["occurred_min"] = 59
    assert replay_execution(example)["issue"]["code"] == "invalid_event_time"

    example = case()
    example["events"][1]["type"] = "REWORK"
    assert replay_execution(example)["issue"]["code"] == "unsupported_event"


def test_bad_scalar_types_are_rejected_without_crashing():
    example = case()
    example["events"][1]["quantity"] = True
    assert replay_execution(example)["issue"]["code"] == "invalid_quantity"
    example["events"][1]["type"] = ["PRODUCE"]
    assert replay_execution(example)["issue"]["code"] == "unsupported_event"
