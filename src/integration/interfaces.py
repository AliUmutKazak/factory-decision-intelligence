from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class ERPAdapterInterface(ABC):
    """Kurumsal Kaynak Planlama (ERP - SAP, IFS, Logo, Odoo) entegrasyon kontratı."""

    @abstractmethod
    def fetch_sales_orders(self, **kwargs: Any) -> pd.DataFrame:
        """Satış siparişlerini ve müşteri taleplerini çeker."""
        pass

    @abstractmethod
    def fetch_bill_of_materials(self, **kwargs: Any) -> pd.DataFrame:
        """Ürün ağacı (BOM) tanımlarını çeker."""
        pass

    @abstractmethod
    def fetch_routing_master(self, **kwargs: Any) -> pd.DataFrame:
        """Operasyon süreleri, iş merkezleri ve makine eşlemelerini çeker."""
        pass


class MESAdapterInterface(ABC):
    """Üretim Yürütme Sistemi (MES) entegrasyon kontratı."""

    @abstractmethod
    def get_machine_live_states(self) -> dict[str, str]:
        """Tüm tezgâhların son üretim durumunu ve üzerinde takılı ürünü döner."""
        pass

    @abstractmethod
    def record_execution_event(self, event_type: str, machine_id: str, payload: dict[str, Any]) -> bool:
        """Tezgâh arıza, duruş veya iş emri tamamlama olayını günlüğe kaydeder."""
        pass


class InventoryAdapterInterface(ABC):
    """Depo ve Envanter Yönetim Sistemi (WMS/ERP-MM) entegrasyon kontratı."""

    @abstractmethod
    def get_on_hand_inventory(self) -> dict[str, float]:
        """Kullanılabilir net fiziki stok miktarını döner."""
        pass

    @abstractmethod
    def get_qc_hold_stock(self) -> dict[str, float]:
        """Kalite kontrolde (karantinada) bekleyen kullanılamaz stokları döner."""
        pass


class MachineTelemetryAdapterInterface(ABC):
    """Endüstriyel IoT (SCADA/PLC) telemetri entegrasyon kontratı."""

    @abstractmethod
    def get_power_consumption_telemetry(self, machine_id: str) -> float:
        """Tezgâhın anlık kW güç tüketim değerini okur."""
        pass
