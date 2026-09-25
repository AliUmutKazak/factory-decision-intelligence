import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import pandas as pd
import pytest


@pytest.fixture(scope="module")
def isolated_db():
    temp_dir = tempfile.mkdtemp()
    src_db = (
        "artifacts/reference/factory.db"
        if os.path.exists("artifacts/reference/factory.db")
        else "data/factory.db"
    )
    temp_db = os.path.join(temp_dir, "isolated_factory.db")
    shutil.copy2(src_db, temp_db)
    conn = sqlite3.connect(temp_db)
    yield conn
    conn.close()
    shutil.rmtree(temp_dir)


def test_1_pipeline_run_lineage_zero_nulls(isolated_db):
    df = pd.read_sql("SELECT * FROM pipeline_runs", isolated_db)
    assert not df.empty, "pipeline_runs tablosu bos olamaz"
    audit_cols = ["run_id", "timestamp", "git_sha", "config_hash", "status"]
    for col in audit_cols:
        assert (
            df[col].isnull().sum() == 0
        ), f"pipeline_runs icinde {col} kolonunda null deger bulunamaz"
    assert (
        df["status"] == "SUCCESS"
    ).any(), "En az bir basarili (SUCCESS) run_id kaydi bulunmali"


def test_2_cpsat_calendar_bounds(isolated_db):
    """Denetim Madde 25: Gerçek takvim ve fazla mesai bütçe değişmezlerini (invariants) doğrular."""
    sched_df = pd.read_sql(
        """SELECT task_id, machine_id, start_min, end_min, duration_min, 
                  regular_minutes, overtime_minutes, calendar_shift 
           FROM production_schedule""",
        isolated_db,
    )
    assert not sched_df.empty, "production_schedule tablosu bos olamaz"

    # Makinelerin günlük kapasite sınırlarını al (SSOT)
    machines_df = pd.read_sql("SELECT machine_id, max_daily_hours FROM machines", isolated_db)
    machine_daily_hours = dict(zip(machines_df["machine_id"].astype(str), machines_df["max_daily_hours"].astype(float)))

    # Taktik LP seviyesinde onaylanan fazla mesai bütçesini al
    cap_df = pd.read_sql("SELECT machine_id, overtime_hours FROM machine_capacity_plan WHERE period_week = 1", isolated_db)
    allowed_ot_budget_min = {
        str(r["machine_id"]): float(r["overtime_hours"]) * 60.0
        for _, r in cap_df.iterrows()
    }

    # Değişmez 1 & 2: Görev bazında aralık, süre korunumu ve kesin takvim denetimi
    for _, r in sched_df.iterrows():
        s_min = int(r["start_min"])
        e_min = int(r["end_min"])
        dur = int(r["duration_min"])
        reg_m = float(r["regular_minutes"])
        ot_m = float(r["overtime_minutes"])
        mid = str(r["machine_id"])

        # Süre ve aralık tutarlılığı
        assert e_min >= s_min, f"Gecersiz zaman araligi: start={s_min} > end={e_min}"
        assert e_min - s_min == dur, f"Zaman farki sure ile uyumsuz: end - start != duration ({r['task_id']})"
        assert abs((reg_m + ot_m) - dur) < 1e-4, f"Sure korunumu bozulmus: reg + ot != duration ({r['task_id']})"

        # Kesin takvim: Başlangıç ile bitiş arasındaki HİÇBİR gün Pazar (gün indeksi 6) olamaz
        start_day_idx = s_min // 1440
        end_day_idx = e_min // 1440
        for d in range(start_day_idx, end_day_idx + 1):
            assert (d % 7) != 6, f"Pazar gunune sarkan gorev tespit edildi! Gun: {d}, Gorev: {r['task_id']}"

        # Shift etiketi uyumu
        expected_shift = "OVERTIME" if ot_m > (dur / 2.0) else "REGULAR"
        assert r["calendar_shift"] == expected_shift, (
            f"calendar_shift etiketi hatali! Beklenen: {expected_shift}, Fiili: {r['calendar_shift']} ({r['task_id']})"
        )

        # SSOT Kesim Noktası Doğrulaması (Gece OT penceresi)
        max_h = machine_daily_hours.get(mid, 16.0)
        ot_cutoff = max(0.0, (24.0 - max_h) * 60.0)
        cur = s_min
        calc_ot = 0.0
        while cur < e_min:
            day_cursor = cur % 1440
            if day_cursor < ot_cutoff:
                step = min(e_min - cur, ot_cutoff - day_cursor)
                calc_ot += step
                cur += step
            else:
                step = min(e_min - cur, 1440 - day_cursor)
                cur += step
        assert abs(calc_ot - ot_m) < 1e-4, f"Hesaplanan OT ile kaydedilen OT uyumsuz! ({r['task_id']})"

    # Değişmez 3: Tezgâh bazlı toplam fazla mesai LP tavan sınırını aşamaz
    machine_ot_sums = sched_df.groupby("machine_id")["overtime_minutes"].sum().to_dict()
    for m, actual_ot in machine_ot_sums.items():
        allowed_ot = allowed_ot_budget_min.get(str(m), 48.0 * 60.0)
        assert actual_ot <= allowed_ot + 1e-4, (
            f"Tezgah {m} icin fazla mesai butcesi asildi! "
            f"Izin Verilen: {allowed_ot} dk, Fiili: {actual_ot} dk"
        )


