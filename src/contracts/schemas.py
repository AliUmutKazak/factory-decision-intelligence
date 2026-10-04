"""Madde 25: Runtime Input Validation & Data Contracts.

Optimizasyon ve karar motoru sınırlarına giren kritik veri akışları
(ERP, MES, Makine Olayları, Senaryo Talepleri) için Pydantic kontratları.
"""

from datetime import datetime
from enum import StrEnum
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


class CurrencyCode(StrEnum):
    EUR = "EUR"
    USD = "USD"
    TRY = "TRY"


class TimeUnit(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"


class EnergyUnit(StrEnum):
    KWH = "kWh"
    MWH = "MWh"


class MassUnit(StrEnum):
    KG = "kg"
    TON = "ton"


class EconomicConfigModel(BaseModel):
    """Pydantic v2 SSOT Ekonomik Parametreler Sözleşmesi."""

    currency: CurrencyCode = Field(default=CurrencyCode.EUR, description="Temel para birimi")
    currency_symbol: str = Field(default="€", description="Para birimi simgesi")

    labor_rate_per_hour: float = Field(default=25.0, gt=0, description="Standart saatlik işçilik maliyeti")
    overtime_multiplier: float = Field(default=1.5, ge=1.0, description="Fazla mesai çarpanı")
    setup_cost_per_hour: float = Field(default=40.0, ge=0, description="Hat hazırlık saatlik maliyeti")
    holding_cost_per_unit_per_day: float = Field(default=0.50, ge=0, description="Birim/gün stok tutma maliyeti")
    holding_cost_per_batch: float = Field(default=25.0, ge=0, description="Parti/hafta stok tutma maliyeti")
    backlog_penalty_per_batch: float = Field(default=1500.0, ge=0, description="Parti başına gecikme cezası")
    energy_price_per_kwh: float = Field(default=0.18, gt=0, description="Endüstriyel elektrik birim fiyatı")
    carbon_price_per_ton: float = Field(default=50.0, ge=0, description="Karbon vergisi referansı")
    expedite_cost_flat: float = Field(default=150.0, ge=0, description="Sabit hızlandırma maliyeti")
    tardiness_cost_per_hour: float = Field(default=60.0, ge=0, description="Termin gecikme cezası")

    @property
    def labor_standard_rate(self) -> float:
        return self.labor_rate_per_hour

    @property
    def labor_overtime_rate(self) -> float:
        return self.labor_rate_per_hour * self.overtime_multiplier

    @property
    def labor_cost_overtime_hr(self) -> float:
        return self.labor_overtime_rate

    @property
    def setup_rate(self) -> float:
        return self.setup_cost_per_hour

    @property
    def holding_rate(self) -> float:
        return self.holding_cost_per_unit_per_day

    @property
    def energy_rate(self) -> float:
        return self.energy_price_per_kwh

    @property
    def carbon_price(self) -> float:
        return self.carbon_price_per_ton

    @property
    def expedite_cost(self) -> float:
        return self.expedite_cost_flat

    @property
    def tardiness_cost(self) -> float:
        return self.tardiness_cost_per_hour

    @property
    def units(self) -> dict[str, str]:
        curr = self.currency.value if hasattr(self.currency, "value") else str(self.currency)
        return {
            "labor_standard_rate": f"{curr}/hour",
            "labor_overtime_rate": f"{curr}/hour",
            "setup_rate": f"{curr}/hour",
            "holding_rate": f"{curr}/unit/day",
            "holding_batch_rate": f"{curr}/lot/week",
            "backlog_rate": f"{curr}/batch",
            "energy_rate": f"{curr}/kWh",
            "carbon_price": f"{curr}/tCO2e",
            "expedite_cost": f"{curr}",
            "tardiness_cost": f"{curr}/hour",
        }


class InputLineageRecord(BaseModel):
    """Boru hattı girdi kaynağı soykütüğü sözleşmesi."""

    run_id: str = Field(description="İlişkili pipeline koşum kimliği")
    source_name: str = Field(description="Girdi kaynağının adı (örn: demand_input, bom, routing)")
    source_type: str = Field(description="Kaynak tipi (RAW_FILE, MASTER_DATA, CONFIG_FILE)")
    source_path: str = Field(description="Dosya yolu")
    sha256: str = Field(min_length=64, max_length=64, description="Dosyanın SHA-256 özeti")
    size_bytes: int = Field(ge=0, description="Dosya boyutu (bayt)")
    row_count: int | None = Field(default=None, description="Veri satır sayısı")


class RunManifestModel(BaseModel):
    """Koşum manifestosu ve tekrarlanabilirlik sözleşmesi."""

    run_id: str = Field(description="Pipeline run ID")
    created_at: str = Field(description="Manifest oluşturulma ISO zaman damgası")
    total_artifacts: int = Field(ge=0, description="İzlenen toplam çıktı artifact sayısı")
    artifacts: dict[str, Any] = Field(default_factory=dict, description="Çıktı dosyaları ve hash'leri")
    inputs: dict[str, Any] = Field(default_factory=dict, description="Girdi veri setleri, config ve ortam izleri")


class SolverStatus(StrEnum):
    """OR-Tools CP-SAT çözücü durum sözleşmesi."""

    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    MODEL_INVALID = "MODEL_INVALID"
    UNKNOWN = "UNKNOWN"


class ScheduleSolverMetadata(BaseModel):
    """Çizelgeleme çözücüsü yürütme ve determinizm meta veri sözleşmesi."""

    run_id: str = Field(description="İlişkili pipeline koşum kimliği")
    status: SolverStatus = Field(description="Çözücü nihai durum kodu")
    proven_optimal: bool = Field(description="Çözümün matematiksel olarak kanıtlanmış optimum olup olmadığı")
    wall_time_seconds: float = Field(ge=0.0, description="Çözücünün harcadığı toplam duvar saati süresi")
    objective_value: float | None = Field(default=None, description="Bulunan en iyi hedef fonksiyon değeri")
    best_objective_bound: float | None = Field(default=None, description="Matematiksel alt/üst sınır")
    random_seed: int = Field(default=42, description="Determinizm için kullanılan rastgele tohum")
    num_search_workers: int = Field(ge=1, description="Aramada kullanılan paralel iş parçacığı sayısı")
    time_limit_seconds: float = Field(gt=0.0, description="Çözücüye tanınan azami süre")


class ScenarioShockModel(BaseModel):
    """Senaryo şok ve parametre manipülasyon sözleşmesi."""

    name: str = Field(description="Senaryo adı (örn: BASELINE, DEMAND_SURGE, MACHINE_OUTAGE)")
    demand_multiplier: float = Field(default=1.0, ge=0.0, description="Talep ölçeklendirme çarpanı")
    capacity_multiplier: float = Field(default=1.0, ge=0.0, description="Kapasite kullanılabilirlik çarpanı")
    electricity_price_multiplier: float = Field(default=1.0, ge=0.0, description="Elektrik tarife çarpanı")
    carbon_tax_delta_eur: float = Field(default=0.0, description="Karbon vergisi değişimi (EUR/ton)")
    objective_policy: str = Field(default="BALANCED", description="Hedef fonksiyon optimizasyon politikası")
    failed_machines: list[str] = Field(default_factory=list, description="Arızalı kabul edilen makine listesi")
    material_delay_days: int = Field(default=0, ge=0, description="Tedarik gecikmesi (gün)")


class ScenarioResultModel(BaseModel):
    """Senaryo simülasyon çıktısı ve KPI sonuç sözleşmesi."""

    scenario: str = Field(description="Simüle edilen senaryo adı")
    makespan_hours: float = Field(ge=0.0, description="Toplam çizelge tamamlanma süresi (saat)")
    on_time_delivery_pct: float = Field(ge=0.0, le=100.0, description="Zamanında teslimat oranı (%)")
    inventory_holding_cost_eur: float = Field(ge=0.0, description="Stok elde tutma maliyeti (EUR)")
    backlog_units: int = Field(ge=0, description="Karşılanamayan gecikmiş sipariş miktarı (adet)")
    energy_cost_eur: float = Field(ge=0.0, description="Enerji tüketim maliyeti (EUR)")
    carbon_tco2e: float = Field(ge=0.0, description="Toplam karbon salımı (tCO2e)")
    carbon_cost_eur: float = Field(ge=0.0, description="Karbon vergisi/maliyeti (EUR)")
    total_cost_eur: float = Field(ge=0.0, description="Toplam ekonomik maliyet (EUR)")


class ScheduleTaskInput(BaseModel):
    """Tek bir üretim görevinin (operasyonunun) çizelgeleyici girdi sözleşmesi."""

    task_id: str = Field(description="Benzersiz görev tanımlayıcısı (örn: P01_OP10)")
    product_id: str = Field(description="Ürün kodu")
    machine_id: str = Field(description="Atanacağı makine kodu")
    duration_min: int = Field(gt=0, description="Operasyon işlem süresi (dakika, pozitif tam sayı)")
    due_date_min: int = Field(ge=0, description="Teslim tarihi (dakika)")
    weight: float = Field(default=1.0, ge=0.0, description="Gecikme ağırlık katsayısı")
    earliest_start_min: int = Field(default=0, ge=0, description="MRP malzeme hazır olma zamanı (dakika)")
    sequence_family: str | None = Field(default=None, description="Setup matrisi ürün ailesi/grubu")


class ScheduleInputPayload(BaseModel):
    """CP-SAT çözücüsüne beslenen doğrulanmış girdi veri kümesi."""

    tasks: list[ScheduleTaskInput] = Field(min_length=1, description="Çizelgelenecek en az bir görev olmalıdır")
    time_limit_seconds: float = Field(gt=0.0, description="Çözücü zaman limiti")
    random_seed: int = Field(ge=0, description="Determinizm çekirdeği")
