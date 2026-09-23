import sqlite3
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
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
        conn = sqlite3.connect(db_path)
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
    conn = sqlite3.connect(db_path)
    
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
    assert sched_makespan_hours >= energy_makespan_val - 1e-3, (
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
    conn = sqlite3.connect(db_path)
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
    conn = sqlite3.connect(DB_PATH)
    
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
    conn = sqlite3.connect(db_path)
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

    conn = sqlite3.connect(cfg.DB_PATH)
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

    # 4. changeover_matrix (from_product, to_product) PRIMARY KEY ihlali
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute("INSERT INTO changeover_matrix (from_product, to_product, setup_time_min) VALUES ('P01', 'P01', 10.0)")
        conn.commit()
    conn.rollback()

    conn.close()    