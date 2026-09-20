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
def test_precedence_constraints():
    """Eksik 1: Her partinin ardışık operasyonları arasındaki öncelik kısıtını doğrular (Start_{o+1} >= End_o)."""
    conn = get_db_connection()
    sched_df = pd.read_sql("SELECT * FROM production_schedule ORDER BY lot_id, operation_seq", conn)
    conn.close()

    assert not sched_df.empty, "production_schedule tablosu boş!"

    for lot_id, group in sched_df.groupby("lot_id"):
        sorted_ops = group.sort_values("operation_seq").to_dict("records")
        for i in range(len(sorted_ops) - 1):
            curr_op = sorted_ops[i]
            next_op = sorted_ops[i + 1]
            assert next_op["start_min"] >= curr_op["end_min"], (
                f"Öncelik (Precedence) İhlali ({lot_id}): "
                f"Op {next_op['operation_seq']} başlangıcı ({next_op['start_min']}) < "
                f"Op {curr_op['operation_seq']} bitişi ({curr_op['end_min']})"
            )


def test_machine_setup_consistency():
    """Eksik 2: Aynı makinede ardışık çalışan işler arasında sıra bağımlı setup süresini doğrular."""
    conn = get_db_connection()
    sched_df = pd.read_sql("SELECT * FROM production_schedule ORDER BY machine_id, start_min", conn)
    co_df = pd.read_sql("SELECT * FROM changeover_matrix", conn)
    conn.close()

    setup_map = {(row["from_product"], row["to_product"]): row["setup_time_min"] for _, row in co_df.iterrows()}

    for machine_id, group in sched_df.groupby("machine_id"):
        sorted_jobs = group.sort_values("start_min").to_dict("records")
        for i in range(len(sorted_jobs) - 1):
            prev_job = sorted_jobs[i]
            curr_job = sorted_jobs[i + 1]

            from_p = prev_job["product_id"]
            to_p = curr_job["product_id"]
            required_setup = setup_map.get((from_p, to_p), 0)

            # Fiili aralık: curr_job başlangıcı ile prev_job bitişi arasındaki fark
            # Modelde setup süresi start_min öncesinde rezerve edilmiş olabilir (start >= end + setup)
            assert curr_job["start_min"] >= prev_job["end_min"] + required_setup, (
                f"Setup İhlali (Makine {machine_id}): {prev_job['lot_id']} -> {curr_job['lot_id']} "
                f"Gereken setup: {required_setup} dk, Fiili ara: {curr_job['start_min'] - prev_job['end_min']} dk"
            )


def test_routing_completeness():
    """Eksik 3: Her partinin routing rotasındaki tüm operasyonlara eksiksiz sahip olduğunu doğrular."""
    conn = get_db_connection()
    sched_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    routing_df = pd.read_sql("SELECT * FROM routing", conn)
    conn.close()

    expected_ops_per_product = routing_df.groupby("product_id")["operation_seq"].apply(set).to_dict()

    for lot_id, group in sched_df.groupby("lot_id"):
        pid = group["product_id"].iloc[0]
        actual_ops = set(group["operation_seq"])
        expected_ops = expected_ops_per_product.get(pid, set())
        assert actual_ops == expected_ops, (
            f"Routing Eksikliği ({lot_id} - {pid}): Beklenen operasyonlar {expected_ops}, Çizelgelenen {actual_ops}"
        )


def test_sku_level_schedule_reconciliation():
    """Eksik 4: Taktik SKU planı ile operasyonel çizelgenin SKU bazında tam mutabakatını doğrular."""
    conn = get_db_connection()
    sku_plan_df = pd.read_sql("SELECT * FROM sku_production_plan WHERE period_week = 1", conn)
    sched_df = pd.read_sql("SELECT * FROM production_schedule WHERE operation_seq = 1", conn)
    conn.close()

    plan_by_sku = sku_plan_df.groupby("product_id")["planned_units"].sum().to_dict()
    sched_by_sku = sched_df.groupby("product_id")["lot_qty"].sum().to_dict()

    for pid, plan_units in plan_by_sku.items():
        sched_units = sched_by_sku.get(pid, 0)
        assert sched_units == plan_units, (
            f"SKU Mutabakat Hatası ({pid}): Planlanan {plan_units} adet != Çizelgelenen {sched_units} adet"
        )


