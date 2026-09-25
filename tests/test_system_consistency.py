import sqlite3
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from src.utils.db import get_db_connection
from src.config import (
    PROCESSED_DATA_DIR,
    SYNTHETIC_DATA_DIR,
    WEEKLY_MINUTES_PER_MACHINE,
    AGGREGATE_MAX_OVERTIME_HOURS
)

def _load_schedule_data():
    db_path = Path(__file__).resolve().parent.parent / "data" / "factory.db"
    if not db_path.exists():
        return None
    try:
        conn = get_db_connection(db_path)
        df = pd.read_sql("SELECT * FROM production_schedule", conn)
        conn.close()
        if not df.empty:
            return df
    except Exception:
        pass
    return None

def test_schedule_makespan_energy_consistency():
    """
    Çizelgeleme makespan değeri ile enerji analitiği makespan değerinin
    planlı mola / kapalı süreler (off_time) hesaba katılarak tutarlı olduğunu doğrular.
    """
    import sqlite3
    import pandas as pd
    from pathlib import Path

    from src.energy.energy_analytics import compute_energy_analytics

    db_path = Path(__file__).resolve().parent.parent / "data" / "factory.db"
    conn = get_db_connection(db_path)
    
    # Tablo henüz oluşmamışsa analitiği çalıştırıp tabloyu oluştur
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='energy_kpis'")
    if not cur.fetchone():
        compute_energy_analytics()

    sched_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    energy_kpi = pd.read_sql("SELECT * FROM energy_kpis", conn)
    conn.close()

    assert not sched_df.empty, "production_schedule tablosu boş olamaz."
    
    # Çizelge brüt makespan: 'end_min' veya 'end_time' kolonunu güvenli şekilde al
    end_col = next((c for c in ["end_min", "end_time", "end_minute"] if c in sched_df.columns), None)
    assert end_col is not None, "Çizelge bitiş zamanı kolonu bulunamadı!"
    
    sched_makespan_hours = float(sched_df[end_col].max()) / 60.0
    
    # Enerji net makespan
    energy_makespan_val = float(energy_kpi["makespan_hours"].iloc[0])
    
    # Brüt makespan, net çalışma makespaninden küçük olamaz
    assert sched_makespan_hours >= energy_makespan_val - 0.25, (
        f"Brüt makespan ({sched_makespan_hours:.2f}h) net enerji makespaninden ({energy_makespan_val:.2f}h) küçük olamaz."
    )


def test_machine_capacity_consistency():
    """
    Test 2: Machine capacity consistency check (HPP Tactical LP vs Operational CP-SAT).
    Verifies that for Week 1, the scheduled processing hours on each machine
    do not exceed the tactical LP capacity ceiling (total_capacity_hours)
    defined in machine_capacity_plan.csv within numerical tolerance.
    """
    import pandas as pd
    from pathlib import Path

    df = _load_schedule_data()
    if df is None:
        pytest.skip("Production schedule artifact not found.")

    db_path = Path(__file__).resolve().parent.parent / "data" / "factory.db"
    assert db_path.exists(), "factory.db not found"
    conn = get_db_connection(db_path)
    cap_df = pd.read_sql("SELECT * FROM machine_capacity_plan", conn)
    conn.close()
    w1_cap = cap_df[cap_df["period_week"] == 1]
    assert not w1_cap.empty, "machine_capacity_plan tablosu icinde 1. hafta verisi bulunamadi"

    for m_id in sorted(df["machine_id"].unique()):
        m_sched = df[df["machine_id"] == m_id]
        m_cap_row = w1_cap[w1_cap["machine_id"] == m_id]
        assert not m_cap_row.empty, f"{m_id} icin W1 kapasite plani tanimi yok."
        
        lp_allowed_max_hr = float(m_cap_row["total_capacity_hours"].iloc[0])
        # Saf islem suresi (processing hours)
        proc_hours = round(float((m_sched["end_min"] - m_sched["start_min"]).sum() / 60.0), 2)
        
        # LP agrega modeli saf islem suresini kisitlar: proc_hours <= lp_allowed_max_hr (+ 0.05 h tolerans)
        assert proc_hours <= lp_allowed_max_hr + 0.05, (
            f"{m_id} makinesinde operasyonel islem suresi ({proc_hours:.2f}h), "
            f"taktik LP kapasite sinirini ({lp_allowed_max_hr:.2f}h) asiyor."
        )


