"""Independent checks for the plain static Brandimarte FJSP subset.

This module does not import the production solver or its constraint builders.
Times and durations are integer benchmark units, not factory calendar minutes.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FjspInstance:
    machine_count: int
    jobs: tuple[tuple[tuple[tuple[int, int], ...], ...], ...]

    @property
    def operation_count(self) -> int:
        return sum(len(job) for job in self.jobs)


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer >= {minimum}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be an integer >= {minimum}") from exc
    if not math.isfinite(number) or not number.is_integer() or number < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return int(number)


def parse_brandimarte_fjs(text: str) -> FjspInstance:
    """Parse one plain FJSP instance; machine/job/operation IDs are 1-based."""
    lines = [line.split() for line in text.splitlines() if line.strip()]
    if not lines or len(lines[0]) not in (2, 3):
        raise ValueError("FJSP header must contain job and machine counts")
    job_count = _integer(lines[0][0], "job_count", minimum=1)
    machine_count = _integer(lines[0][1], "machine_count", minimum=1)
    if len(lines) != job_count + 1:
        raise ValueError(f"expected {job_count} job rows, found {len(lines) - 1}")
    jobs = []
    for job_id, tokens in enumerate(lines[1:], start=1):
        values = [_integer(value, f"job {job_id} token", minimum=0) for value in tokens]
        operation_count = values[0] if values else 0
        if operation_count <= 0:
            raise ValueError(f"job {job_id} must have operations")
        cursor = 1
        operations = []
        for operation_seq in range(1, operation_count + 1):
            if cursor >= len(values):
                raise ValueError(f"job {job_id} operation {operation_seq} is incomplete")
            alternative_count = values[cursor]
            cursor += 1
            if alternative_count <= 0 or cursor + 2 * alternative_count > len(values):
                raise ValueError(f"job {job_id} operation {operation_seq} has invalid alternatives")
            alternatives = []
            seen = set()
            for _ in range(alternative_count):
                machine, duration = values[cursor : cursor + 2]
                cursor += 2
                if not 1 <= machine <= machine_count or duration <= 0 or machine in seen:
                    raise ValueError(f"job {job_id} operation {operation_seq} has invalid machine/duration")
                seen.add(machine)
                alternatives.append((machine, duration))
            operations.append(tuple(alternatives))
        if cursor != len(values):
            raise ValueError(f"job {job_id} contains trailing tokens")
        jobs.append(tuple(operations))
    return FjspInstance(machine_count=machine_count, jobs=tuple(jobs))


def check_fjsp_schedule(instance: FjspInstance, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Check assignment, duration, precedence and machine capacity without CP-SAT."""
    issues: list[dict[str, Any]] = []
    tasks: dict[tuple[int, int], tuple[int, int, int]] = {}
    for row_number, row in enumerate(rows, start=1):
        try:
            job_id = _integer(row.get("job_id"), "job_id", minimum=1)
            operation_seq = _integer(row.get("operation_seq"), "operation_seq", minimum=1)
            machine_id = _integer(row.get("machine_id"), "machine_id", minimum=1)
            start = _integer(row.get("start"), "start")
            end = _integer(row.get("end"), "end")
        except ValueError as exc:
            issues.append({"row": row_number, "code": "INVALID_ROW", "detail": str(exc)})
            continue
        key = (job_id, operation_seq)
        if not 1 <= job_id <= len(instance.jobs) or not 1 <= operation_seq <= len(instance.jobs[job_id - 1]):
            issues.append({"row": row_number, "code": "UNKNOWN_OPERATION", "detail": str(key)})
            continue
        if key in tasks:
            issues.append({"row": row_number, "code": "DUPLICATE_OPERATION", "detail": str(key)})
            continue
        alternatives = dict(instance.jobs[job_id - 1][operation_seq - 1])
        if machine_id not in alternatives:
            issues.append({"row": row_number, "code": "INELIGIBLE_MACHINE", "detail": str(key)})
        if end <= start or (machine_id in alternatives and end - start != alternatives[machine_id]):
            issues.append({"row": row_number, "code": "INVALID_DURATION", "detail": str(key)})
        tasks[key] = (machine_id, start, end)

    expected = {
        (job_id, operation_seq)
        for job_id, job in enumerate(instance.jobs, start=1)
        for operation_seq in range(1, len(job) + 1)
    }
    for key in sorted(expected - tasks.keys()):
        issues.append({"row": None, "code": "MISSING_OPERATION", "detail": str(key)})
    for job_id, job in enumerate(instance.jobs, start=1):
        for operation_seq in range(2, len(job) + 1):
            previous, current = tasks.get((job_id, operation_seq - 1)), tasks.get((job_id, operation_seq))
            if previous and current and current[1] < previous[2]:
                issues.append({"row": None, "code": "PRECEDENCE_OVERLAP", "detail": str((job_id, operation_seq))})
    by_machine: dict[int, list[tuple[int, int, tuple[int, int]]]] = {}
    for key, (machine, start, end) in tasks.items():
        by_machine.setdefault(machine, []).append((start, end, key))
    for machine, intervals in by_machine.items():
        intervals.sort()
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                issues.append(
                    {"row": None, "code": "MACHINE_OVERLAP", "detail": str((machine, previous[2], current[2]))}
                )
    return {
        "status": "ACCEPTED" if not issues else "REJECTED",
        "job_count": len(instance.jobs),
        "machine_count": instance.machine_count,
        "operation_count": instance.operation_count,
        "makespan": max((end for _, _, end in tasks.values()), default=None) if not issues else None,
        "issues": issues,
        "scope": "STATIC_FJSP_ASSIGNMENT_DURATION_PRECEDENCE_MACHINE_CAPACITY_ONLY",
    }