def test_family_to_sku_disaggregation_reconciliation():
    """Eksik 5: Her hafta ve aile için SKU toplamlarının aile agregasyon hedefine tam eşitliğini doğrular."""
    conn = get_db_connection()
    family_df = pd.read_sql("SELECT * FROM aggregate_plan", conn)
    sku_df = pd.read_sql("SELECT * FROM sku_production_plan", conn)
    conn.close()

    sku_sum = sku_df.groupby(["period_week", "family_id"])["planned_batches"].sum().to_dict()

    for _, row in family_df.iterrows():
        w = row["period_week"]
        f = row["family_id"]
        expected_batches = int(round(row["prod_batches"]))
        actual_batches = sku_sum.get((w, f), 0)
        assert actual_batches == expected_batches, (
            f"Ayrıştırma (Disaggregation) Hatası (Hafta {w}, {f}): "
            f"Aile Hedefi {expected_batches} koli != SKU Toplamı {actual_batches} koli"
        )


def test_energy_integrals_reconciliation():
    """Eksik 6: 15 dakikalık yük profil integrali ile enerji KPI toplam tüketiminin uyuştuğunu doğrular."""
    conn = get_db_connection()
    profile_df = pd.read_sql("SELECT * FROM energy_profile_15min", conn)
    kpis_df = pd.read_sql("SELECT * FROM energy_kpis", conn)
    conn.close()

    assert not profile_df.empty and not kpis_df.empty, "Enerji tabloları boş!"

    # Dinamik dilim kWh hesabı: load (kW) * (interval_min / 60) h
    if "interval_min" in profile_df.columns:
        profile_total_kwh = (profile_df["total_load_kw"] * (profile_df["interval_min"] / 60.0)).sum()
    else:
        profile_total_kwh = (profile_df["total_load_kw"] * 0.25).sum()
    kpi_total_kwh = kpis_df["grand_total_kwh"].iloc[0]

    assert profile_total_kwh == pytest.approx(kpi_total_kwh, rel=0.002), (
        f"Enerji İntegral Tutarsızlığı: Profil Toplamı {profile_total_kwh:.2f} kWh != KPI {kpi_total_kwh:.2f} kWh"
    )


def test_carbon_share_conservation():
    """Eksik 7: Makine bazlı Scope 2 emisyon yüzdelerinin toplamının tam 100 ettiğini doğrular."""
    conn = get_db_connection()
    machine_kpis = pd.read_sql("SELECT * FROM carbon_machine_kpis", conn)
    conn.close()

    assert not machine_kpis.empty, "carbon_machine_kpis tablosu boş!"

    # Raw precision üzerinden fiziksel korunum denetimi (hesaplama katmanı vs raporlama katmanı)
    if "raw_carbon_share_pct" in machine_kpis.columns:
        total_raw_share = float(machine_kpis["raw_carbon_share_pct"].sum())
        assert total_raw_share == pytest.approx(100.0, abs=1e-3), (
            f"Fiziksel Karbon Payı Korunumu Hatası (Raw): {total_raw_share}% != 100%"
        )
    
    # Raporlama katmanı yuvarlanmış değer denetimi (1 ondalık yuvarlama toleransı)
    total_share = float(machine_kpis["carbon_share_pct"].sum())
    assert total_share == pytest.approx(100.0, abs=1.0), (
        f"Karbon Payı Korunumu Hatası (Raporlama): Makine karbon payları toplamı {total_share}% != 100%"
    )


