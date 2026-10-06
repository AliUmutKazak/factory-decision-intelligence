"""Monetary manufacturing objective on the production constraint model.

Integer coefficients use micro currency units; rounded rate coefficients differ
from the analytic report by at most half a micro unit per charged minute/unit.
Material and processing costs are fixed for a fixed task set but remain included
in the objective and its decomposition. Setup, overtime, WIP, tardiness and idle
energy costs depend on the chosen schedule.
"""

from dataclasses import dataclass, field

from src.config import DEFAULT_FORKLIFT_LITERS, DIESEL_EMISSION_FACTOR, GRID_EMISSION_FACTOR


@dataclass
class MonetaryObjective:
    scale: int = 1_000_000
    terms: list = field(default_factory=list)
    constant_components: dict = field(default_factory=dict)

    def add(self, name, expression, rate):
        self.terms.append((name, expression, float(rate)))

    @property
    def expression(self):
        constant = round(sum(self.constant_components.values()) * self.scale)
        return constant + sum(round(rate * self.scale) * expression for _, expression, rate in self.terms)

    def breakdown(self, solver):
        result = dict(self.constant_components)
        for name, expression, rate in self.terms:
            result[name] = result.get(name, 0.0) + solver.Value(expression) * rate
        result["total"] = sum(result.values())
        return result


def _prefix_overlap(model, end, left, right, horizon, name):
    clipped = model.NewIntVar(-horizon, right - left, f"{name}_clip")
    overlap = model.NewIntVar(0, right - left, name)
    model.AddMinEquality(clipped, [end - left, right - left])
    model.AddMaxEquality(overlap, [0, clipped])
    return overlap


def build_monetary_objective(
    model,
    tasks,
    task_frame,
    machines,
    routing,
    bom,
    materials,
    mrp,
    makespan,
    horizon,
    machine_setup_terms,
    processing_ot_terms,
    setup_ot_terms,
    machine_daily_hours,
    machine_ot_hours,
    tardiness_terms,
    economic,
):
    objective = MonetaryObjective()
    total_duration = int(task_frame["duration"].sum())
    objective.constant_components["processing_labor"] = total_duration / 60 * economic.labor_rate_per_hour
    objective.add(
        "setup_labor", sum(sum(terms) for terms in machine_setup_terms.values()), economic.setup_cost_per_hour / 60
    )
    premium = economic.overtime_multiplier - 1
    objective.add("processing_overtime_premium", sum(processing_ot_terms), premium * economic.labor_rate_per_hour / 60)
    objective.add("setup_overtime_premium", sum(setup_ot_terms), premium * economic.setup_cost_per_hour / 60)
    objective.add("weighted_tardiness", sum(tardiness_terms), economic.tardiness_cost_per_hour / 60)

    material_rates = materials.set_index("material_id")["unit_cost"].to_dict()
    material_by_product = {}
    for row in bom.itertuples():
        if row.material_id not in material_rates:
            raise ValueError(f"Missing monetary material rate: {row.material_id}")
        material_by_product[row.product_id] = (
            material_by_product.get(row.product_id, 0.0) + row.qty_per_unit * material_rates[row.material_id]
        )
    material_cost = 0.0
    for lot, group in task_frame.groupby("lot_id"):
        ordered = group.sort_values("operation_seq")
        first, last = ordered.iloc[0], ordered.iloc[-1]
        if first.product_id not in material_by_product:
            raise ValueError(f"Missing monetary BOM: {first.product_id}")
        quantity = int(first.production_units)
        material_cost += quantity * material_by_product[first.product_id]
        wip = tasks[last.task_id]["end"] - tasks[first.task_id]["start"]
        objective.add("inventory_holding", wip, quantity * economic.holding_cost_per_unit_per_day / 1440)
    objective.constant_components["material"] = material_cost
    expedited = int(mrp["action_message"].astype(str).str.contains("EXPEDITE").sum()) if "action_message" in mrp else 0
    objective.constant_components["expedite"] = expedited * economic.expedite_cost_flat

    variable_rates = routing.set_index(["product_id", "operation_seq", "machine_id"])["variable_kwh_per_unit"].to_dict()
    process_kwh = 0.0
    specs = machines.set_index("machine_id")
    for row in task_frame.itertuples():
        machine = specs.loc[row.machine_id]
        key = (row.product_id, row.operation_seq, row.machine_id)
        if key not in variable_rates:
            raise ValueError(f"Missing operation energy rate: {key}")
        process_kwh += row.duration / 60 * float(machine.base_power_kw) + row.production_units * float(
            variable_rates[key]
        )
    energy_rate = economic.energy_price_per_kwh
    carbon_rate = GRID_EMISSION_FACTOR / 1000 * economic.carbon_price_per_ton
    objective.constant_components["processing_energy"] = process_kwh * energy_rate
    objective.constant_components["processing_carbon"] = process_kwh * carbon_rate
    objective.constant_components["scope_1_carbon"] = (
        DEFAULT_FORKLIFT_LITERS * DIESEL_EMISSION_FACTOR * economic.carbon_price_per_ton
    )
    for machine_id, machine in specs.iterrows():
        base = float(machine.base_power_kw)
        setup_kw = float(machine.get("setup_kw", round(base * 0.45, 2)))
        idle_kw = float(machine.get("idle_kw", round(base * 0.18, 2)))
        setup = sum(machine_setup_terms.get(machine_id, []))
        processed = int(task_frame.loc[task_frame.machine_id == machine_id, "duration"].sum())
        daily_hours = machine_daily_hours.get(machine_id, float(machine.max_daily_hours))
        night_length = int(round((24 - daily_hours) * 60))
        open_time = []
        for day in range(horizon // 1440 + 1):
            if day % 7 == 6:
                continue
            left = day * 1440 + night_length
            if left < horizon:
                open_time.append(
                    _prefix_overlap(
                        model,
                        makespan,
                        left,
                        min((day + 1) * 1440, horizon),
                        horizon,
                        f"cost_regular_{machine_id}_{day}",
                    )
                )
            if day < 6 and machine_ot_hours.get(machine_id, 0) > 0 and night_length > 0:
                open_time.append(
                    _prefix_overlap(
                        model,
                        makespan,
                        day * 1440,
                        min(day * 1440 + night_length, horizon),
                        horizon,
                        f"cost_night_{machine_id}_{day}",
                    )
                )
        idle = model.NewIntVar(0, horizon, f"cost_idle_{machine_id}")
        model.Add(idle == sum(open_time) - processed - setup)
        objective.add("setup_energy", setup, setup_kw / 60 * energy_rate)
        objective.add("idle_energy", idle, idle_kw / 60 * energy_rate)
        objective.add("setup_carbon", setup, setup_kw / 60 * carbon_rate)
        objective.add("idle_carbon", idle, idle_kw / 60 * carbon_rate)
    return objective
