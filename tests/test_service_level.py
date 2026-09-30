import pandas as pd

from src.scheduling.service_level import evaluate_schedule_service_level


def test_service_level_all_on_time():
    # 2 iş, ikisi de termininden önce bitiyor
    sched_df = pd.DataFrame([
        {"job_id": "ORD-01", "machine_id": "M1", "start_min": 0, "end_min": 100, "duration": 100, "setup_duration": 0},
        {"job_id": "ORD-02", "machine_id": "M2", "start_min": 0, "end_min": 200, "duration": 200, "setup_duration": 0},
    ])
    orders_df = pd.DataFrame([
        {"job_id": "ORD-01", "due_date_min": 300, "customer_class": "TIER_1", "priority": 2, "quantity": 50},
        {"job_id": "ORD-02", "due_date_min": 400, "customer_class": "STANDARD", "priority": 1, "quantity": 100},
    ])

    kpis = evaluate_schedule_service_level(sched_df, orders_df)

    assert kpis["on_time_delivery_pct"] == 100.0
    assert kpis["late_orders"] == 0
    assert kpis["total_tardiness_min"] == 0.0
    assert kpis["weighted_tardiness"] == 0.0
    assert kpis["total_tardiness_cost"] == 0.0


def test_service_level_with_weighted_tardiness_and_tier_penalty():
    # ORD-01 gecikiyor (Bitiş: 500, Termin: 400 -> 100 dk gecikme), TIER_1 VIP müşteri
    # ORD-02 zamanında bitiyor
    sched_df = pd.DataFrame([
        {"job_id": "ORD-01", "machine_id": "M1", "start_min": 0, "end_min": 500, "duration": 500, "setup_duration": 20},
        {"job_id": "ORD-02", "machine_id": "M2", "start_min": 0, "end_min": 300, "duration": 300, "setup_duration": 10},
    ])
    orders_df = pd.DataFrame([
        {"job_id": "ORD-01", "due_date_min": 400, "customer_class": "TIER_1", "priority": 2, "quantity": 25},
        {"job_id": "ORD-02", "due_date_min": 400, "customer_class": "STANDARD", "priority": 1, "quantity": 50},
    ])

    kpis = evaluate_schedule_service_level(sched_df, orders_df, cost_per_tardy_min=2.0)

    assert kpis["total_orders"] == 2
    assert kpis["late_orders"] == 1
    assert kpis["on_time_delivery_pct"] == 50.0
    assert kpis["late_quantity"] == 25
    assert kpis["total_tardiness_min"] == 100.0
    # Ağırlık = Priority(2) * TIER_1(3.0) = 6.0. Weighted Tardiness = 100 * 6.0 = 600.0
    assert kpis["weighted_tardiness"] == 600.0
    # Ceza = 100 dk * 2.0 TL * 6.0 weight = 1200.0 TL
    assert kpis["total_tardiness_cost"] == 1200.0