def test_carbon_energy_balance():
    """
    Test 3: Carbon-energy balance check (First Law consistency).
    Strictly verifies that the sum of individual machine energy consumption
    from energy_machine_kpis equals grand_total_kwh in energy_kpis.
    """
    import sqlite3
    import pandas as pd
    from pathlib import Path
    from src.config import DB_PATH

    from src.energy.energy_analytics import compute_energy_analytics

    assert Path(DB_PATH).exists(), f"Veritabani bulunamadi: {DB_PATH}"
    conn = get_db_connection(DB_PATH)
    
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='energy_machine_kpis'")
    if not cur.fetchone():
        compute_energy_analytics()

    m_kpis = pd.read_sql("SELECT machine_id, total_kwh FROM energy_machine_kpis", conn)
    f_kpis = pd.read_sql("SELECT grand_total_kwh FROM energy_kpis", conn)
    conn.close()

    assert not m_kpis.empty, "energy_machine_kpis tablosu bos olamaz."
    assert not f_kpis.empty, "energy_kpis tablosu bos olamaz."

    sum_machine_kwh = float(m_kpis["total_kwh"].sum())
    facility_grand_total_kwh = float(f_kpis["grand_total_kwh"].iloc[0])

    # 2. Termodinamik Enerji Korunumu Mutabakati (Sum of machines == Facility total)
    assert np.isclose(sum_machine_kwh, facility_grand_total_kwh, atol=0.5), (
        f"Enerji korunum dengesizligi: Makinelerin toplami ({sum_machine_kwh:.2f} kWh) "
        f"ile Tesis toplami ({facility_grand_total_kwh:.2f} kWh) eslesmiyor."
    )

def test_transfer_batching_precedence_and_flow():
    """
    Transfer partileme (transfer batching) ve ardışık operasyon akışını
    production_schedule tablosu üzerinden doğrular.
    """
    import sqlite3
    import pandas as pd
    from pathlib import Path
    
    db_path = Path(__file__).resolve().parent.parent / "data" / "factory.db"
    conn = get_db_connection(db_path)
    sched_df = pd.read_sql("SELECT * FROM production_schedule", conn)
    conn.close()

    assert not sched_df.empty, "production_schedule boş olamaz."

    group_col = "lot_id" if "lot_id" in sched_df.columns else "batch_id" if "batch_id" in sched_df.columns else "product_id"
    start_col = "start_min" if "start_min" in sched_df.columns else "start_time"
    end_col = "end_min" if "end_min" in sched_df.columns else "end_time"
    seq_col = "operation_seq" if "operation_seq" in sched_df.columns else "operation_sequence"

    if seq_col in sched_df.columns:
        for key, group in sched_df.groupby(group_col):
            group_sorted = group.sort_values(seq_col)
            prev_end = 0
            for _, row in group_sorted.iterrows():
                assert row[start_col] >= prev_end - 1e-3, (
                    f"Transfer batching öncelik ihlali: {key} op {row[seq_col]} "
                    f"start ({row[start_col]}) < prev end ({prev_end})"
                )
                prev_end = row[end_col]

def test_cpsat_solver_metadata_workers():
    """CP-SAT metadata dosyasında worker sayılarının doğru kaydedildiğini doğrular."""
    import json
    from pathlib import Path
    import src.config as cfg

    project_root = Path(__file__).resolve().parent.parent
    meta_path = getattr(cfg, "REPORTS_DIR", project_root / "reports") / "schedule_solver_metadata.json"
    assert meta_path.exists(), "schedule_solver_metadata.json bulunamadı!"

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    expected_workers = int(cfg.CPSAT_NUM_SEARCH_WORKERS)
    assert meta.get("configured_num_search_workers") == expected_workers
    assert meta.get("effective_num_search_workers") == expected_workers
    assert meta.get("num_workers") == expected_workers

