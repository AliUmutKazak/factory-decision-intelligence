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
from src.utils.lineage import (
    record_pipeline_run_metadata, 
    generate_run_id, 
    start_pipeline_run, 
    get_active_pipeline_run,
    apply_run_retention_policy
)

def run_end_to_end_pipeline():
    run_id = generate_run_id()
    print("\n" + "#" * 85)
    print(f"      FABRİKA KARAR DESTEK PLATFORMU: PIPELINE BAŞLATILDI (Run ID: {run_id})")
    print("#" * 85 + "\n")

    # Denetim Madde 27: Transaction Boundary - Koşum RUNNING olarak mühürlenir
    start_pipeline_run(run_id=run_id)

    stages = [
        ("Aşama 1: Veri Ön İşleme & Temizlik", lambda: run_preprocessing()),
        ("Aşama 2: SQLite Veritabanı Kurulumu", lambda: initialize_database(run_id=run_id)),
        ("Aşama 3: ML Talep Tahmini (LightGBM)", lambda: run_forecast_benchmark(run_id=run_id)),
        ("Aşama 4: Hiyerarşik Taktik Planlama & SKU Ayrıştırma", lambda: run_planning_pipeline(run_id=run_id)),
        ("Aşama 5: Malzeme İhtiyaç Planlaması (MRP-I)", lambda: run_mrp_engine(run_id=run_id)),
        ("Aşama 6: Detaylı Çizelgeleme (Google OR-Tools CP-SAT)", lambda: solve_cpsat_schedule(run_id=run_id)),
        ("Aşama 7A: Enerji Analitiği & Yük Profili", lambda: compute_energy_analytics(run_id=run_id)),
        ("Aşama 7B: Kurumsal Karbon Muhasebesi (GHG Protocol)", lambda: compute_carbon_analytics(run_id=run_id)),
    ]

    total_start = time.time()

    try:
        for stage_name, stage_func in stages:
            print(f">>> [{stages.index((stage_name, stage_func)) + 1}/8] {stage_name} başlatılıyor...")
            s_start = time.time()
            stage_func()
            s_elapsed = time.time() - s_start
            print(f">>> [OK] {stage_name} tamamlandı ({s_elapsed:.2f} sn).\n")

        total_elapsed = time.time() - total_start

        # Gerçek sipariş sayısını veritabanından dinamik al
        actual_orders_count = 0
        try:
            from src.utils.db import get_db_connection
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM orders")
                row = cur.fetchone()
                if row:
                    actual_orders_count = row[0]
        except Exception:
            pass

        # Denetim meta verisini gerçek sipariş adedi ve veri kaynağıyla kaydet
        meta = record_pipeline_run_metadata(
            run_id=run_id,
            status="COMPLETED",
            orders_count=actual_orders_count,
            data_source="data/processed/factory_orders.csv"
        )
        print(f"\n[AUDIT] Run metadata kaydedildi -> reports/run_metadata.json (Run ID: {meta['run_id']}, Status: COMPLETED, Orders: {actual_orders_count})")

        # Denetim Kapı 5: Historical Run Retention (Son 20 koşumu koru, eskileri tasfiye et)
        pruned_count = apply_run_retention_policy(keep_last_n=20)
        if pruned_count > 0:
            print(f"[AUDIT] Retention Policy uygulandı: {pruned_count} adet eski denetim kaydı arşivlendi/temizlendi.")

        print("\n" + "#" * 85)
        print(f" TÜM ENTEGRE PIPELINE BAŞARIYLA TAMAMLANDI! Toplam Süre: {total_elapsed:.2f} saniye")
        print("#" * 85 + "\n")

    except Exception as exc:
        print(f"\n[CRITICAL PIPELINE FAILURE] Aşama hatası: {str(exc)}", file=sys.stderr)
        try:
            record_pipeline_run_metadata(run_id=run_id, status="FAILED")
        except Exception:
            pass
        raise exc


if __name__ == "__main__":
    run_end_to_end_pipeline()