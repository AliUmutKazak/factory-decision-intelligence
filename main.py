"""
Factory Decision Intelligence Platform - Master Pipeline Orchestrator
----------------------------------------------------------------------
Uçtan uca hiyerarşik üretim planlama, detaylı çizelgeleme,
malzeme gereksinim planlaması, enerji ve karbon muhasebesi zincirini çalıştırır.
"""

import sys
import time
# Yeni hali:
from src.data.preprocessing import run_preprocessing
from src.data.build_database_and_eda import initialize_database
from src.forecasting.train_forecast import run_forecast_benchmark
from src.planning.aggregate_planning import run_planning_pipeline
from src.inventory.bom_mrp import run_mrp_engine
from src.scheduling.schedule_cpsat import solve_cpsat_schedule
from src.energy.energy_analytics import compute_energy_analytics
from src.carbon.carbon_analytics import compute_carbon_analytics

def run_end_to_end_pipeline():
    start_total = time.time()
# Aşama 8: Industrial Decision Lineage & Audit Trail Kaydı
    meta = record_pipeline_run_metadata()
    print(f"\n[AUDIT] Run metadata kaydedildi -> reports/run_metadata.json (Run ID: {meta['run_id']}, Git: {meta['git_sha'][:7]})")
    print("\n" + "#" * 85)
    print("      FABRİKA KARAR DESTEK PLATFORMU: UÇTAN UCA ENTEGRE ÇALIŞTIRMA      ")
    print("#" * 85 + "\n")

    steps = [
        ("Aşama 1: Veri Ön İşleme & Temizlik", run_preprocessing),
        ("Aşama 2: SQLite Veritabanı Kurulumu", initialize_database),
        ("Aşama 3: ML Talep Tahmini (LightGBM)", run_forecast_benchmark),
        ("Aşama 4: Hiyerarşik Taktik Planlama & SKU Ayrıştırma", run_planning_pipeline),
        ("Aşama 5: Malzeme İhtiyaç Planlaması (MRP-I)", run_mrp_engine),
        ("Aşama 6: Detaylı Çizelgeleme (Google OR-Tools CP-SAT)", solve_cpsat_schedule),
        ("Aşama 7A: Enerji Analitiği & Yük Profili", compute_energy_analytics),
        ("Aşama 7B: Kurumsal Karbon Muhasebesi (GHG Protocol)", compute_carbon_analytics),
    ]

    for idx, (name, func) in enumerate(steps, 1):
        step_start = time.time()
        print(f"\n>>> [{idx}/{len(steps)}] {name} başlatılıyor...")
        func()
        elapsed = time.time() - step_start
        print(f">>> [OK] {name} tamamlandı ({elapsed:.2f} sn).\n")

    total_time = time.time() - start_total
    print("#" * 85)
    print(f" TÜM ENTEGRE PIPELINE BAŞARIYLA TAMAMLANDI! Toplam Süre: {total_time:.2f} saniye")
    print("#" * 85 + "\n")

if __name__ == "__main__":
    run_end_to_end_pipeline()
from src.utils.lineage import record_pipeline_run_metadata
