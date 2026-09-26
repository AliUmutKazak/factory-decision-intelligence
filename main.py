"""
Factory Decision Intelligence Platform - Master Pipeline Orchestrator
----------------------------------------------------------------------
Uçtan uca hiyerarşik üretim planlama, detaylı çizelgeleme,
malzeme gereksinim planlaması, enerji ve karbon muhasebesi zincirini çalıştırır.
"""

import os
import sys
import time
import shutil
from pathlib import Path

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
    apply_run_retention_policy,
    generate_run_manifest,
    promote_run_to_active,
    update_pipeline_run_status,
    validate_pipeline_run,
    init_pipeline_runs_table
)


def run_end_to_end_pipeline():
    run_id = generate_run_id()
    print("\n" + "#" * 85)
    print(f"      FABRİKA KARAR DESTEK PLATFORMU: PIPELINE BAŞLATILDI (Run ID: {run_id})")
    print("#" * 85 + "\n")

    base_dir = Path(__file__).resolve().parent
    canonical_db = base_dir / "data" / "factory.db"
    staging_dir = base_dir / "data" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_db = staging_dir / f"factory_staging_{run_id}.db"

    # Mevcut kanonik DB varsa metadata ve baz tablolar için staging'e başlangıç kopyası al
    if canonical_db.exists():
        shutil.copy2(canonical_db, staging_db)

    # Pipeline boyunca tüm modüllerin izole staging DB'ye yazmasını sağla
    os.environ["FACTORY_DB_PATH"] = str(staging_db)

    # Staging üzerinde koşumu RUNNING olarak başlat
    start_pipeline_run(run_id=run_id, db_path=str(staging_db))

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

        # 1. Aşama: STAGING
        update_pipeline_run_status(run_id=run_id, status="STAGING", db_path=str(staging_db))
        print(f"[AUDIT] Pipeline durumu: STAGING ({run_id})")

        # 2. Aşama: VALIDATE
        update_pipeline_run_status(run_id=run_id, status="VALIDATE", db_path=str(staging_db))
        print(f"[AUDIT] Pipeline durumu: VALIDATE ({run_id})")
        validate_pipeline_run(run_id=run_id, db_path=str(staging_db))
        print(f"[AUDIT] Doğrulama başarılı: Matematiksel ve operasyonel veri bütünlüğü onaylandı.")

        # 3. Aşama: COMPLETED
        update_pipeline_run_status(run_id=run_id, status="COMPLETED", db_path=str(staging_db))
        print(f"[AUDIT] Pipeline durumu: COMPLETED ({run_id})")

        # 4. Aşama: ACTIVE (Atomic DB Promotion & State Transition)
        promote_run_to_active(run_id=run_id, db_path=str(staging_db))

        # Environment değişkenini kaldır
        os.environ.pop("FACTORY_DB_PATH", None)

        # Açık kalmış olabilecek SQLite bağlantı handle'larını serbest bırak
        import gc
        gc.collect()
        time.sleep(0.5)

        # Windows & OneDrive File-Lock Güvenli Atomic Replacement
        max_retries = 5
        promoted = False
        for attempt in range(max_retries):
            try:
                # Doğrudan staging dosyasını kanonik hedefe kopyala
                shutil.copy2(staging_db, canonical_db)
                promoted = True
                break
            except PermissionError:
                gc.collect()
                time.sleep(1.0)

        if not promoted:
            # Alternatif deneme: Geçici hedef üzerinden atomic replace
            temp_target = canonical_db.with_suffix(f".tmp_{run_id}")
            shutil.copy2(staging_db, temp_target)
            if canonical_db.exists():
                try:
                    canonical_db.unlink()
                except PermissionError:
                    pass
            temp_target.replace(canonical_db)

        # Staging dosyasını temizle
        if staging_db.exists():
            try:
                staging_db.unlink()
            except Exception:
                pass

        print(f"[AUDIT] Atomic Run Promotion başarılı: {run_id} -> ACTIVE (data/factory.db güncellendi)")

        # Gerçek sipariş sayısını veritabanından al
        actual_orders_count = 0
        try:
            from src.utils.db import get_db_connection
            with get_db_connection(str(canonical_db)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM orders")
                row = cur.fetchone()
                if row:
                    actual_orders_count = row[0]
        except Exception:
            pass

        # Denetim meta verisini kaydet
        meta = record_pipeline_run_metadata(
            run_id=run_id,
            status="ACTIVE",
            orders_count=actual_orders_count,
            data_source="data/processed/factory_orders.csv"
        )
        print(f"\n[AUDIT] Run metadata kaydedildi -> reports/run_metadata.json (Run ID: {meta['run_id']}, Status: ACTIVE, Orders: {actual_orders_count})")

        # Historical Run Retention
        pruned_count = apply_run_retention_policy(keep_last_n=20, db_path=str(canonical_db))
        if pruned_count > 0:
            print(f"[AUDIT] Retention Policy uygulandı: {pruned_count} adet eski denetim kaydı arşivlendi/temizlendi.")

        # Artifact Manifest Mühürleme
        manifest = generate_run_manifest(run_id=run_id)
        print(f"[AUDIT] Artifact Manifest oluşturuldu -> reports/run_manifest.json ({manifest['total_artifacts']} dosya mühürlendi)")

        print("\n" + "#" * 85)
        print(f" TÜM ENTEGRE PIPELINE BAŞARIYLA TAMAMLANDI! Toplam Süre: {total_elapsed:.2f} saniye")
        print("#" * 85 + "\n")

    except Exception as exc:
        print(f"\n[CRITICAL PIPELINE FAILURE] Aşama hatası: {str(exc)}", file=sys.stderr)
        os.environ.pop("FACTORY_DB_PATH", None)

        # Hata anında staging DB temizlenir, kanonik DB'ye dokunulmaz!
        if staging_db.exists():
            try:
                staging_db.unlink()
            except Exception:
                pass

        try:
            if canonical_db.exists():
                from src.utils.db import get_db_connection
                with get_db_connection(str(canonical_db)) as conn:
                    init_pipeline_runs_table(conn)
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT OR REPLACE INTO pipeline_runs (run_id, timestamp, status) VALUES (?, datetime('now'), 'FAILED')",
                        (run_id,)
                    )
            record_pipeline_run_metadata(run_id=run_id, status="FAILED")
        except Exception:
            pass

        raise exc


if __name__ == "__main__":
    run_end_to_end_pipeline()