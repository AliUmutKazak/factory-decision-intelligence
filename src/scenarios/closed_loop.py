"""
Closed-Loop MES Integration & Dynamic Replanning Module
Saha fiili üretim verilerini (Actuals) izler, plan sapmalarını (slippage) ölçer
ve eşik aşımında yeniden çizelgeleme (Dynamic Replanning) kararını tetikler.
"""

import os
from dataclasses import dataclass

import pandas as pd

from src.utils.db import get_db_connection


@dataclass
class ReplanningTriggerDecision:
    run_id: str
    schedule_slippage_pct: float
    total_delay_hours: float
    scrap_rate_pct: float
    requires_replanning: bool
    trigger_reason: str | None = None


class ClosedLoopEngine:
    """
    Planlanan çizelge ile sahadan toplanan MES gerçekleşenlerini
    karşılaştıran ve kapalı çevrim kontrolünü sağlayan motor.
    """

    def __init__(self, db_path: str | None = None, slippage_threshold_pct: float = 10.0, max_delay_hours: float = 4.0):
        self.db_path = db_path or os.environ.get("FACTORY_DB_PATH", "data/factory.db")
        self.slippage_threshold_pct = slippage_threshold_pct
        self.max_delay_hours = max_delay_hours

    def ingest_mes_actuals(self, actuals_df: pd.DataFrame, run_id: str | None = None) -> int:
        """
        MES üzerinden gelen fiili üretim ve duruş kayıtlarını veritabanına yazar.
        """
        conn = get_db_connection(self.db_path)
        if run_id and "run_id" not in actuals_df.columns:
            actuals_df = actuals_df.copy()
            actuals_df["run_id"] = run_id

        actuals_df.to_sql("mes_production_actuals", conn, if_exists="append", index=False)
        conn.commit()
        conn.close()
        return len(actuals_df)

    def evaluate_variance_and_trigger(self, run_id: str) -> ReplanningTriggerDecision:
        """
        Sahadaki fiili süreleri planlanan sürelerle karşılaştırarak sapmayı ölçer.
        Belirlenen tolerans aşıldığında Replanning tetikleme kararı verir.
        """
        conn = get_db_connection(self.db_path)
        actuals_df = pd.read_sql("SELECT * FROM mes_production_actuals WHERE run_id = ?", conn, params=(run_id,))
        conn.close()

        if actuals_df.empty:
            return ReplanningTriggerDecision(
                run_id=run_id,
                schedule_slippage_pct=0.0,
                total_delay_hours=0.0,
                scrap_rate_pct=0.0,
                requires_replanning=False,
                trigger_reason="No MES actuals recorded for this run.",
            )

        # Planlanan vs Gerçekleşen Makespan ve Gecikme Analizi
        total_planned_hours = (actuals_df["planned_end_hour"] - actuals_df["planned_start_hour"]).sum()
        total_actual_hours = (actuals_df["actual_end_hour"] - actuals_df["actual_start_hour"]).sum()

        # Ek duruş sürelerini dahil et
        downtime_hours = actuals_df["downtime_hours"].sum() if "downtime_hours" in actuals_df.columns else 0.0
        effective_actual_hours = total_actual_hours + downtime_hours

        delta_delay = max(0.0, effective_actual_hours - total_planned_hours)
        slippage_pct = (delta_delay / total_planned_hours * 100.0) if total_planned_hours > 0 else 0.0

        # Hurda / Fire Oranı
        total_units = actuals_df["actual_units"].sum()
        scrap_units = actuals_df["scrap_units"].sum() if "scrap_units" in actuals_df.columns else 0
        scrap_rate_pct = (scrap_units / (total_units + scrap_units) * 100.0) if (total_units + scrap_units) > 0 else 0.0

        # Eşik kontrolleri
        requires_replanning = False
        reasons = []

        if slippage_pct >= self.slippage_threshold_pct:
            requires_replanning = True
            reasons.append(
                f"Schedule slippage ({slippage_pct:.1f}%) exceeded threshold ({self.slippage_threshold_pct:.1f}%)"
            )

        if delta_delay >= self.max_delay_hours:
            requires_replanning = True
            reasons.append(f"Total delay ({delta_delay:.1f}h) exceeded max allowed ({self.max_delay_hours:.1f}h)")

        if scrap_rate_pct > 5.0:
            requires_replanning = True
            reasons.append(f"Scrap rate ({scrap_rate_pct:.1f}%) triggered material deficit replanning")

        return ReplanningTriggerDecision(
            run_id=run_id,
            schedule_slippage_pct=round(slippage_pct, 2),
            total_delay_hours=round(delta_delay, 2),
            scrap_rate_pct=round(scrap_rate_pct, 2),
            requires_replanning=requires_replanning,
            trigger_reason="; ".join(reasons) if reasons else "Execution within tolerance limits.",
        )
