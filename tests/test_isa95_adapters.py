"""Tests for ISA-95 Integration Adapter Contracts (Madde 17 compliance)."""

import pandas as pd

from src.integration.adapters import (
    MockERPAdapter,
    MockInventoryAdapter,
    MockMESAdapter,
    MockTelemetryAdapter,
)
from src.integration.interfaces import (
    ERPAdapterInterface,
    InventoryAdapterInterface,
    MachineTelemetryAdapterInterface,
    MESAdapterInterface,
)


def test_mock_erp_adapter_contract():
    erp = MockERPAdapter()
    assert isinstance(erp, ERPAdapterInterface)

    orders = erp.fetch_sales_orders()
    assert isinstance(orders, pd.DataFrame)
    assert not orders.empty
    assert "material_code" in orders.columns
    assert "quantity" in orders.columns

    bom = erp.fetch_bill_of_materials()
    assert isinstance(bom, pd.DataFrame)
    assert "parent_sku" in bom.columns

    routing = erp.fetch_routing_master()
    assert isinstance(routing, pd.DataFrame)
    assert "workcenter" in routing.columns


def test_mock_mes_adapter_contract():
    mes = MockMESAdapter()
    assert isinstance(mes, MESAdapterInterface)

    states = mes.get_machine_live_states()
    assert isinstance(states, dict)
    assert "M01" in states

    recorded = mes.record_execution_event("DOWNTIME_LOG", "M01", {"reason": "Hydraulic failure"})
    assert recorded is True
    assert len(mes.events_log) == 1


def test_mock_inventory_adapter_contract():
    wms = MockInventoryAdapter()
    assert isinstance(wms, InventoryAdapterInterface)

    on_hand = wms.get_on_hand_inventory()
    assert isinstance(on_hand, dict)
    assert on_hand["RM_STEEL_01"] > 0

    qc_hold = wms.get_qc_hold_stock()
    assert isinstance(qc_hold, dict)
    assert "RM_STEEL_02" in qc_hold


def test_mock_telemetry_adapter_contract():
    telemetry = MockTelemetryAdapter()
    assert isinstance(telemetry, MachineTelemetryAdapterInterface)

    power_m01 = telemetry.get_power_consumption_telemetry("M01")
    assert power_m01 > 0.0

    power_unknown = telemetry.get_power_consumption_telemetry("M99_UNKNOWN")
    assert power_unknown == 0.0
