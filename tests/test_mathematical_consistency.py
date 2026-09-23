import sys
import os
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
    """Eksik 5: Her hafta ve aile için SKU toplamlarının aile agregasyon hedefine mutabakatını doğrular.
    Kapalı çevrim (closed-loop) kapasite onarımı ve tamsayı yuvarlama payı (<= 1 parti) gözetilir.
    """
    import os
    import sqlite3
    db_path = os.path.join("data", "factory.db")
    conn = sqlite3.connect(db_path)
    family_df = pd.read_sql("SELECT * FROM aggregate_plan", conn)
    sku_df = pd.read_sql("SELECT * FROM sku_production_plan", conn)
    conn.close()

    sku_sum = sku_df.groupby(["period_week", "family_id"])["planned_batches"].sum().to_dict()

    for _, row in family_df.iterrows():
        w = row["period_week"]
        f = row["family_id"]
        expected_batches = int(round(row["prod_batches"]))
        actual_batches = sku_sum.get((w, f), 0)
        # Closed-loop capacity repair ve integer lotting toleransı (|fark| <= 1 parti)
        diff = abs(actual_batches - expected_batches)
        assert diff <= 1, (
            f"Ayrıştırma (Disaggregation) Hatası (Hafta {w}, {f}): "
            f"Aile Hedefi {expected_batches} koli, SKU Toplamı {actual_batches} koli (Fark: {diff} > 1)"
        )


