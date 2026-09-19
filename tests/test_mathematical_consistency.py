import sys
from pathlib import Path

# Proje ana dizinini arama yoluna ekler
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import sqlite3
import pandas as pd
import pytest
from src.config import (
    DB_PATH,
    AGGREGATE_MAX_OVERTIME_HOURS,
    AGGREGATE_INITIAL_INVENTORY,
)

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def test_aggregate_inventory_balance():
    """Hax & Meal Envanter Denge Kısıtı Doğrulaması: I_t - B_t == I_{t-1} - B_{t-1} + P_t - D_t"""
    conn = get_db_connection()
    plan_df = pd.read_sql("SELECT * FROM aggregate_plan ORDER BY family_id, period_week", conn)
    conn.close()

    assert not plan_df.empty, "aggregate_plan tablosu boş!"

    for family, group in plan_df.groupby("family_id"):
        # Hafta 1 için başlangıç envanterini config'den alıyoruz
        prev_inv = AGGREGATE_INITIAL_INVENTORY.get(family, 0.0)
        prev_backlog = 0.0
        
        for _, row in group.iterrows():
            p = row["prod_batches"]
            d = row["demand_batches"]
            i = row["end_inv_batches"]
            b = row["backlog_batches"]
            
            # Net envanter hesabı (yuvarlama hassasiyetiyle)
            net_balance = round((prev_inv - prev_backlog) + p - d, 1)
            net_actual = round(i - b, 1)
            
            assert net_actual == pytest.approx(net_balance, abs=0.2), (
                f"Envanter Denge Hatası ({family} W{row['period_week']}): "
                f"Beklenen {net_balance}, Çıkan {net_actual}"
            )
            prev_inv = i
            prev_backlog = b

def test_machine_overtime_bounds():
    """Fazla mesainin yasal/teknik AGGREGATE_MAX_OVERTIME_HOURS tavanını aşmadığını doğrular."""
    conn = get_db_connection()
    plan_df = pd.read_sql("SELECT * FROM aggregate_plan", conn)
    conn.close()

    max_ot = plan_df["max_machine_overtime_hours"].max()
    assert max_ot <= AGGREGATE_MAX_OVERTIME_HOURS, (
        f"Maksimum fazla mesai sınırı aşıldı! {max_ot} > {AGGREGATE_MAX_OVERTIME_HOURS}"
    )

def test_energy_physics_assertion():
    """Madde 16: Tepe yükün ortalama yükten küçük olamayacağını garanti eder."""
    conn = get_db_connection()
    kpi_df = pd.read_sql("SELECT * FROM energy_kpis", conn)
    profile_df = pd.read_sql("SELECT * FROM energy_profile_15min", conn)
    conn.close()

    assert not kpi_df.empty, "energy_kpis tablosu boş!"
    row = kpi_df.iloc[0]

    peak_load = row["peak_load_kw"]
    avg_load = row["avg_load_kw"]
    load_factor = row["load_factor"]

    assert peak_load >= avg_load, f"Fiziksel İhlal: Peak ({peak_load} kW) < Avg ({avg_load} kW)"
    assert 0.0 < load_factor <= 1.0, f"Geçersiz Yük Faktörü: {load_factor}"
    
    # 15 dakikalık profil ile KPI tepe değeri tam örtüşmeli
    profile_max = profile_df["total_load_kw"].max()
    assert round(profile_max, 2) == pytest.approx(peak_load, abs=0.1)

def test_schedule_mrp_release_time_coupling():
    """Madde 14: MRP expedite kısıtına sahip lotların erken başlamadığını doğrular."""
    conn = get_db_connection()
    sched_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    mrp_df = pd.read_sql("SELECT * FROM mrp_plan WHERE period_week = 1", conn)
    bom_df = pd.read_sql("SELECT * FROM bom", conn)
    conn.close()

    expedite_mats = set(mrp_df[mrp_df["action_message"].str.contains("EXPEDITE", na=False)]["material_id"])
    
    # İlk operasyonları denetle
    first_ops = sched_df[sched_df["operation_seq"] == 1]
    for _, row in first_ops.iterrows():
        pid = row["product_id"]
        req_mats = set(bom_df[bom_df["product_id"] == pid]["material_id"])
        
        if req_mats.intersection(expedite_mats):
            # En az 480. dakikada serbest kalmış olmalı
            assert row["start_min"] >= 480, (
                f"MRP Kısıt İhlali: {row['lot_id']} kritik hammadde eksik olmasına rağmen "
                f"{row['start_min']}. dakikada başlatılmış!"
            )