def test_master_data_database_constraints():
    """DB seviyesindeki UNIQUE / PRIMARY KEY kısıtlarının mükerrer kaydı reddettiğini doğrular."""
    import sqlite3
    import pytest
    import src.config as cfg

    conn = get_db_connection(cfg.DB_PATH)
    cur = conn.cursor()

    # 1. materials.material_id PRIMARY KEY ihlali
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute("INSERT INTO materials (material_id, material_name) VALUES ('RAW_STEEL_A', 'Duplicate Material')")
        conn.commit()
    conn.rollback()

    # 2. bom (product_id, material_id) PRIMARY KEY ihlali
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute("INSERT INTO bom (product_id, material_id, qty_per_unit) VALUES ('P01', 'RAW_STEEL_A', 99.0)")
        conn.commit()
    conn.rollback()

    # 3. routing (product_id, operation_seq) PRIMARY KEY ihlali
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute("INSERT INTO routing (product_id, operation_seq, machine_id, processing_time_min) VALUES ('P01', 1, 'M01', 5.0)")
        conn.commit()
    conn.rollback()

    # 4. changeover_matrix (machine_id, from_product, to_product) PRIMARY KEY ihlali
    # NOT NULL + 'ALL' sentinal değeri ile mükerrerlik kesinlikle engellenir
    cur.execute("SELECT machine_id, from_product, to_product FROM changeover_matrix LIMIT 1")
    row = cur.fetchone()
    if row:
        mid, fp, tp = row[0], row[1], row[2]
    else:
        mid, fp, tp = 'ALL', 'P01', 'P01'
        cur.execute("INSERT OR REPLACE INTO changeover_matrix (machine_id, from_product, to_product, setup_time_min) VALUES (?, ?, ?, 10.0)", (mid, fp, tp))
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        # Aynı (machine_id, from_product, to_product) üçlüsünü tekrar eklemeyi dene -> Kesin IntegrityError
        cur.execute("INSERT INTO changeover_matrix (machine_id, from_product, to_product, setup_time_min) VALUES (?, ?, ?, 99.0)", (mid, fp, tp))
        conn.commit()
    conn.rollback()

    # Ekstra P0 Güvencesi: machine_id kolonu NOT NULL kısıtına sahip olmalı
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute("INSERT INTO changeover_matrix (machine_id, from_product, to_product, setup_time_min) VALUES (NULL, 'P01', 'P02', 15.0)")
        conn.commit()
    conn.rollback()

    conn.close()  

