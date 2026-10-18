"""Calendar closures and outages may overlap without making work infeasible."""

import pytest
from ortools.sat.python import cp_model

from src.scheduling.schedule_cpsat import _add_machine_availability_constraints


@pytest.mark.parametrize("optional_calendar", [False, True])
def test_overlapping_closures_block_work_but_not_each_other(optional_calendar):
    model = cp_model.CpModel()
    start = model.NewIntVar(90, 300, "start")
    end = model.NewIntVar(90, 320, "end")
    work = model.NewIntervalVar(start, 20, end, "work")
    if optional_calendar:
        closed = model.NewBoolVar("closed")
        model.Add(closed == 1)
        calendar = model.NewOptionalIntervalVar(100, 100, 200, closed, "night")
    else:
        calendar = model.NewFixedSizeIntervalVar(100, 100, "night")
    outage = model.NewFixedSizeIntervalVar(150, 100, "outage")
    overlapping_outage = model.NewFixedSizeIntervalVar(180, 50, "overlapping_outage")

    _add_machine_availability_constraints(model, [work], [calendar], [outage, overlapping_outage])
    model.Minimize(start)

    solver = cp_model.CpSolver()
    assert solver.Solve(model) == cp_model.OPTIMAL
    assert solver.Value(start) == 250
    assert solver.Value(end) == 270
