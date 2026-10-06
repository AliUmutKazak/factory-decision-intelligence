"""Exact analytic schedule economics shared by benchmarks and acceptance tests."""

from dataclasses import asdict

import pandas as pd

from src.config import DEFAULT_FORKLIFT_LITERS, DIESEL_EMISSION_FACTOR, ECONOMIC_CONFIG, GRID_EMISSION_FACTOR
from src.economics.cost_to_serve import CostParameters, EconomicDecisionEngine
from src.scheduling.calendar_service import MachineCalendarService


def evaluate_schedule_cost(conn, schedule, run_id, economic=None):
    rates = economic or ECONOMIC_CONFIG
    if schedule.empty:
        return {"currency": str(rates.currency), "energy_kwh": 0.0, "total_manufacturing_cost": 0.0}
    machines = pd.read_sql("SELECT * FROM machines", conn).set_index("machine_id")
    routing = pd.read_sql("SELECT * FROM routing", conn)
    variable_rates = routing.set_index(["product_id", "operation_seq", "machine_id"])["variable_kwh_per_unit"]
    hours = MachineCalendarService.load_daily_hours(conn)
    ot = dict(
        conn.execute(
            "SELECT machine_id, overtime_hours FROM machine_capacity_plan WHERE run_id = ? AND period_week = 1",
            (run_id,),
        )
    )
    energy = 0.0
    for machine_id, spec in machines.iterrows():
        jobs = schedule[schedule.machine_id == machine_id]
        setup_min = float(jobs.setup_before_min.sum())
        processing_min = float(jobs.duration_min.sum())
        opened = MachineCalendarService.open_minutes(
            0, float(schedule.end_min.max()), hours[machine_id], ot.get(machine_id, 0) > 0
        )
        idle_min = opened - processing_min - setup_min
        if idle_min < -0.00001:
            raise ValueError("Schedule work exceeds its open calendar.")
        for job in jobs.itertuples():
            energy += (
                job.duration_min / 60 * spec.base_power_kw
                + job.production_units * variable_rates.loc[(job.product_id, job.operation_seq, machine_id)]
            )
        energy += setup_min / 60 * spec.get("setup_kw", round(spec.base_power_kw * 0.45, 2))
        energy += max(0, idle_min) / 60 * spec.get("idle_kw", round(spec.base_power_kw * 0.18, 2))
    bom = pd.read_sql("SELECT * FROM bom", conn)
    materials = pd.read_sql("SELECT * FROM materials", conn).set_index("material_id").unit_cost
    product_cost = {}
    for row in bom.itertuples():
        product_cost[row.product_id] = (
            product_cost.get(row.product_id, 0) + row.qty_per_unit * materials.loc[row.material_id]
        )
    first_operations = schedule.sort_values("operation_seq").groupby("lot_id").first()
    material = sum(row.production_units * product_cost[row.product_id] for row in first_operations.itertuples())
    mrp = pd.read_sql("SELECT * FROM mrp_plan WHERE run_id = ? AND period_week = 1", conn, params=(run_id,))
    expedited = int(mrp.action_message.astype(str).str.contains("EXPEDITE").sum()) if "action_message" in mrp else 0
    params = CostParameters(
        labor_rate_per_hour=rates.labor_rate_per_hour,
        overtime_multiplier=rates.overtime_multiplier,
        setup_cost_per_hour=rates.setup_cost_per_hour,
        holding_cost_per_unit_per_day=rates.holding_cost_per_unit_per_day,
        energy_cost_per_kwh=rates.energy_price_per_kwh,
        carbon_cost_per_ton=rates.carbon_price_per_ton,
        expedite_cost_flat=rates.expedite_cost_flat,
        default_tardiness_cost_per_hour=rates.tardiness_cost_per_hour,
        currency=str(rates.currency),
    )
    cost = EconomicDecisionEngine(params).compute_total_manufacturing_cost(
        schedule,
        energy_kwh_total=energy,
        carbon_emissions_ton=energy * GRID_EMISSION_FACTOR / 1000 + DEFAULT_FORKLIFT_LITERS * DIESEL_EMISSION_FACTOR,
        material_cost_total=material,
        expedited_orders_count=expedited,
    )
    return {"currency": str(rates.currency), "energy_kwh": energy, **asdict(cost)}
