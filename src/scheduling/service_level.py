"""
Customer Service Level & Due-Date Tardiness Analytics Engine (Madde 33).
Çizelgeleme sonuçlarını müşteri öncelikleri, termin tarihleri (due-dates)
ve gecikme cezaları (tardiness) üzerinden çok boyutlu KPI'lara dönüştürür.
"""

from typing import Any

import pandas as pd

from src.config import ECONOMIC_CONFIG
from src.scheduling.analytics_schema import schedule_job_summary

# Müşteri sınıfı / Öncelik ceza çarpanları (Tier 1 = VIP / Stratejik Ortak)
CUSTOMER_CLASS_WEIGHTS = {
    "TIER_1": 3.0,
    "TIER_2": 2.0,
    "TIER_3": 1.0,
    "STANDARD": 1.0,
}

# Economic SSOT: configured currency per tardy minute.
DEFAULT_TARDINESS_COST_PER_MIN = ECONOMIC_CONFIG.tardiness_cost_per_hour / 60.0


def evaluate_schedule_service_level(
    schedule_df: pd.DataFrame,
    orders_df: pd.DataFrame | None = None,
    default_due_date_min: float = 7 * 24 * 60,  # 1 Hafta (10,080 dk)
    cost_per_tardy_min: float = DEFAULT_TARDINESS_COST_PER_MIN,
) -> dict[str, Any]:
    """
    Çizelgelenmiş işlerin teslim tarihlerine (due date) uyumunu,
    müşteri sınıflarına göre ağırlıklı gecikmelerini ve servis seviyesi KPI'larını hesaplar.
    """
    if schedule_df.empty:
        return {
            "on_time_delivery_pct": 100.0,
            "total_orders": 0,
            "on_time_orders": 0,
            "late_orders": 0,
            "total_tardiness_min": 0.0,
            "weighted_tardiness": 0.0,
            "late_quantity": 0,
            "total_tardiness_cost": 0.0,
            "utilization_pct": 0.0,
            "total_setup_hours": 0.0,
            "makespan_hours": 0.0,
            "orders_breakdown": [],
        }

    # Eğer sipariş bazlı due-date tablosu verilmemişse iş/parti bazında türet
    df = schedule_df.copy()

    # Sipariş veya iş tamamlama zamanı (C_j: job'ın son operasyonunun bitişi)
    group_col, merged = schedule_job_summary(df, orders_df)

    # Varsayılan sütun atamaları (yoksa)
    if "due_date_min" not in merged.columns:
        merged["due_date_min"] = default_due_date_min
    else:
        merged["due_date_min"] = merged["due_date_min"].fillna(default_due_date_min)

    if "customer_class" not in merged.columns:
        merged["customer_class"] = "STANDARD"
    else:
        merged["customer_class"] = merged["customer_class"].fillna("STANDARD")

    if "priority" not in merged.columns:
        merged["priority"] = merged.get("priority_weight", 1)
    else:
        merged["priority"] = merged["priority"].fillna(1)

    if "quantity" not in merged.columns:
        merged["quantity"] = 1
    else:
        merged["quantity"] = merged["quantity"].fillna(1)

    # Tardiness Hesabı: T_j = max(0, C_j - d_j)
    merged["tardiness_min"] = (merged["completion_min"] - merged["due_date_min"]).clip(lower=0.0)
    merged["is_late"] = merged["tardiness_min"] > 0

    # Ağırlıklı Tardiness: w_j = priority * tier_multiplier
    merged["tier_weight"] = merged["customer_class"].map(CUSTOMER_CLASS_WEIGHTS).fillna(1.0)
    merged["effective_weight"] = merged["priority"] * merged["tier_weight"]
    merged["weighted_tardiness"] = merged["tardiness_min"] * merged["effective_weight"]

    # Gecikme maliyeti
    merged["tardiness_cost"] = merged["tardiness_min"] * cost_per_tardy_min * merged["effective_weight"]

    # KPI Toplamları
    total_orders = len(merged)
    late_orders = int(merged["is_late"].sum())
    on_time_orders = total_orders - late_orders
    otd_pct = round((on_time_orders / total_orders) * 100.0, 2) if total_orders > 0 else 100.0

    total_tardiness_min = float(merged["tardiness_min"].sum())
    weighted_tardiness = float(merged["weighted_tardiness"].sum())
    late_quantity = int(merged[merged["is_late"]]["quantity"].sum())
    total_tardiness_cost = float(merged["tardiness_cost"].sum())

    # Fabrika Verimlilik Metrikleri
    makespan_min = float(df["end_min"].max()) if not df.empty else 0.0
    makespan_hours = round(makespan_min / 60.0, 2)

    setup_col = "setup_before_min" if "setup_before_min" in df.columns else "setup_duration"
    total_setup_min = float(df[setup_col].sum()) if setup_col in df.columns else 0.0
    total_setup_hours = round(total_setup_min / 60.0, 2)

    # Operasyon süreleri ve kullanım (utilization)
    if "duration_min" in df.columns:
        run_time_col = "duration_min"
    elif "duration" in df.columns:
        run_time_col = "duration"
    else:
        run_time_col = "run_duration"
    total_run_min = float(df[run_time_col].sum()) if run_time_col in df.columns else 0.0

    num_machines = df["machine_id"].nunique() if "machine_id" in df.columns else 1
    total_available_min = max(1.0, makespan_min * num_machines)
    utilization_pct = round(((total_run_min + total_setup_min) / total_available_min) * 100.0, 2)

    return {
        "on_time_delivery_pct": otd_pct,
        "total_orders": total_orders,
        "on_time_orders": on_time_orders,
        "late_orders": late_orders,
        "total_tardiness_min": round(total_tardiness_min, 2),
        "total_tardiness_hours": round(total_tardiness_min / 60.0, 2),
        "weighted_tardiness": round(weighted_tardiness, 2),
        "late_quantity": late_quantity,
        "total_tardiness_cost": round(total_tardiness_cost, 2),
        "utilization_pct": utilization_pct,
        "total_setup_hours": total_setup_hours,
        "makespan_hours": makespan_hours,
        "orders_breakdown": merged[
            [group_col, "completion_min", "due_date_min", "customer_class", "priority", "tardiness_min", "is_late"]
        ].to_dict(orient="records"),
    }
