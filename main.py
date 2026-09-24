"""
Factory Decision Intelligence Platform - Master Pipeline Orchestrator
----------------------------------------------------------------------
Uçtan uca hiyerarşik üretim planlama, detaylı çizelgeleme,
malzeme gereksinim planlaması, enerji ve karbon muhasebesi zincirini çalıştırır.
"""

import sys
import time
from src.data.preprocessing import run_preprocessing
from src.data.build_database_and_eda import initialize_database
from src.forecasting.train_forecast import run_forecast_benchmark
from src.planning.aggregate_planning import run_planning_pipeline
from src.inventory.bom_mrp import run_mrp_engine
from src.scheduling.schedule_cpsat import solve_cpsat_schedule
from src.energy.energy_analytics import compute_energy_analytics
from src.carbon.carbon_analytics import compute_carbon_analytics
from src.utils.lineage import record_pipeline_run_metadata, generate_run_id

def run_end_to_end_pipeline():
    start_total = time.time()
    run_id = generate_run_id()

    print("\n" + "#" * 85)
    print(f"      FABRİKA KARAR DESTEK PLATFORMU: PIPELINE BAŞLATILDI (Run ID: {run_id})")
    print("#" * 85)

    steps = [
        ("Aşama 1: Veri Ön İşleme & Temizlik", run_preprocessing),
        ("Aşama 2: SQLite Veritabanı Kurulumu", lambda: initialize_database(run_id=run_id)),
        ("Aşama 3: ML Talep Tahmini (LightGBM)", lambda: run_forecast_benchmark(run_id=run_id)),
        ("Aşama 4: Hiyerarşik Taktik Planlama & SKU Ayrıştırma", lambda: run_planning_pipeline(run_id=run_id)),
        ("Aşama 5: Malzeme İhtiyaç Planlaması (MRP-I)", lambda: run_mrp_engine(run_id=run_id)),
        ("Aşama 6: Detaylı Çizelgeleme (Google OR-Tools CP-SAT)", lambda: solve_cpsat_schedule(run_id=run_id)),
        ("Aşama 7A: Enerji Analitiği & Yük Profili", lambda: compute_energy_analytics(run_id=run_id)),
        ("Aşama 7B: Kurumsal Karbon Muhasebesi (GHG Protocol)", lambda: compute_carbon_analytics(run_id=run_id)),
    ]

    try:
        for idx, (name, func) in enumerate(steps, 1):
            step_start = time.time()
            print(f"\n>>> [{idx}/{len(steps)}] {name} başlatılıyor...")
            func()
            elapsed = time.time() - step_start
            print(f">>> [OK] {name} tamamlandı ({elapsed:.2f} sn).\n")

        # Başarıyla tamamlandığında SUCCESS durumu kaydet
        meta = record_pipeline_run_metadata(run_id=run_id, status="SUCCESS")
        print(f"\n[AUDIT] Run metadata kaydedildi -> reports/run_metadata.json (Run ID: {meta['run_id']}, Status: SUCCESS)")

        import sqlite3
        from src.config import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE pipeline_runs SET status = 'SUCCESS' WHERE run_id = ?", (run_id,))
            conn.commit()

    except Exception as exc:
        print(f"\n[CRITICAL PIPELINE FAILURE] Aşama hatası: {str(exc)}", file=sys.stderr)
        
        # Hata durumunda FAILED durumu kaydet
        record_pipeline_run_metadata(run_id=run_id, status="FAILED")
        try:
            import sqlite3
            from src.config import DB_PATH
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("UPDATE pipeline_runs SET status = 'FAILED' WHERE run_id = ?", (run_id,))
                conn.commit()
        except Exception:
            pass
        raise exc

    total_time = time.time() - start_total
    print("\n" + "#" * 85)
    print(f" TÜM ENTEGRE PIPELINE BAŞARIYLA TAMAMLANDI! Toplam Süre: {total_time:.2f} saniye")
    print("#" * 85)


if __name__ == "__main__":
    run_end_to_end_pipeline()