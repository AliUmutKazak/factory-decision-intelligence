"""Madde 25: Runtime Input Validation & Data Contracts.

Optimizasyon ve karar motoru sınırlarına giren kritik veri akışları
(ERP, MES, Makine Olayları, Senaryo Talepleri) için Pydantic kontratları.
"""

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class ProductionOrder(BaseModel):
    """ERP Sipariş Sözleşmesi."""

    order_id: str = Field(..., min_length=1, description="Benzersiz sipariş kodu")
    product_id: str = Field(..., min_length=1, description="Ürün kodu")
    quantity: float = Field(..., gt=0, description="Sipariş miktarı sıfırdan büyük olmalıdır")
    due_date: str | datetime = Field(..., description="Termin tarihi / dakikası")
    priority: int = Field(default=1, ge=1, le=5, description="Sipariş önceliği (1: Normal, 5: Kritik)")
    customer_tier: Literal["STANDARD", "PREMIUM", "VIP"] = Field(default="STANDARD", description="Müşteri segmenti")


class MESActual(BaseModel):
    """MES Gerçekleşen Üretim Kaydı Sözleşmesi."""

    lot_id: str = Field(..., min_length=1)
    machine_id: str = Field(..., min_length=1)
    operation_seq: int = Field(..., ge=1)
    actual_start_min: float = Field(..., ge=0)
    actual_end_min: float = Field(..., ge=0)
    produced_qty: float = Field(..., ge=0)
    scrap_qty: float = Field(default=0.0, ge=0)

    @field_validator("actual_end_min")
    @classmethod
    def validate_duration(cls, v: float, info: Any) -> float:
        start = info.data.get("actual_start_min")
        if start is not None and v < start:
            raise ValueError("Bitiş zamanı başlangıç zamanından önce olamaz.")
        return v


class MachineEvent(BaseModel):
    """Makine Olay / Arıza Bildirim Sözleşmesi."""

    machine_id: str = Field(..., min_length=1)
    event_type: Literal["BREAKDOWN", "MAINTENANCE", "TOOL_CHANGE", "SETUP"]
    start_time_min: float = Field(..., ge=0)
    duration_min: float = Field(..., gt=0)


class MaterialAvailability(BaseModel):
    """Hammadde / Malzeme Temin Sözleşmesi."""

    material_id: str = Field(..., min_length=1)
    available_date_min: float = Field(default=0.0, ge=0)
    quantity_available: float = Field(..., ge=0)


class ProductionScheduleTask(BaseModel):
    """Çizelge Görev Çıktı Sözleşmesi."""

    task_id: str = Field(..., min_length=1)
    lot_id: str = Field(..., min_length=1)
    product_id: str = Field(..., min_length=1)
    machine_id: str = Field(..., min_length=1)
    operation_seq: int = Field(..., ge=1)
    start_min: float = Field(..., ge=0)
    end_min: float = Field(..., ge=0)
    duration_min: float = Field(..., ge=0)

    @field_validator("end_min")
    @classmethod
    def validate_task_end(cls, v: float, info: Any) -> float:
        start = info.data.get("start_min")
        if start is not None and v < start:
            raise ValueError("Görev bitişi başlangıcından önce olamaz.")
        return v


class ScenarioRequest(BaseModel):
    """What-If Karar Destek Senaryo Talep Sözleşmesi."""

    name: str = Field(..., min_length=1)
    demand_multiplier: float = Field(default=1.0, gt=0)
    capacity_multiplier: float = Field(default=1.0, gt=0, le=2.0)
    electricity_price_multiplier: float = Field(default=1.0, ge=0)
    carbon_tax_delta_eur: float = Field(default=0.0)
    objective_policy: Literal["BALANCED", "ENERGY_MIN", "SERVICE_MAX", "COST_MIN"] = "BALANCED"
    failed_machines: list[str] = Field(default_factory=list)
    material_delay_days: int = Field(default=0, ge=0)


class ScheduleResult(BaseModel):
    """Çizelgeleme Motoru Çıktı Sözleşmesi."""

    status: Literal["OPTIMAL", "FEASIBLE", "INFEASIBLE", "MODEL_INVALID"]
    makespan_hours: float = Field(..., ge=0)
    total_cost_eur: float = Field(..., ge=0)
    tasks: list[ProductionScheduleTask] = Field(default_factory=list)