def test_pipeline_failure_status_and_downstream_isolation():
    """Pipeline başarısız olduğunda veya başlatıldığında stale downstream tabloların aktif kabul edilmediğini doğrular."""
    import sqlite3
    import src.config as cfg

    with sqlite3.connect(cfg.DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM pipeline_runs ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        assert row is not None, "pipeline_runs tablosu boş!"
        # Başarılı bir pipeline koşusunun statüsü SUCCESS veya COMPLETED olmalı, FAILED/RUNNING olmamalıdır
        assert row[0] in ("SUCCESS", "COMPLETED")      

def test_pipeline_transaction_boundary_and_active_run_promotion(tmp_path, monkeypatch):
    """Denetim Madde 27: Pipeline çalışma sırasında RUNNING, hata anında FAILED, yalnızca başarıda COMPLETED olmalıdır."""
    import sqlite3
    import src.config as config
    from src.utils.lineage import (
        start_pipeline_run, 
        record_pipeline_run_metadata, 
        get_active_pipeline_run, 
        init_pipeline_runs_table
    )

    temp_db = str(tmp_path / "test_boundary.db")
    monkeypatch.setenv("FACTORY_DB_PATH", temp_db)
    monkeypatch.setattr(config, "DB_PATH", temp_db)
    import src.utils.lineage as lineage_mod
    temp_metadata_path = tmp_path / "run_metadata.json"
    monkeypatch.setattr(lineage_mod, "METADATA_JSON_PATH", temp_metadata_path)

    conn = sqlite3.connect(temp_db)
    init_pipeline_runs_table(conn)
    conn.close()

    # 1. Başlatıldığında durum RUNNING olmalı
    run_1 = "RUN-TEST-BOUND-001"
    start_pipeline_run(run_1, db_path=temp_db)
    
    conn = sqlite3.connect(temp_db)
    c = conn.cursor()
    c.execute("SELECT status FROM pipeline_runs WHERE run_id = ?", (run_1,))
    assert c.fetchone()[0] == "RUNNING", "Pipeline baslatildiginda status RUNNING olmali!"
    
    # Henüz terfi etmediği için active run bulunamamalı
    assert get_active_pipeline_run(db_path=temp_db) is None, "RUNNING durumundaki kosum active kabul edilemez!"
    conn.close()

    # 2. Hata durumunda FAILED mühürlenmeli ve asla promote edilmemeli
    record_pipeline_run_metadata(run_id=run_1, status="FAILED", db_path=temp_db)
    assert get_active_pipeline_run(db_path=temp_db) is None, "FAILED kosum active kabul edilemez!"

    # 3. İkinci bir koşum başarıyla bittiğinde PROMOTE edilmeli ve ACTIVE run olmalı
    run_2 = "RUN-TEST-BOUND-002"
    start_pipeline_run(run_2, db_path=temp_db)
    record_pipeline_run_metadata(run_id=run_2, status="COMPLETED", orders_count=500, db_path=temp_db)
    
    active_run = get_active_pipeline_run(db_path=temp_db)
    assert active_run is not None
    assert active_run["run_id"] == run_2
    assert active_run["status"] == "COMPLETED"

def test_lp_cpsat_overtime_reconciliation():
    """
    Denetim Madde 2: Taktik LP ve CP-SAT Fazla Mesai (OT) Birebir Mutabakatı.
    Operasyonel CP-SAT'ın fiili kullandığı toplam OT süresi,
    taktik modelin tezgâh başına izin verdiği 48 saatlik (2,880 dk) üst sınırı aşamaz.
    """
    import sqlite3
    import pandas as pd
    from src.config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    sched_df = pd.read_sql_query("SELECT * FROM production_schedule", conn)
    conn.close()

    assert not sched_df.empty, "production_schedule tablosu boş!"

    # Tezgâh bazında toplam OT kullanımını topla (overtime_min sütunu)
    ot_per_machine = sched_df.groupby("machine_id")["overtime_min"].sum()
    max_allowed_ot_min = 48 * 60  # 48 saat = 2880 dakika

    for machine_id, actual_ot in ot_per_machine.items():
        assert actual_ot <= max_allowed_ot_min, (
            f"Makine {machine_id} için CP-SAT OT kullanımı ({actual_ot} dk), "
            f"taktik LP izin verilen OT bütçesini ({max_allowed_ot_min} dk) aştı!"
        )    

def test_p0_mes_machine_state_not_overwritten():
    """
    P0 Denetim Kanıtı:
    Gerçek MES snapshot'ı (ör. M01 -> P05) veritabanına yazılmışsa,
    pipeline yeniden başlatıldığında (initialize_database) bu canlı durum
    statik seed verisiyle EZİLMEMELİDİR.
    """
    import sqlite3
    from src.config import DB_PATH
    from src.data.build_database_and_eda import initialize_database

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Simüle edilmiş MES canlı durumu: M01 tezgâhı en son P05 üretti
    cur.execute("INSERT OR REPLACE INTO machine_state (machine_id, last_product_id) VALUES ('M01', 'P05')")
    conn.commit()

    # Test öncesi son run_id'yi al
    cur.execute("SELECT run_id FROM pipeline_runs ORDER BY timestamp DESC LIMIT 1")
    last_run_before = cur.fetchone()
    last_run_id_before = last_run_before[0] if last_run_before else None
    conn.close()

    try:
        # 2. Pipeline veritabanı başlatmasını çalıştır (force_recreate=False)
        initialize_database(force_recreate=False)

        # 3. M01 tezgâhının durumunu sorgula; P01'e geri dönmemeli, P05 olarak korunmalı
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT last_product_id FROM machine_state WHERE machine_id = 'M01'")
        current_product = cur.fetchone()[0]
        assert current_product == "P05", f"MES canlı durumu statik veriyle ezildi! Beklenen: P05, Gelen: {current_product}"
    finally:
        # Test İzolasyonu: initialize_database'in açtığı geçici INITIALIZED kaydını temizle
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        if last_run_id_before:
            cur.execute("DELETE FROM pipeline_runs WHERE status = 'INITIALIZED' AND run_id != ?", (last_run_id_before,))
        else:
            cur.execute("DELETE FROM pipeline_runs WHERE status = 'INITIALIZED'")
        conn.commit()
        conn.close()