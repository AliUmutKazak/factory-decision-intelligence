"""Checks independent of the production scheduling model."""

from copy import deepcopy

import pytest

from src.scheduling.fjsp_reference import check_fjsp_schedule, parse_brandimarte_fjs

SMALL = """2 2 2
2 2 1 3 2 4 1 2 2
1 1 1 2
"""


def _valid_rows():
    return [
        {"job_id": 1, "operation_seq": 1, "machine_id": 1, "start": 0, "end": 3},
        {"job_id": 1, "operation_seq": 2, "machine_id": 2, "start": 3, "end": 5},
        {"job_id": 2, "operation_seq": 1, "machine_id": 1, "start": 3, "end": 5},
    ]


def test_plain_fjsp_accepts_hand_checked_schedule():
    instance = parse_brandimarte_fjs(SMALL)
    report = check_fjsp_schedule(instance, _valid_rows())
    assert (report["job_count"], report["machine_count"], report["operation_count"]) == (2, 2, 3)
    assert report["status"] == "ACCEPTED"
    assert report["makespan"] == 5


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda rows: rows[1].update(start=2, end=4), "PRECEDENCE_OVERLAP"),
        (lambda rows: rows[2].update(start=2, end=4), "MACHINE_OVERLAP"),
        (lambda rows: rows[2].update(machine_id=2), "INELIGIBLE_MACHINE"),
        (lambda rows: rows[0].update(end=4), "INVALID_DURATION"),
        (lambda rows: rows.pop(), "MISSING_OPERATION"),
        (lambda rows: rows.append(deepcopy(rows[0])), "DUPLICATE_OPERATION"),
    ],
)
def test_independent_checker_rejects_corrupt_schedules(change, expected):
    rows = _valid_rows()
    change(rows)
    report = check_fjsp_schedule(parse_brandimarte_fjs(SMALL), rows)
    assert report["status"] == "REJECTED"
    assert report["makespan"] is None
    assert expected in {issue["code"] for issue in report["issues"]}


def test_parser_rejects_ambiguous_or_incomplete_source():
    with pytest.raises(ValueError, match="job rows"):
        parse_brandimarte_fjs("2 2\n1 1 1 2")
    with pytest.raises(ValueError, match="invalid machine/duration"):
        parse_brandimarte_fjs("1 2\n1 2 1 3 1 4")
    with pytest.raises(ValueError, match="trailing tokens"):
        parse_brandimarte_fjs("1 2\n1 1 1 3 9")