def test_3_batch_quantity_contract(isolated_db):
    sched_df = pd.read_sql(
        "SELECT task_id, batch_count, batch_size_units, production_units FROM production_schedule",
        isolated_db,
    )
    assert not sched_df.empty
    diff = (sched_df["batch_count"] * sched_df["batch_size_units"]) - sched_df[
        "production_units"
    ]
    assert (
        diff == 0
    ).all(), "batch_count * batch_size_units == production_units sozlesmesi bozulmus"


def test_4_sku_production_reconciliation(isolated_db):
    plan_df = pd.read_sql(
        "SELECT product_id, SUM(planned_units) as p_units FROM sku_production_plan WHERE period_week = 1 GROUP BY product_id",
        isolated_db,
    )
    sched_df = pd.read_sql(
        "SELECT product_id, SUM(production_units) as s_units FROM production_schedule WHERE operation_seq = 1 GROUP BY product_id",
        isolated_db,
    )
    merged = pd.merge(plan_df, sched_df, on="product_id")
    assert len(merged) == len(plan_df)
    assert (
        merged["p_units"] == merged["s_units"]
    ).all(), f"SKU Plan vs Cizelge adet uyumsuzlugu: {merged}"


def test_5_hierarchical_capacity_reconciliation(isolated_db):
    cap_df = pd.read_sql(
        "SELECT machine_id, regular_capacity_hours, overtime_hours FROM machine_capacity_plan WHERE period_week = 1",
        isolated_db,
    )
    sched_df = pd.read_sql(
        "SELECT machine_id, SUM(duration_min)/60.0 as actual_proc_hr FROM production_schedule GROUP BY machine_id",
        isolated_db,
    )
    merged = pd.merge(cap_df, sched_df, on="machine_id")
    for _, r in merged.iterrows():
        allowed_hr = r["regular_capacity_hours"] + r["overtime_hours"]
        m_id = r["machine_id"]
        assert r["actual_proc_hr"] <= (
            allowed_hr + 1e-4
        ), f"{m_id} LP saf islem kapasite ust sinirini asti"


def test_6_energy_state_machine_and_integral(isolated_db):
    prof = pd.read_sql(
        "SELECT SUM(total_load_kw * (interval_min / 60.0)) AS integral_kwh FROM energy_profile_15min",
        isolated_db,
    )
    kpi = pd.read_sql("SELECT grand_total_kwh FROM energy_kpis", isolated_db)
    mkpi = pd.read_sql(
        "SELECT SUM(total_kwh) AS machines_total_kwh FROM energy_machine_kpis",
        isolated_db,
    )
    integral_val = float(prof.iloc[0, 0])
    kpi_val = float(kpi.iloc[0, 0])
    m_sum_val = float(mkpi.iloc[0, 0])
    assert (
        abs(integral_val - kpi_val) < 0.01
    ), f"Profil integrali ({integral_val}) ile energy_kpis ({kpi_val}) farkli"
    assert (
        abs(m_sum_val - kpi_val) < 0.01
    ), f"Makine KPI toplami ({m_sum_val}) ile energy_kpis ({kpi_val}) farkli"


def test_7_reference_manifest_integrity():
    manifest_path = "artifacts/reference/manifest.json"
    assert os.path.exists(manifest_path), "manifest.json bulunamadi"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert "files" in manifest and len(manifest["files"]) > 0

    mismatches = []
    missing_files = []

    for fname, meta in manifest["files"].items():
        fpath = os.path.join("artifacts/reference", fname)
        if not os.path.exists(fpath):
            missing_files.append(fname)
            continue
        curr_sha = hashlib.sha256(open(fpath, "rb").read()).hexdigest()
        if curr_sha != meta["sha256"]:
            mismatches.append(
                f"{fname} -> Beklenen: {meta['sha256'][:8]}..., Gercek: {curr_sha[:8]}..."
            )

    assert not missing_files, f"Eksik dosyalar var: {missing_files}"
    assert (
        not mismatches
    ), "SHA-256 uyumsuzluklari tespit edildi:\n" + "\n".join(mismatches)
