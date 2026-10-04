"""Madde 25: Data Contracts & Runtime Validation Test Suite.

Sistem sınırlarında (ERP, MES, Makine Olayları, Senaryo Talepleri)
Pydantic v2 sözleşmelerinin doğru çalıştığını ve geçersiz verilerin
çözücüye/motora ulaşmadan reddedildiğini doğrular.
"""

import pytest
from pydantic import ValidationError

from src.contracts.schemas import (
    MachineEvent,
    MaterialAvailability,
    MESActual,
    ProductionOrder,
    ProductionScheduleTask,
    ScenarioRequest,
    ScheduleResult,
)


def test_production_order_contract_valid():
    """Geçerli bir ERP siparişi sözleşmeyi başarıyla geçmeli."""
    order = ProductionOrder(
        order_id="ORD-101",
        product_id="PROD_A",
        quantity=50.0,
        due_date="2026-06-01T12:00:00",
        priority=3,
        customer_tier="PREMIUM",
    )
    assert order.order_id == "ORD-101"
    assert order.quantity == 50.0
    assert order.customer_tier == "PREMIUM"


def test_production_order_rejects_non_positive_quantity():
    """Sipariş miktarı sıfır veya negatif olduğunda sözleşme ValidationError fırlatmalı."""
    with pytest.raises(ValidationError):
        ProductionOrder(
            order_id="ORD-102",
            product_id="PROD_A",
            quantity=0.0,  # gt=0 kuralı ihlali
            due_date="2026-06-01",
        )

    with pytest.raises(ValidationError):
        ProductionOrder(
            order_id="ORD-103",
            product_id="PROD_A",
            quantity=-10.0,
            due_date="2026-06-01",
        )


def test_production_order_rejects_invalid_priority():
    """Öncelik 1-5 aralığı dışında olduğunda reddedilmeli."""
    with pytest.raises(ValidationError):
        ProductionOrder(
            order_id="ORD-104",
            product_id="PROD_A",
            quantity=10.0,
            due_date="2026-06-01",
            priority=10,  # ge=1, le=5 kuralı ihlali
        )


def test_mes_actual_duration_validation():
    """MES kaydında bitiş başlangıçtan önce olamaz."""
    # Geçerli
    mes = MESActual(
        lot_id="LOT-01",
        machine_id="M01",
        operation_seq=1,
        actual_start_min=10.0,
        actual_end_min=50.0,
        produced_qty=20.0,
    )
    assert mes.produced_qty == 20.0

    # Geçersiz (actual_end_min < actual_start_min)
    with pytest.raises(ValidationError):
        MESActual(
            lot_id="LOT-01",
            machine_id="M01",
            operation_seq=1,
            actual_start_min=100.0,
            actual_end_min=50.0,
            produced_qty=20.0,
        )


def test_machine_event_type_restriction():
    """Makine olayları yalnızca tanımlı literal tipleri kabul etmeli."""
    event = MachineEvent(
        machine_id="M02",
        event_type="BREAKDOWN",
        start_time_min=60.0,
        duration_min=45.0,
    )
    assert event.event_type == "BREAKDOWN"

    with pytest.raises(ValidationError):
        MachineEvent(
            machine_id="M02",
            event_type="RANDOM_EVENT",  # Tanımsız tip
            start_time_min=60.0,
            duration_min=45.0,
        )


def test_scenario_request_policy_and_bounds():
    """Senaryo talebinde politikalar ve çarpan sınırları kontrol edilmeli."""
    req = ScenarioRequest(
        name="+20% DEMAND",
        demand_multiplier=1.2,
        objective_policy="BALANCED",
    )
    assert req.demand_multiplier == 1.2

    with pytest.raises(ValidationError):
        ScenarioRequest(
            name="INVALID",
            capacity_multiplier=-0.5,  # gt=0 kuralı ihlali
        )


def test_schedule_result_contract():
    """Çizelge çıktısı sözleşmesi geçerli durumları ve görev listesini doğrulamalı."""
    task = ProductionScheduleTask(
        task_id="T01",
        lot_id="L01",
        product_id="P01",
        machine_id="M01",
        operation_seq=1,
        start_min=0.0,
        end_min=60.0,
        duration_min=60.0,
    )
    result = ScheduleResult(
        status="OPTIMAL",
        makespan_hours=1.0,
        total_cost_eur=150.0,
        tasks=[task],
    )
    assert result.status == "OPTIMAL"
    assert len(result.tasks) == 1
