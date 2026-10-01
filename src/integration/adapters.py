"""Synthetic / Mock Adapters for ERP and MES Integrations (Madde 17 & ISA-95).

Gerçek SAP/MES sistemlerine bağlanmak yerine, ISA-95 entegrasyon sınırlarını
belirleyen kontratların referans synthetic implementasyonlarını sağlar.
"""

from typing import Any

import pandas as pd

from src.integration.interfaces import (
    ERPAdapterInterface,
    InventoryAdapterInterface,
    MachineTelemetryAdapterInterface,
    MESAdapterInterface,
)
from src.utils.erp_service import ERPService


class MockERPAdapter(ERPAdapterInterface):
    """ISA-95 Level 4 Enterprise Boundary Mock (SAP S/4HANA / IFS benzeri)."""

    def fetch_sales_orders(self, **kwargs: Any) -> pd.DataFrame:
        """Sentetik satış siparişlerini ve müşteri taleplerini döner."""
        return pd.DataFrame(
            [
                {
                    "order_id": "SO-2026-001",
                    "material_code": ERPService.get_erp_code("SKU", "P01") or "MAT-10001",
                    "quantity": 500,
                    "delivery_week": 1,
                    "customer": "CUST-A",
                },
                {
                    "order_id": "SO-2026-002",
                    "material_code": ERPService.get_erp_code("SKU", "P02") or "MAT-10002",
                    "quantity": 300,
                    "delivery_week": 2,
                    "customer": "CUST-B",
                },
            ]
        )

    def fetch_bill_of_materials(self, **kwargs: Any) -> pd.DataFrame:
        """Sentetik ürün ağacı (BOM) hiyerarşisini döner."""
        return pd.DataFrame(
            [
                {
                    "parent_sku": "P01",
                    "component_id": "RM_STEEL_01",
                    "usage_rate": 1.5,
                },
                {
                    "parent_sku": "P02",
                    "component_id": "RM_STEEL_02",
                    "usage_rate": 2.0,
                },
            ]
        )

    def fetch_routing_master(self, **kwargs: Any) -> pd.DataFrame:
        """Sentetik iş planı (routing) ve makine standart sürelerini döner."""
        return pd.DataFrame(
            [
                {
                    "sku": "P01",
                    "op_seq": 10,
                    "workcenter": ERPService.get_erp_code("MACHINE", "M01") or "WC-CNC-5AX",
                    "setup_min": 30.0,
                    "run_time_min": 15.0,
                },
                {
                    "sku": "P02",
                    "op_seq": 10,
                    "workcenter": ERPService.get_erp_code("MACHINE", "M02") or "WC-CNC-3AX",
                    "setup_min": 45.0,
                    "run_time_min": 20.0,
                },
            ]
        )


class MockMESAdapter(MESAdapterInterface):
    """ISA-95 Level 3 Manufacturing Operations Management Mock (MES / SCADA)."""

    def __init__(self) -> None:
        self.events_log: list[dict[str, Any]] = []

    def get_machine_live_states(self) -> dict[str, str]:
        """Tüm tezgahların anlık operasyon durumunu döner."""
        return {
            "M01": "RUNNING",
            "M02": "IDLE",
            "M03": "RUNNING",
            "M04": "STANDBY",
        }

    def record_execution_event(self, event_type: str, machine_id: str, payload: dict[str, Any]) -> bool:
        """Saha olayını sentetik olay günlüğüne kaydeder."""
        self.events_log.append(
            {
                "event_type": event_type,
                "machine_id": machine_id,
                "payload": payload,
            }
        )
        return True


class MockInventoryAdapter(InventoryAdapterInterface):
    """ISA-95 Depo ve Stok Yönetimi (WMS / ERP-MM) Mock."""

    def get_on_hand_inventory(self) -> dict[str, float]:
        """Kullanılabilir net fiziki hammadde stoklarını döner."""
        return {
            "RM_STEEL_01": 2500.0,
            "RM_STEEL_02": 1800.0,
            "RM_ALU_01": 950.0,
        }

    def get_qc_hold_stock(self) -> dict[str, float]:
        """Kalite kontrolde (karantinada) bekleyen stokları döner."""
        return {
            "RM_STEEL_01": 150.0,
            "RM_STEEL_02": 0.0,
            "RM_ALU_01": 50.0,
        }


class MockTelemetryAdapter(MachineTelemetryAdapterInterface):
    """ISA-95 Level 2/1 IoT PLC / SCADA Telemetri Mock."""

    def get_power_consumption_telemetry(self, machine_id: str) -> float:
        """Tezgahın anlık kW güç tüketim telemetrisini simüle eder."""
        telemetry_map = {
            "M01": 42.5,
            "M02": 0.8,
            "M03": 38.0,
            "M04": 2.1,
        }
        return telemetry_map.get(machine_id, 0.0)