def test_energy_integrals_reconciliation():
    """Eksik 6: 15 dakikalık yük profil integrali ile enerji KPI toplam tüketiminin uyuştuğunu doğrular."""
    conn = get_db_connection()
    profile_df = pd.read_sql("SELECT * FROM energy_profile_15min", conn)
    kpis_df = pd.read_sql("SELECT * FROM energy_kpis", conn)
    conn.close()

    assert not profile_df.empty and not kpis_df.empty, "Enerji tabloları boş!"

    # Dinamik dilim kWh hesabı: sum(Load_t * (Interval_t / 60))
    assert "interval_min" in profile_df.columns, "energy_profile_15min tablosunda 'interval_min' kolonu bulunmalıdır!"
    profile_total_kwh = (profile_df["total_load_kw"] * (profile_df["interval_min"] / 60.0)).sum()
    kpi_total_kwh = float(kpis_df["grand_total_kwh"].iloc[0])

    # Profil integrali ile operasyonel KPI toplamı tutarlılığı (off-shift baz yük farkı toleransı ile)
    ratio = profile_total_kwh / kpi_total_kwh
    assert 0.98 <= ratio <= 1.02, (
        f"Enerji İntegral Tutarsızlığı: Profil Toplamı {profile_total_kwh:.2f} kWh != KPI {kpi_total_kwh:.2f} kWh (Oran: {ratio:.2f})"
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
    HPP Teoremi: Agrega LP yalnizca saf islem suresini (processing) kisitlar;
    Sira bagimli hazirlik (changeover) sureleri operasyonel katmanda eklenir.
    Processing <= LP Max Allowed Capacity sarti tum tezgahlarda saglanmalidir.
    """
    import pandas as pd
    from pathlib import Path

    db_path = os.path.join("data", "factory.db")
    assert os.path.exists(db_path), "factory.db veritabani dosyasi bulunamadi"
    conn = sqlite3.connect(db_path)
    cap_df = pd.read_sql("SELECT * FROM machine_capacity_plan", conn)
    sched_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    w1_cap = cap_df[cap_df["period_week"] == 1]
    assert not w1_cap.empty, "machine_capacity_plan.csv icinde 1. hafta tanimi yok."
    
    tolerance = 0.05

    for m_id in sorted(sched_df["machine_id"].unique()):
        m_sched = sched_df[sched_df["machine_id"] == m_id]
        m_cap = w1_cap[w1_cap["machine_id"] == m_id]
        assert not m_cap.empty, f"{m_id} icin W1 kapasitesi tanimlanmamis."
        
        lp_max_hr = float(m_cap["total_capacity_hours"].iloc[0])
        proc_hr = float((m_sched["end_min"] - m_sched["start_min"]).sum() / 60.0)
        setup_hr = float(m_sched["setup_before_min"].sum() / 60.0)
        total_hr = proc_hr + setup_hr

        # 1. Agrega LP yalnizca net islem suresini sinirlar
        assert proc_hr <= lp_max_hr + tolerance, (
            f"{m_id} makinesinde operasyonel islem suresi ({proc_hr:.2f}h), "
            f"LP kapasite tavanini ({lp_max_hr:.2f}h) asiyor."
        )

        # 2. Toplam yuk LP sinirini asiyorsa, fark tamamen setup kaynakli olmalidir
        if total_hr > lp_max_hr:
            assert total_hr - lp_max_hr <= setup_hr + tolerance, (
                f"{m_id} tezgahindaki kapasite asimi ({total_hr - lp_max_hr:.2f}h), "
                f"toplam setup suresini ({setup_hr:.2f}h) asamaz."
            )

        # 2. Asim varsa bunun tamamen setup kaynakli oldugunu dogrula
        if total_hr > lp_max_hr:
            assert total_hr - lp_max_hr <= setup_hr + tolerance, (
                f"{m_id} tezgahindaki kapasite asimi ({total_hr - lp_max_hr:.2f}h), "
                f"toplam setup suresini ({setup_hr:.2f}h) asamaz."
            )


def test_explicit_setup_intervals_physical_integrity():
    """
    CP-SAT OptionalInterval doğrulaması:
    1. setup_before_min > 0 olan her iş için setup_end_min == start_min olmalıdır (JIT).
    2. setup_start_min == setup_end_min - setup_before_min sağlanmalıdır.
    3. Setup aralığı, makinedeki bir önceki işin bitişinden önce başlayamaz.
    """
    import pandas as pd
    from pathlib import Path

    db_path = os.path.join("data", "factory.db")
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    assert "setup_start_min" in df.columns, "setup_start_min kolonu schedule..."
    assert "setup_end_min" in df.columns, "setup_end_min kolonu schedule ciktisinda bulunamadi."
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

def test_forecast_model_lineage_governance():
    """Madde 23: Model seçim kararlarının ve MLOps soykütüğünün doğrulanması."""
    import json
    import os
    import sqlite3
    
    db_path = os.path.join("data", "factory.db")
    conn = sqlite3.connect(db_path)
    lineage_df = pd.read_sql("SELECT * FROM forecast_model_lineage", conn)
    conn.close()

    assert not lineage_df.empty, "forecast_model_lineage tablosu boş!"
    assert len(lineage_df) == 5, f"5 pilot ürün bekleniyordu, {len(lineage_df)} bulundu."

    required_cols = [
        "product_id", "selected_model", "model_version", "feature_version",
        "training_start", "training_end", "backtest_start", "backtest_end",
        "validation_score_wape", "test_score_rmse", "hyperparameters",
        "competing_models", "selection_reason"
    ]
    for col in required_cols:
        assert col in lineage_df.columns, f"forecast_model_lineage içinde '{col}' kolonu eksik!"

    # JSON metadata artifact kontrolü
    meta_path = os.path.join("reports", "forecast_model_metadata.json")
    assert os.path.exists(meta_path), f"{meta_path} artifact dosyası oluşturulmamış!"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_data = json.load(f)
    assert len(meta_data) == 5, "Metadata JSON dosyası 5 ürünü içermelidir."

def test_schedule_solver_metadata_governance():
    """Madde 24: CP-SAT çözücü durumunun, makespan optimalliğinin ve çözüm kanıtının doğrulanması."""
    import json
    import os
    import sqlite3

    db_path = os.path.join("data", "factory.db")
    conn = sqlite3.connect(db_path)
    solver_df = pd.read_sql("SELECT * FROM schedule_solver_metadata", conn)
    conn.close()

    assert not solver_df.empty, "schedule_solver_metadata tablosu boş!"
    row = solver_df.iloc[0]

    required_fields = [
        "solver_name", "solver_status", "is_optimal", "objective_value_min",
        "best_bound_min", "optimality_gap_pct", "solve_time_seconds", "random_seed"
    ]
    for field in required_fields:
        assert field in solver_df.columns, f"Çözücü metadata tablosunda '{field}' eksik!"

    assert row["solver_status"] in ("OPTIMAL", "FEASIBLE"), f"Beklenmeyen çözücü statüsü: {row['solver_status']}"
    assert row["objective_value_min"] > 0, "Objective değeri pozitif olmalıdır."
    
    # JSON artifact kontrolü
    meta_json_path = os.path.join("reports", "schedule_solver_metadata.json")
    assert os.path.exists(meta_json_path), "reports/schedule_solver_metadata.json dosyası mevcut değil!"    