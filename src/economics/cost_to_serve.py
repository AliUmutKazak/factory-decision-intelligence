"""
Total Manufacturing Cost (TMC) and Cost-to-Serve (CTS) Economic Decision Engine (Madde 34).
Farklı operasyonel maliyet kalemlerini (Holding, Backlog, Overtime, Setup, Energy, Carbon, Tardiness)
tek bir üretim ekonomisi amaç fonksiyonunda konsolide eder.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class CostParameters:
    """Birim maliyet katsayıları ve ekonomik parametreler."""
    labor_rate_per_hour: float = 25.0
    overtime_multiplier: float = 1.5
    setup_cost_per_hour: float = 40.0
    holding_cost_per_unit_per_day: float = 0.50
    energy_cost_per_kwh: float = 0.18
    carbon_cost_per_ton: float = 50.0  # Emisyon ticaret sistemi (ETS) referansı
    expedite_cost_flat: float = 150.0  # Hızlandırılmış nakliye/işleme sabit maliyeti
    default_tardiness_cost_per_hour: float = 60.0


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
        run_duration_col = "duration" if "duration" in df.columns else "run_duration"
        total_run_min = float(df[run_duration_col].sum()) if run_duration_col in df.columns else 0.0
        total_setup_min = float(df["setup_duration"].sum()) if "setup_duration" in df.columns else 0.0

        run_hours = total_run_min / 60.0
        setup_hours = total_setup_min / 60.0

        # Normal işçilik ve setup maliyeti
        base_labor_cost = run_hours * self.params.labor_rate_per_hour
        setup_cost = setup_hours * self.params.setup_cost_per_hour

        # 2. Fazla Mesai (Overtime) Maliyeti
        # Hafta 1 sınırı (168 saat / 10080 dk) üstü veya overtime bayrağı
        overtime_min = 0.0
        if "is_overtime" in df.columns:
            overtime_min = float(df[df["is_overtime"] == 1][run_duration_col].sum())
        elif "end_min" in df.columns:
            # Standart haftalık vardiya sınırını (ör. 120 saat) aşan kısımlar
            overtime_min = max(0.0, float(df["end_min"].max() - (5 * 24 * 60)))

        overtime_hours = overtime_min / 60.0
        overtime_cost = overtime_hours * (self.params.labor_rate_per_hour * self.params.overtime_multiplier)

        # 3. Enerji ve Karbon Maliyeti
        energy_cost = energy_kwh_total * self.params.energy_cost_per_kwh
        carbon_cost = carbon_emissions_ton * self.params.carbon_cost_per_ton

        # 4. Hızlandırma (Expedite) Maliyeti
        expedite_cost = expedited_orders_count * self.params.expedite_cost_flat

        # 5. Müşteri / Sipariş Bazlı Maliyet ve Gecikme (Tardiness & Holding)
        tardiness_cost_total = 0.0
        holding_cost_total = 0.0
        order_cost_list: list[dict[str, Any]] = []

        group_col = "job_id" if "job_id" in df.columns else "product_id"
        job_summary = df.groupby(group_col).agg(
            completion_min=("end_min", "max"),
            start_min=("start_min", "min"),
            job_run_min=(run_duration_col, "sum"),
            job_setup_min=("setup_duration", "sum") if "setup_duration" in df.columns else (run_duration_col, lambda _: 0.0),
        ).reset_index()

        if orders_df is not None and not orders_df.empty:
            merged = pd.merge(job_summary, orders_df, on=group_col, how="left")
        else:
            merged = job_summary.copy()

        # Eksik sütun varsayılanları
        if "due_date_min" not in merged.columns:
            merged["due_date_min"] = 7 * 24 * 60  # 1 hafta
        if "customer_class" not in merged.columns:
            merged["customer_class"] = "STANDARD"
        if "quantity" not in merged.columns:
            merged["quantity"] = 100

        for _, row in merged.iterrows():
            cid = row[group_col]
            comp_min = row["completion_min"]
            due_min = row["due_date_min"]
            qty = row["quantity"]

            # Tardiness
            tardy_min = max(0.0, comp_min - due_min)
            tardy_cost = (tardy_min / 60.0) * self.params.default_tardiness_cost_per_hour
            if row["customer_class"] == "TIER_1":
                tardy_cost *= 2.0  # VIP müşteri cezası

            # Holding / Stokta bekleme süresi (gün)
            wip_days = (comp_min - row["start_min"]) / (24 * 60.0)
            holding_cost = qty * max(0.1, wip_days) * self.params.holding_cost_per_unit_per_day

            direct_labor = (row["job_run_min"] / 60.0) * self.params.labor_rate_per_hour
            direct_setup = (row["job_setup_min"] / 60.0) * self.params.setup_cost_per_hour

            cts_order = direct_labor + direct_setup + tardy_cost + holding_cost

            order_cost_list.append({
                group_col: cid,
                "customer_class": row["customer_class"],
                "direct_labor_cost": round(direct_labor, 2),
                "direct_setup_cost": round(direct_setup, 2),
                "tardiness_cost": round(tardy_cost, 2),
                "inventory_holding_cost": round(holding_cost, 2),
                "cost_to_serve": round(cts_order, 2),
            })

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
