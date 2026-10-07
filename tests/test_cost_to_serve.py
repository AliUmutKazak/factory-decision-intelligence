import pandas as pd
import pytest

from src.economics.cost_to_serve import CostParameters, EconomicDecisionEngine


def test_economic_decision_engine_tmc_calculation():
    engine = EconomicDecisionEngine()

    sched_df = pd.DataFrame(
        [
            {
                "job_id": "ORD-1",
                "start_min": 0,
                "end_min": 120,
                "duration": 120,
                "setup_duration": 30,
                "is_overtime": 0,
            },
            {
                "job_id": "ORD-2",
                "start_min": 120,
                "end_min": 360,
                "duration": 240,
                "setup_duration": 30,
                "is_overtime": 1,
            },
        ]
    )

    orders_df = pd.DataFrame(
        [
            {"job_id": "ORD-1", "due_date_min": 200, "customer_class": "STANDARD", "quantity": 100},
            {"job_id": "ORD-2", "due_date_min": 300, "customer_class": "TIER_1", "quantity": 200},  # 60 dk gecikme
        ]
    )

    result = engine.compute_total_manufacturing_cost(
        schedule_df=sched_df,
        orders_df=orders_df,
        energy_kwh_total=500.0,
        carbon_emissions_ton=0.25,
        material_cost_total=1500.0,
        expedited_orders_count=1,
    )

    # TMC ve kalemlerin pozitif ve tutarlı olduğunu doğrula
    assert result.total_manufacturing_cost > 0.0
    assert result.material_cost == 1500.0
    assert result.labor_cost > 0.0
    assert result.setup_cost > 0.0
    assert result.energy_cost == round(500.0 * 0.18, 2)
    assert result.carbon_cost == round(0.25 * 50.0, 2)
    assert result.expedite_cost == 150.0
    assert result.tardiness_cost > 0.0  # ORD-2 gecikti
    assert len(result.cost_to_serve_by_order) == 2


def test_cost_to_serve_empty_schedule():
    engine = EconomicDecisionEngine()
    result = engine.compute_total_manufacturing_cost(schedule_df=pd.DataFrame())
    assert result.total_manufacturing_cost == 0.0
    assert result.cost_to_serve_by_order == []


def test_canonical_lots_do_not_join_historical_demand_or_repeat_routing_units():
    schedule = pd.DataFrame(
        [
            {
                "lot_id": "NORMAL",
                "product_id": "P01",
                "operation_seq": 1,
                "production_units": 10,
                "start_min": 480,
                "end_min": 540,
                "duration_min": 60,
                "setup_before_min": 30,
                "due_date_min": 550,
                "priority_weight": 2,
            },
            {
                "lot_id": "NORMAL",
                "product_id": "P01",
                "operation_seq": 2,
                "production_units": 10,
                "start_min": 540,
                "end_min": 600,
                "duration_min": 60,
                "setup_before_min": 0,
                "due_date_min": 550,
                "priority_weight": 2,
            },
            {
                "lot_id": "HOT",
                "product_id": "P01",
                "operation_seq": 1,
                "production_units": 25,
                "start_min": 600,
                "end_min": 660,
                "duration_min": 60,
                "setup_before_min": 0,
                "due_date_min": 750,
                "priority_weight": 5,
            },
            {
                "lot_id": "HOT",
                "product_id": "P01",
                "operation_seq": 2,
                "production_units": 25,
                "start_min": 660,
                "end_min": 720,
                "duration_min": 60,
                "setup_before_min": 0,
                "due_date_min": 750,
                "priority_weight": 5,
            },
        ]
    )
    orders = pd.DataFrame(
        [
            {"product_id": "P01", "order_qty": 900, "order_date": "2017-01-01"},
            {"product_id": "P01", "order_qty": 800, "order_date": "2017-01-02"},
        ]
    )
    result = EconomicDecisionEngine().compute_total_manufacturing_cost(schedule, orders)
    assert len(result.cost_to_serve_by_order) == 2
    assert result.labor_cost == 100.0
    assert result.setup_cost == 20.0
    assert result.overtime_cost == 10.0  # Only 30 minutes of setup before 08:00; premium only.
    assert result.tardiness_cost == 100.0
    assert result.inventory_holding_cost == 1.46  # 35 physical units, each held for two hours.
    assert result.total_manufacturing_cost == 231.46
    from src.scheduling.service_level import evaluate_schedule_service_level

    service = evaluate_schedule_service_level(schedule, orders)
    assert service["total_orders"] == 2
    assert service["late_quantity"] == 10
    assert service["weighted_tardiness"] == 100.0


def test_makespan_after_96_hours_does_not_imply_overtime():
    schedule = pd.DataFrame([{"job_id": "J", "start_min": 8000, "end_min": 8060, "duration_min": 60}])
    result = EconomicDecisionEngine().compute_total_manufacturing_cost(schedule)
    assert result.labor_cost == 25.0
    assert result.setup_cost == 0.0
    assert result.overtime_cost == 0.0
    assert result.inventory_holding_cost == 0.0


def test_ambiguous_dispatch_metadata_fails_instead_of_multiplying_costs():
    schedule = pd.DataFrame([{"job_id": "J", "start_min": 480, "end_min": 540, "duration_min": 60}])
    orders = pd.DataFrame([{"job_id": "J", "quantity": 10}, {"job_id": "J", "quantity": 20}])
    with pytest.raises(ValueError, match="Ambiguous"):
        EconomicDecisionEngine().compute_total_manufacturing_cost(schedule, orders)
