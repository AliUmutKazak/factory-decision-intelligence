"""P2: Scenario Engine & What-If Simulation Module (Faz 2: Decision Engine Closure).

Gerçek fabrika operasyonları için karar destek ve duyarlılık analizi motoru.
Girdi şoklarını izole staging/sandbox ortamında simüle eder:
- Finansal şoklar (+25% Energy, +50 €/tCO2) analitik SSOT ekonomik motoru ile değerlendirilir.
- Operasyonel şoklar (+20% Demand, M01 Failure, Material Delay) gerçek LP -> MRP -> CP-SAT
  çizelgeleme ve operasyonel veriler üzerinden deterministik metrikler üretir.
"""

import sqlite3
import tempfile
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.config import (
    DEFAULT_ELECTRICITY_PRICE_EUR_PER_KWH,
    ECONOMIC_CONFIG,
    ObjectivePolicy,
    get_runtime_paths,
)
from src.contracts.schemas import ScenarioResultModel
from src.economics.cost_to_serve import CostParameters, EconomicDecisionEngine
from src.scheduling.service_level import evaluate_schedule_service_level
from src.utils.db import clone_run_inputs, get_active_run_id, get_db_connection


class ScenarioDataUnavailableError(Exception):
    """Madde 24: Veritabanında çizelge veya operasyonel veriler bulunamadığında
    sahte default üretilmesini engelleyen karar zekâsı kural istisnası.
    Unknown != Zero != Default.
    """

    pass


@dataclass
class ScenarioShock:
    name: str
    demand_multiplier: float = 1.0
    capacity_multiplier: float = 1.0
    electricity_price_multiplier: float = 1.0
    carbon_tax_delta_eur: float = 0.0
    objective_policy: str = ObjectivePolicy.BALANCED
    failed_machines: list[str] = field(default_factory=list)
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

    def to_contract(self) -> ScenarioResultModel:
        """Sonuçları Pydantic v2 sözleşmesi üzerinden doğrular ve mühürler."""
        return ScenarioResultModel(
            scenario=self.scenario,
            makespan_hours=self.makespan_hours,
            on_time_delivery_pct=self.on_time_delivery_pct,
            inventory_holding_cost_eur=self.inventory_holding_cost_eur,
            backlog_units=self.backlog_units,
            energy_cost_eur=self.energy_cost_eur,
            carbon_tco2e=self.carbon_tco2e,
            carbon_cost_eur=self.carbon_cost_eur,
            total_cost_eur=self.total_cost_eur,
        )

    @classmethod
    def from_contract(cls, model: ScenarioResultModel) -> "ScenarioResult":
        """Pydantic modelinden ScenarioResult nesnesi türetir."""
        return cls(
            scenario=model.scenario,
            makespan_hours=model.makespan_hours,
            on_time_delivery_pct=model.on_time_delivery_pct,
            inventory_holding_cost_eur=model.inventory_holding_cost_eur,
            backlog_units=model.backlog_units,
            energy_cost_eur=model.energy_cost_eur,
            carbon_tco2e=model.carbon_tco2e,
            carbon_cost_eur=model.carbon_cost_eur,
            total_cost_eur=model.total_cost_eur,
        )


