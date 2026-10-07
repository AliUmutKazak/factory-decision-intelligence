"""Parameterized ROI from measured, comparable schedule costs, not customer ROI."""

import math


def modeled_roi(
    baseline_cost, candidate_cost, *, cycles_per_year, realization_fraction, implementation_cost, annual_operating_cost
):
    values = (
        baseline_cost,
        candidate_cost,
        cycles_per_year,
        realization_fraction,
        implementation_cost,
        annual_operating_cost,
    )
    if (
        any(not math.isfinite(value) or value < 0 for value in values)
        or realization_fraction > 1
        or cycles_per_year == 0
    ):
        raise ValueError("ROI inputs must be finite, nonnegative; cycles positive and realization within [0,1].")
    saving = baseline_cost - candidate_cost
    gross = saving * cycles_per_year * realization_fraction
    annual_net = gross - annual_operating_cost
    investment = implementation_cost + annual_operating_cost
    return {
        "modeled_saving_per_cycle": saving,
        "modeled_annual_gross_benefit": gross,
        "annual_net_benefit": annual_net,
        "first_year_net_benefit": annual_net - implementation_cost,
        "first_year_roi_pct": (annual_net - implementation_cost) / investment * 100 if investment > 0 else None,
        "payback_months": implementation_cost / annual_net * 12 if annual_net > 0 else None,
        "assumptions": {
            "cycles_per_year": cycles_per_year,
            "realization_fraction": realization_fraction,
            "implementation_cost": implementation_cost,
            "annual_operating_cost": annual_operating_cost,
        },
        "evidence_type": "modeled projection; not an observed customer cash-flow or pilot result",
    }
