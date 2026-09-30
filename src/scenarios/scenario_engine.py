"""
P2: Scenario Engine & What-If Simulation Module
Gerçek fabrika operasyonları için karar destek ve duyarlılık analizi motoru.
Girdi şoklarını simüle eder ve multi-objective trade-off matrisini üretir.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
import sqlite3
import pandas as pd
import numpy as np

from src.config import (
    DEFAULT_ELECTRICITY_PRICE_EUR_PER_KWH,
    CARBON_PRICE_SCENARIOS_EUR,
    AGGREGATE_HOLDING_COST_PER_BATCH,
    LABOR_COST_OVERTIME_HR,
)
from src.utils.db import get_db_connection


@dataclass
class ScenarioShock:
    name: str
    demand_multiplier: float = 1.0
    capacity_multiplier: float = 1.0
    electricity_price_multiplier: float = 1.0
    carbon_tax_delta_eur: float = 0.0
    failed_machines: List[str] = field(default_factory=list)
    material_delay_days: int = 0


@dataclass
class ScenarioResult:
    scenario: str
    makespan_hours: float
    on_time_delivery_pct: float
    inventory_holding_cost_eur: float
    backlog_units: int
    energy_cost_eur: float
    carbon_tco2e: float
    carbon_cost_eur: float
    total_cost_eur: float


class ScenarioEngine:
    """
    Tüm boru hattı simülasyonunu yöneten ve şok senaryolarını
    karşılaştırmalı iş metriklerine dönüştüren karar destek motoru.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.environ.get("FACTORY_DB_PATH", "data/factory.db")
        self.scenarios: Dict[str, ScenarioShock] = {
            "BASELINE": ScenarioShock(name="BASELINE"),
            "+20% DEMAND": ScenarioShock(name="+20% DEMAND", demand_multiplier=1.20),
            "-10% CAPACITY": ScenarioShock(name="-10% CAPACITY", capacity_multiplier=0.90),
            "+25% ENERGY COST": ScenarioShock(name="+25% ENERGY COST", electricity_price_multiplier=1.25),
            "+50 €/tCO2": ScenarioShock(name="+50 €/tCO2", carbon_tax_delta_eur=50.0),
            "M01 FAILURE": ScenarioShock(name="M01 FAILURE", failed_machines=["M01"]),
            "RAW MATERIAL DELAY": ScenarioShock(name="RAW MATERIAL DELAY", material_delay_days=3),
        }

    def evaluate_scenario(self, shock: ScenarioShock) -> ScenarioResult:
        """
        Belirli bir senaryo şokunu temel fiziksel KPI'lar üzerinden simüle eder.
        """
        conn = get_db_connection(self.db_path)
        
        # Temel verileri çek
        try:
            energy_df = pd.read_sql("SELECT * FROM energy_kpis", conn)
            carbon_df = pd.read_sql("SELECT * FROM carbon_kpis", conn)
            sched_df = pd.read_sql("SELECT * FROM production_schedule", conn)
        except Exception:
            energy_df = pd.DataFrame()
            carbon_df = pd.DataFrame()
            sched_df = pd.DataFrame()
        finally:
            conn.close()

        base_makespan = float(energy_df["makespan_hours"].iloc[0]) if not energy_df.empty else 168.0
        base_kwh = float(energy_df["grand_total_kwh"].iloc[0]) if not energy_df.empty else 25000.0
        base_tco2 = float(carbon_df["total_tco2e"].iloc[0]) if not carbon_df.empty else 12.5

        # 1. Makespan Simülasyonu
        # Kapasite düşüşü veya makine arızası makespan'i uzatır, talep artışı işlem süresini genişletir
        capacity_factor = max(shock.capacity_multiplier, 0.1)
        machine_penalty = 1.25 if "M01" in shock.failed_machines else 1.0
        delay_penalty_hours = shock.material_delay_days * 8.0

        simulated_makespan = (base_makespan * shock.demand_multiplier / capacity_factor * machine_penalty) + delay_penalty_hours

        # 2. Zamanında Teslimat (OT) ve Backlog Simülasyonu
        # Nominal plan 168 saat (1 hafta) varsayımıyla eşik kontrolü
        max_acceptable_hours = 168.0
        if simulated_makespan <= max_acceptable_hours:
            on_time_pct = 100.0
            backlog = 0
        else:
            delay_ratio = (simulated_makespan - max_acceptable_hours) / max_acceptable_hours
            on_time_pct = max(0.0, 100.0 - (delay_ratio * 100.0))
            backlog = int(delay_ratio * 500 * shock.demand_multiplier)

        # 3. Enerji Maliyeti
        unit_electricity_price = DEFAULT_ELECTRICITY_PRICE_EUR_PER_KWH * shock.electricity_price_multiplier
        simulated_kwh = base_kwh * shock.demand_multiplier * (1.05 if "M01" in shock.failed_machines else 1.0)
        energy_cost = simulated_kwh * unit_electricity_price

        # 4. Karbon Ayak İzi ve Karbon Maliyeti
        simulated_tco2 = base_tco2 * (simulated_kwh / max(base_kwh, 1.0))
        if isinstance(CARBON_PRICE_SCENARIOS_EUR, list) and len(CARBON_PRICE_SCENARIOS_EUR) > 0:
            base_carbon_price = float(CARBON_PRICE_SCENARIOS_EUR[len(CARBON_PRICE_SCENARIOS_EUR) // 2])
        elif isinstance(CARBON_PRICE_SCENARIOS_EUR, dict):
            base_carbon_price = float(CARBON_PRICE_SCENARIOS_EUR.get("mid", 85.0))
        else:
            base_carbon_price = float(CARBON_PRICE_SCENARIOS_EUR) if CARBON_PRICE_SCENARIOS_EUR else 85.0

        total_carbon_rate = base_carbon_price + shock.carbon_tax_delta_eur
        carbon_cost = simulated_tco2 * total_carbon_rate

        # 5. Stok (Holding) Maliyeti
        # Gecikme veya talep artışı fabrika içi WIP/hammadde bekleme maliyetini artırır
        base_wip_batches = 12
        simulated_batches = base_wip_batches * shock.demand_multiplier * (1.2 if shock.material_delay_days > 0 else 1.0)
        inventory_cost = simulated_batches * AGGREGATE_HOLDING_COST_PER_BATCH

        # 6. Toplam Operasyonel Maliyet (Total Cost)
        overtime_cost = max(0.0, simulated_makespan - max_acceptable_hours) * LABOR_COST_OVERTIME_HR
        total_cost = energy_cost + carbon_cost + inventory_cost + overtime_cost + (backlog * 50.0)

        return ScenarioResult(
            scenario=shock.name,
            makespan_hours=round(simulated_makespan, 2),
            on_time_delivery_pct=round(on_time_pct, 1),
            inventory_holding_cost_eur=round(inventory_cost, 2),
            backlog_units=backlog,
            energy_cost_eur=round(energy_cost, 2),
            carbon_tco2e=round(simulated_tco2, 2),
            carbon_cost_eur=round(carbon_cost, 2),
            total_cost_eur=round(total_cost, 2),
        )

    def run_all_scenarios(self) -> pd.DataFrame:
        """
        Görseldeki tüm senaryoları çalıştırarak nihai Karşılaştırma Matrisini döner.
        """
        results = [self.evaluate_scenario(shock) for shock in self.scenarios.values()]
        df = pd.DataFrame([r.__dict__ for r in results])
        # İşletme görünümü için kolonları yeniden adlandır
        df.columns = [
            "Scenario",
            "Makespan (h)",
            "OT (%)",
            "Inventory Cost (€)",
            "Backlog (units)",
            "Energy Cost (€)",
            "Carbon (tCO2e)",
            "Carbon Cost (€)",
            "Total Cost (€)",
        ]
        return df