class ScenarioEngine:
    """Tüm boru hattı simülasyonunu yöneten ve şok senaryolarını
    karşılaştırmalı iş metriklerine dönüştüren deterministik karar destek motoru.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = str(db_path or get_runtime_paths()["db_path"])
        self.baseline_run_id: str | None = None
        self.scenarios: dict[str, ScenarioShock] = {
            "BASELINE": ScenarioShock(name="BASELINE"),
            "+20% DEMAND": ScenarioShock(name="+20% DEMAND", demand_multiplier=1.20),
            "-10% CAPACITY": ScenarioShock(name="-10% CAPACITY", capacity_multiplier=0.90),
            "+25% ENERGY COST": ScenarioShock(name="+25% ENERGY COST", electricity_price_multiplier=1.25),
            "+50 €/tCO2": ScenarioShock(name="+50 €/tCO2", carbon_tax_delta_eur=50.0),
            "M01 FAILURE": ScenarioShock(name="M01 FAILURE", failed_machines=["M01"]),
            "RAW MATERIAL DELAY": ScenarioShock(name="RAW MATERIAL DELAY", material_delay_days=3),
        }

    def _read_table_safe(self, table_name: str, db_path: str, run_id: str | None = None) -> pd.DataFrame:
        conn = get_db_connection(db_path)
        try:
            run_scoped = {
                "orders",
                "forecast_demand",
                "forecast_model_lineage",
                "aggregate_plan",
                "sku_production_plan",
                "machine_capacity_plan",
                "mrp_plan",
                "production_schedule",
                "energy_kpis",
                "energy_machine_kpis",
                "carbon_kpis",
                "carbon_machine_kpis",
                "carbon_price_scenarios",
            }
            if run_id and table_name in run_scoped:
                return pd.read_sql(f"SELECT * FROM {table_name} WHERE run_id = ?", conn, params=(str(run_id),))
            return pd.read_sql(f"SELECT * FROM {table_name}", conn)
        except Exception as exc:
            raise ScenarioDataUnavailableError(f"DATA_UNAVAILABLE: {table_name} okunamadı: {exc}") from exc
        finally:
            conn.close()

    def _get_baseline_energy_carbon(
        self, sched_df: pd.DataFrame, energy_df: pd.DataFrame, carbon_df: pd.DataFrame
    ) -> tuple[float, float, float]:
        """Çizelge ve KPI tablolarından gerçek baz makespan, kWh ve tCO2e türetir.
        Madde 24: Veri yoksa keyfi default atanamaz (Unknown != Zero != Default).
        """
        if not sched_df.empty and "end_min" in sched_df.columns and not sched_df["end_min"].isna().all():
            base_makespan = float(sched_df["end_min"].max()) / 60.0
        elif not energy_df.empty and "makespan_hours" in energy_df.columns:
            base_makespan = float(energy_df["makespan_hours"].iloc[0])
        else:
            raise ScenarioDataUnavailableError(
                "DATA_UNAVAILABLE: Makespan türetilebilecek geçerli operasyonel veri yok."
            )

        if energy_df.empty or "grand_total_kwh" not in energy_df.columns:
            raise ScenarioDataUnavailableError("DATA_UNAVAILABLE: Energy KPI missing.")
        if carbon_df.empty or "total_tco2e" not in carbon_df.columns:
            raise ScenarioDataUnavailableError("DATA_UNAVAILABLE: Carbon KPI missing.")
        base_kwh = float(energy_df["grand_total_kwh"].iloc[0])
        base_tco2 = float(carbon_df["total_tco2e"].iloc[0])

        return base_makespan, base_kwh, base_tco2

    def _solve_operational_shock(self, shock: ScenarioShock, source_run_id: str):
        """Run LP -> MRP -> CP-SAT -> energy/carbon on a private SQLite backup."""
        from src.carbon.carbon_analytics import compute_carbon_analytics
        from src.config import SchedulingObjectivePolicy
        from src.energy.energy_analytics import compute_energy_analytics
        from src.inventory.bom_mrp import run_mrp_engine
        from src.planning.aggregate_planning import run_planning_pipeline
        from src.scheduling.maintenance import MaintenanceWindow
        from src.scheduling.schedule_cpsat import run_cpsat_scheduling

        if shock.demand_multiplier < 0 or shock.capacity_multiplier <= 0:
            raise ValueError("Demand must be non-negative and capacity positive.")
        with tempfile.TemporaryDirectory(prefix="factory-scenario-") as temporary:
            root = Path(temporary)
            db = root / "factory.db"
            processed = root / "processed"
            reports = root / "reports"
            with closing(sqlite3.connect(self.db_path)) as source, closing(sqlite3.connect(db)) as target:
                source.backup(target)
            scenario_id = f"SCENARIO-{uuid.uuid4().hex[:12]}"
            with sqlite3.connect(db) as conn:
                clone_run_inputs(conn, source_run_id, scenario_id)
                if shock.demand_multiplier != 1.0:
                    conn.execute(
                        "UPDATE forecast_demand SET forecast_demand = forecast_demand * ? WHERE run_id = ?",
                        (shock.demand_multiplier, scenario_id),
                    )
                if shock.capacity_multiplier != 1.0:
                    # Capacity loss is modeled as lower throughput, including
                    # both the tactical resource load and operational durations.
                    conn.execute(
                        "UPDATE routing SET processing_time_min = processing_time_min / ?", (shock.capacity_multiplier,)
                    )
                conn.commit()
            try:
                run_planning_pipeline(run_id=scenario_id, db_path=db, processed_dir=processed)
                run_mrp_engine(run_id=scenario_id, db_path=db, processed_dir=processed)
                windows = [
                    MaintenanceWindow(machine, 480, 960, "BREAKDOWN", shock.name) for machine in shock.failed_machines
                ]
                run_cpsat_scheduling(
                    run_id=scenario_id,
                    db_path=db,
                    processed_dir=processed,
                    reports_dir=reports,
                    policy=SchedulingObjectivePolicy(shock.objective_policy),
                    maintenance_overrides=windows,
                    material_delay_min=shock.material_delay_days * 1440,
                )
                compute_energy_analytics(run_id=scenario_id, db_path=db, processed_dir=processed)
                compute_carbon_analytics(run_id=scenario_id, db_path=db, processed_dir=processed)
                with sqlite3.connect(db) as conn:
                    schedule = pd.read_sql(
                        "SELECT * FROM production_schedule WHERE run_id = ?", conn, params=(scenario_id,)
                    )
                    energy = pd.read_sql("SELECT * FROM energy_kpis WHERE run_id = ?", conn, params=(scenario_id,))
                    carbon = pd.read_sql("SELECT * FROM carbon_kpis WHERE run_id = ?", conn, params=(scenario_id,))
                    orders = pd.read_sql("SELECT * FROM orders WHERE run_id = ?", conn, params=(scenario_id,))
                return schedule, float(energy["grand_total_kwh"].iloc[0]), float(carbon["total_tco2e"].iloc[0]), orders
            except Exception as exc:
                raise ScenarioDataUnavailableError(f"SCENARIO_SOLVE_FAILED: {shock.name}: {exc}") from exc

    @contextmanager
    def _baseline_snapshot(self):
        if not Path(self.db_path).is_file():
            raise ScenarioDataUnavailableError("DATA_UNAVAILABLE: Runtime database missing.")
        with tempfile.TemporaryDirectory(prefix="factory-baseline-") as temporary:
            snapshot = Path(temporary) / "factory.db"
            with closing(sqlite3.connect(self.db_path)) as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
                try:
                    self.baseline_run_id = get_active_run_id(target)
                except RuntimeError as exc:
                    raise ScenarioDataUnavailableError(f"DATA_UNAVAILABLE: {exc}") from exc
            engine = ScenarioEngine(db_path=str(snapshot))
            yield engine

    def evaluate_scenario(self, shock: ScenarioShock) -> ScenarioResult:
        with self._baseline_snapshot() as engine:
            return engine._evaluate_scenario(shock)

    def _evaluate_scenario(self, shock: ScenarioShock) -> ScenarioResult:
        """Madde 23: Hibrit Senaryo Motoru.

        - 3 Kritik Operasyonel Şok (Demand, Capacity, Material): Gerçek kısıt çözümü / rerun.
        - Finansal Şoklar (Energy, CO2): Analitik duyarlılık (Sensitivity) analizi.
        """
        try:
            with get_db_connection(self.db_path) as conn:
                run_id = get_active_run_id(conn)
        except RuntimeError as exc:
            raise ScenarioDataUnavailableError(f"DATA_UNAVAILABLE: {exc}") from exc
        sched_df = self._read_table_safe("production_schedule", self.db_path, run_id)
        energy_df = self._read_table_safe("energy_kpis", self.db_path, run_id)
        carbon_df = self._read_table_safe("carbon_kpis", self.db_path, run_id)
        orders_df = self._read_table_safe("orders", self.db_path, run_id)

        # Hem çizelge hem enerji tablosu yoksa/boşsa veri yoktur: hata fırlat
        if sched_df.empty and (energy_df.empty or "makespan_hours" not in energy_df.columns):
            raise ScenarioDataUnavailableError(
                "DATA_UNAVAILABLE: production_schedule veya energy_kpis tablosu boş ya da okunamadı. "
                "Senaryo simülasyonu sahte verilerle koşturulamaz (Unknown != Zero != Default)."
            )

        base_makespan, base_kwh, base_tco2 = self._get_baseline_energy_carbon(sched_df, energy_df, carbon_df)

        sim_sched = sched_df.copy() if not sched_df.empty else pd.DataFrame()
        sim_makespan = base_makespan
        sim_kwh = base_kwh
        sim_tco2 = base_tco2

        operational_shock = (
            shock.failed_machines
            or shock.material_delay_days > 0
            or shock.demand_multiplier != 1.0
            or shock.capacity_multiplier != 1.0
        )
        if operational_shock:
            sim_sched, sim_kwh, sim_tco2, orders_df = self._solve_operational_shock(shock, run_id)
            sim_makespan = float(sim_sched["end_min"].max()) / 60.0 if not sim_sched.empty else 0.0

        # =====================================================================
        # 2. SERVİS SEVİYESİ VE GECİKME (OTIF %)
        # =====================================================================
        target_due_min = 168.0 * 60.0
        service_kpis = evaluate_schedule_service_level(
            schedule_df=sim_sched,
            orders_df=orders_df,
            default_due_date_min=target_due_min,
        )
        on_time_pct = round(service_kpis["on_time_delivery_pct"], 1)
        backlog = int(service_kpis["late_quantity"])

        # =====================================================================
        # 3. FİNANSAL SENSITIVITY ANALİZİ (+25% Energy, +50 €/tCO2)
        # =====================================================================
        unit_electricity_price = DEFAULT_ELECTRICITY_PRICE_EUR_PER_KWH * shock.electricity_price_multiplier
        total_carb_rate = ECONOMIC_CONFIG.carbon_price_per_ton + shock.carbon_tax_delta_eur

        params = CostParameters(
            energy_cost_per_kwh=unit_electricity_price,
            carbon_cost_per_ton=total_carb_rate,
        )

        # 4. Ekonomik Karar Motoru (TMC)
        # Doğrudan deterministik enerji ve karbon maliyet hesapları
        calc_energy_cost = round(sim_kwh * unit_electricity_price, 2)
        calc_carbon_cost = round(sim_tco2 * total_carb_rate, 2)

        if not sim_sched.empty:
            econ_engine = EconomicDecisionEngine(params=params)
            cost_breakdown = econ_engine.compute_total_manufacturing_cost(
                schedule_df=sim_sched,
                orders_df=orders_df,
                energy_kwh_total=sim_kwh,
                carbon_emissions_ton=sim_tco2,
            )
            inventory_cost = round(cost_breakdown.inventory_holding_cost, 2)
            energy_cost = round(cost_breakdown.energy_cost, 2)
            carbon_cost = round(cost_breakdown.carbon_cost, 2)
            total_cost = round(cost_breakdown.total_manufacturing_cost, 2)
        else:
            inventory_cost = 0.0
            energy_cost = calc_energy_cost
            carbon_cost = calc_carbon_cost
            total_cost = round(energy_cost + carbon_cost, 2)

        return ScenarioResult(
            scenario=shock.name,
            makespan_hours=round(sim_makespan, 2),
            on_time_delivery_pct=on_time_pct,
            inventory_holding_cost_eur=inventory_cost,
            backlog_units=backlog,
            energy_cost_eur=energy_cost,
            carbon_tco2e=round(sim_tco2, 2),
            carbon_cost_eur=carbon_cost,
            total_cost_eur=total_cost,
        )

    def run_all_scenarios(self) -> pd.DataFrame:
        """Tüm senaryoları çalıştırarak nihai Karşılaştırma Matrisini döner."""
        # One SQLite snapshot pins the entire comparison to the same run and masters.
        with self._baseline_snapshot() as engine:
            results = [engine._evaluate_scenario(shock) for shock in self.scenarios.values()]
        df = pd.DataFrame([r.__dict__ for r in results])
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
        df["Baseline Run"] = self.baseline_run_id
        return df
