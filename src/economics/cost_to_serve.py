"""
Total Manufacturing Cost (TMC) and Cost-to-Serve (CTS) Economic Decision Engine (Madde 34).
Farklı operasyonel maliyet kalemlerini (Holding, Backlog, Overtime, Setup, Energy, Carbon, Tardiness)
tek bir üretim ekonomisi amaç fonksiyonunda konsolide eder.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.config import ECONOMIC_CONFIG
from src.scheduling.analytics_schema import calendar_overtime_minutes, schedule_job_summary
from src.scheduling.service_level import CUSTOMER_CLASS_WEIGHTS


@dataclass
class CostParameters:
    """Birim maliyet katsayıları ve ekonomik parametreler (Economic SSOT uyumlu)."""

    labor_rate_per_hour: float = ECONOMIC_CONFIG.labor_rate_per_hour
    overtime_multiplier: float = ECONOMIC_CONFIG.overtime_multiplier
    setup_cost_per_hour: float = ECONOMIC_CONFIG.setup_cost_per_hour
    holding_cost_per_unit_per_day: float = ECONOMIC_CONFIG.holding_cost_per_unit_per_day
    energy_cost_per_kwh: float = ECONOMIC_CONFIG.energy_price_per_kwh
    carbon_cost_per_ton: float = ECONOMIC_CONFIG.carbon_price_per_ton
    expedite_cost_flat: float = ECONOMIC_CONFIG.expedite_cost_flat
    default_tardiness_cost_per_hour: float = ECONOMIC_CONFIG.tardiness_cost_per_hour
    currency: str = ECONOMIC_CONFIG.currency


@dataclass
class ManufacturingCostBreakdown:
    """TMC (Total Manufacturing Cost) Kalemleri."""

    material_cost: float = 0.0
    labor_cost: float = 0.0
    overtime_cost: float = 0.0
    setup_cost: float = 0.0
    inventory_holding_cost: float = 0.0
    expedite_cost: float = 0.0
    tardiness_cost: float = 0.0
    energy_cost: float = 0.0
    carbon_cost: float = 0.0
    total_manufacturing_cost: float = 0.0
    cost_to_serve_by_order: list[dict[str, Any]] = field(default_factory=list)


class EconomicDecisionEngine:
    """
    Üretim ve çizelgeleme çıktılarını konsolide eden ekonomik karar motoru.
    """

    def __init__(self, params: CostParameters | None = None):
        self.params = params or CostParameters()

    def compute_total_manufacturing_cost(
        self,
        schedule_df: pd.DataFrame,
        orders_df: pd.DataFrame | None = None,
        energy_kwh_total: float = 0.0,
        carbon_emissions_ton: float = 0.0,
        material_cost_total: float = 0.0,
        expedited_orders_count: int = 0,
    ) -> ManufacturingCostBreakdown:
        """
        Bütün operasyonel parametreleri tek bir Total Manufacturing Cost (TMC)
        ve sipariş bazlı Cost-to-Serve (CTS) yapısında hesaplar.
        """
        if schedule_df.empty:
            return ManufacturingCostBreakdown()

        df = schedule_df.copy()

        # 1. Setup & İşçilik Süreleri
        if "duration_min" in df.columns:
            run_duration_col = "duration_min"
        elif "duration" in df.columns:
            run_duration_col = "duration"
        else:
            run_duration_col = "run_duration"

        total_run_min = float(df[run_duration_col].sum()) if run_duration_col in df.columns else 0.0
        if "setup_before_min" in df.columns:
            total_setup_min = float(df["setup_before_min"].sum())
        elif "setup_duration" in df.columns:
            total_setup_min = float(df["setup_duration"].sum())
        else:
            total_setup_min = 0.0

        run_hours = total_run_min / 60.0
        setup_hours = total_setup_min / 60.0

        # Normal işçilik ve setup maliyeti
        base_labor_cost = run_hours * self.params.labor_rate_per_hour
        setup_cost = setup_hours * self.params.setup_cost_per_hour

        # Base processing/setup costs already include all worked minutes.
        # Overtime adds only the premium, separately for processing and setup.
        processing_ot = next((col for col in ("production_overtime_minutes", "overtime_minutes") if col in df), None)
        if processing_ot:
            overtime_min = float(df[processing_ot].sum())
        elif "is_overtime" in df:
            overtime_min = float(df.loc[df["is_overtime"] == 1, run_duration_col].sum())
        else:
            overtime_min = sum(calendar_overtime_minutes(row.start_min, row.end_min) for row in df.itertuples())
        if "setup_overtime_minutes" in df:
            setup_ot_min = float(df["setup_overtime_minutes"].sum())
        else:
            setup_ot_min = sum(
                calendar_overtime_minutes(
                    row["start_min"] - row.get("setup_before_min", row.get("setup_duration", 0)), row["start_min"]
                )
                for _, row in df.iterrows()
            )
        overtime_cost = (self.params.overtime_multiplier - 1.0) * (
            overtime_min / 60.0 * self.params.labor_rate_per_hour
            + setup_ot_min / 60.0 * self.params.setup_cost_per_hour
        )

        # 3. Enerji ve Karbon Maliyeti
        energy_cost = energy_kwh_total * self.params.energy_cost_per_kwh
        carbon_cost = carbon_emissions_ton * self.params.carbon_cost_per_ton

        # 4. Hızlandırma (Expedite) Maliyeti
        expedite_cost = expedited_orders_count * self.params.expedite_cost_flat

        # 5. Müşteri / Sipariş Bazlı Maliyet ve Gecikme (Tardiness & Holding)
        tardiness_cost_total = 0.0
        holding_cost_total = 0.0
        order_cost_list: list[dict[str, Any]] = []

        group_col, merged = schedule_job_summary(df, orders_df)

        # Eksik sütun varsayılanları
        if "due_date_min" not in merged.columns:
            merged["due_date_min"] = 7 * 24 * 60  # 1 hafta
        if "customer_class" not in merged.columns:
            merged["customer_class"] = "STANDARD"
        merged["due_date_min"] = merged["due_date_min"].fillna(7 * 24 * 60)
        merged["customer_class"] = merged["customer_class"].fillna("STANDARD")
        if "quantity" not in merged.columns:
            merged["quantity"] = 0.0

        for _, row in merged.iterrows():
            cid = row[group_col]
            comp_min = row["completion_min"]
            due_min = row["due_date_min"]
            qty = row["quantity"]

            # Tardiness
            tardy_min = max(0.0, comp_min - due_min)
            tardy_cost = (tardy_min / 60.0) * self.params.default_tardiness_cost_per_hour
            priority = row.get("priority", row.get("priority_weight", 1))
            tardy_cost *= priority * CUSTOMER_CLASS_WEIGHTS.get(row["customer_class"], 1.0)

            # Holding / Stokta bekleme süresi (gün)
            wip_days = (comp_min - row["start_min"]) / (24 * 60.0)
            holding_cost = qty * max(0.0, wip_days) * self.params.holding_cost_per_unit_per_day

            direct_labor = (row["job_run_min"] / 60.0) * self.params.labor_rate_per_hour
            direct_setup = (row["job_setup_min"] / 60.0) * self.params.setup_cost_per_hour

            cts_order = direct_labor + direct_setup + tardy_cost + holding_cost

            order_cost_list.append(
                {
                    group_col: cid,
                    "customer_class": row["customer_class"],
                    "direct_labor_cost": round(direct_labor, 2),
                    "direct_setup_cost": round(direct_setup, 2),
                    "tardiness_cost": round(tardy_cost, 2),
                    "inventory_holding_cost": round(holding_cost, 2),
                    "cost_to_serve": round(cts_order, 2),
                }
            )

            tardiness_cost_total += tardy_cost
            holding_cost_total += holding_cost

        # Toplam İmalat Maliyeti (TMC)
        tmc = (
            material_cost_total
            + base_labor_cost
            + overtime_cost
            + setup_cost
            + holding_cost_total
            + expedite_cost
            + tardiness_cost_total
            + energy_cost
            + carbon_cost
        )

        return ManufacturingCostBreakdown(
            material_cost=round(material_cost_total, 2),
            labor_cost=round(base_labor_cost, 2),
            overtime_cost=round(overtime_cost, 2),
            setup_cost=round(setup_cost, 2),
            inventory_holding_cost=round(holding_cost_total, 2),
            expedite_cost=round(expedite_cost, 2),
            tardiness_cost=round(tardiness_cost_total, 2),
            energy_cost=round(energy_cost, 2),
            carbon_cost=round(carbon_cost, 2),
            total_manufacturing_cost=round(tmc, 2),
            cost_to_serve_by_order=order_cost_list,
        )


@dataclass
class TDABCVarianceResult:
    order_id: str
    planned_runtime_hours: float
    actual_runtime_hours: float
    capacity_cost_rate_per_hour: float
    planned_cost: float
    actual_cost: float
    variance: float
    primary_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "planned_runtime_hours": round(self.planned_runtime_hours, 2),
            "actual_runtime_hours": round(self.actual_runtime_hours, 2),
            "planned_cost": round(self.planned_cost, 2),
            "actual_cost": round(self.actual_cost, 2),
            "variance": round(self.variance, 2),
            "primary_reason": self.primary_reason,
        }


# EconomicDecisionEngine sınıfı içerisine eklenecek metot:
def compute_tdabc_variance(
    order_id: str,
    planned_runtime_hours: float,
    actual_runtime_hours: float,
    capacity_cost_rate_per_hour: float,
    downtime_hours: float = 0.0,
) -> TDABCVarianceResult:
    """Time-Driven Activity-Based Costing (TDABC) runtime variance calculator (Madde 33)."""
    planned_cost = planned_runtime_hours * capacity_cost_rate_per_hour
    actual_cost = actual_runtime_hours * capacity_cost_rate_per_hour
    variance = actual_cost - planned_cost

    if variance > 0.01:
        if downtime_hours > 0.0:
            primary_reason = f"downtime ({round(downtime_hours, 2)} hrs)"
        else:
            primary_reason = "speed_loss / micro_stops"
    elif variance < -0.01:
        primary_reason = "efficiency_gain"
    else:
        primary_reason = "on_target"

    return TDABCVarianceResult(
        order_id=order_id,
        planned_runtime_hours=planned_runtime_hours,
        actual_runtime_hours=actual_runtime_hours,
        capacity_cost_rate_per_hour=capacity_cost_rate_per_hour,
        planned_cost=planned_cost,
        actual_cost=actual_cost,
        variance=variance,
        primary_reason=primary_reason,
    )