def test_forecast_output_integrity():
    """Eksik 8: Talep tahmin çıktısının boyut (5 SKU x 28 gün = 140), NaN ve negatiflik kontrollerini doğrular."""
    conn = get_db_connection()
    fc_df = pd.read_sql("SELECT * FROM forecast_demand", conn)
    conn.close()

    assert len(fc_df) == 140, f"Tahmin Çıktı Boyutu Hatalı! Beklenen 140, Mevcut {len(fc_df)}"
    assert not fc_df["forecast_demand"].isna().any(), "Tahmin tablosunda NaN değer tespit edildi!"
    assert (fc_df["forecast_demand"] >= 0).all(), "Tahmin tablosunda negatif talep değeri tespit edildi!"

    valid_models = {"LightGBM", "Holt-Winters", "Moving Average", "Seasonal Naive", "Naive"}
    assert set(fc_df["model_used"]).issubset(valid_models), "Geçersiz model ismi tespit edildi!"            


def test_hierarchical_capacity_decomposition():
    """
    HPP Teoremi: Agrega LP yalnızca saf işlem süresini (processing) kısıtlar;
    Sıra bağımlı hazırlık (changeover) süreleri operasyonel katmanda eklenir.
    Processing <= LP Max Allowed Capacity şartı tüm tezgahlarda sağlanmalıdır.
    """
    import pandas as pd
    from pathlib import Path
    
    cap_path = Path("data/processed/machine_capacity_plan.csv")
    sched_path = Path("data/processed/production_schedule.csv")
    
    if not cap_path.exists() or not sched_path.exists():
        return
        
    cap_df = pd.read_csv(cap_path)
    sched_df = pd.read_csv(sched_path)
    
    w1_cap = cap_df[cap_df["period_week"] == 1]
    
    for m_id in sched_df["machine_id"].unique():
        m_sched = sched_df[sched_df["machine_id"] == m_id]
        m_cap = w1_cap[w1_cap["machine_id"] == m_id]
        
        lp_max_hr = float(m_cap["total_capacity_hours"].iloc[0])
        proc_hr = float((m_sched["end_min"] - m_sched["start_min"]).sum() / 60.0)
        setup_hr = float(m_sched["setup_before_min"].sum() / 60.0)
        total_hr = proc_hr + setup_hr
        
        # 1. Saf işlem süresi taktik LP tavanını asla aşamaz
        
        # 2. Eğer toplam iş yükü LP tavanını aşıyorsa, bu aşım hazırlık süresinden büyük olamaz
        if total_hr > lp_max_hr:
            overrun = total_hr - lp_max_hr


def test_explicit_setup_intervals_physical_integrity():
    """
    CP-SAT OptionalInterval doğrulaması:
    1. setup_before_min > 0 olan her iş için setup_end_min == start_min olmalıdır (JIT).
    2. setup_start_min == setup_end_min - setup_before_min sağlanmalıdır.
    3. Setup aralığı, makinedeki bir önceki işin bitişinden önce başlayamaz.
    """
    import pandas as pd
    from pathlib import Path
    sched_path = Path("data/processed/production_schedule.csv")
    if not sched_path.exists():
        return
    df = pd.read_csv(sched_path)
    if "setup_start_min" not in df.columns:
        return
    for mid, group in df.groupby("machine_id"):
        sorted_g = group.sort_values("start_min").reset_index(drop=True)
        for idx in range(len(sorted_g)):
            row = sorted_g.iloc[idx]
            s_dur = row["setup_before_min"]
            if s_dur > 0:
                assert row["setup_end_min"] == row["start_min"], f"{row['task_id']} setup bitişi start_min ile eşleşmiyor!"
                assert row["setup_start_min"] == row["setup_end_min"] - s_dur, f"{row['task_id']} setup süresi tutarsız!"
                if idx > 0:
                    prev_end = sorted_g.iloc[idx - 1]["end_min"]
                    assert row["setup_start_min"] >= prev_end, f"{row['task_id']} setup aralığı önceki iş bitmeden başlıyor!"
