import pandas as pd

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
