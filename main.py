"""
Factory Decision Intelligence Platform - Master Pipeline Orchestrator
----------------------------------------------------------------------
Uçtan uca hiyerarşik üretim planlama, detaylı çizelgeleme,
malzeme gereksinim planlaması, enerji ve karbon muhasebesi zincirini çalıştırır.
"""

import os
import shutil
import sys
import time
from pathlib import Path

from src.carbon.carbon_analytics import compute_carbon_analytics
from src.data.build_database_and_eda import initialize_database
from src.data.preprocessing import run_preprocessing
from src.energy.energy_analytics import compute_energy_analytics
from src.forecasting.train_forecast import run_forecast_benchmark
from src.inventory.bom_mrp import run_mrp_engine
from src.planning.aggregate_planning import run_planning_pipeline
from src.scheduling.schedule_cpsat import solve_cpsat_schedule
from src.utils.lineage import (
    apply_run_retention_policy,
    generate_run_id,
    generate_run_manifest,
    init_pipeline_runs_table,
    promote_run_to_active,
    record_pipeline_run_metadata,
    start_pipeline_run,
    update_pipeline_run_status,
    validate_pipeline_run,
)


def run_end_to_end_pipeline():
    run_id = generate_run_id()
    print("\n" + "#" * 85)
    print(f"      FABRİKA KARAR DESTEK PLATFORMU: PIPELINE BAŞLATILDI (Run ID: {run_id})")
    print("#" * 85 + "\n")

    # Test ve çalışma ortamı izolasyonu (CWD öncelikli)
    base_dir = Path.cwd() if (Path.cwd() / "data").exists() else Path(__file__).resolve().parent
    canonical_db = Path(os.environ.get("FACTORY_CANONICAL_DB", base_dir / "data" / "factory.db"))
    staging_dir = base_dir / "runs" / run_id
    staging_db = staging_dir / f"factory_staging_{run_id}.db"
    staging_processed = staging_dir / "data" / "processed"
    staging_reports = staging_dir / "reports"

    staging_processed.mkdir(parents=True, exist_ok=True)
    staging_reports.mkdir(parents=True, exist_ok=True)

    # Mevcut kanonik DB varsa metadata ve baz tablolar için staging'e başlangıç kopyası al
    if canonical_db.exists():
        shutil.copy2(canonical_db, staging_db)

    # Pipeline boyunca tüm modüllerin izole staging ortamına yazmasını sağla
    os.environ["FACTORY_DB_PATH"] = str(staging_db)
    os.environ["FACTORY_PROCESSED_DIR"] = str(staging_processed)
    os.environ["FACTORY_REPORTS_DIR"] = str(staging_reports)

    # Staging üzerinde koşumu başlat ve RUNNING durumuna al
    start_pipeline_run(run_id=run_id, db_path=str(staging_db))
    update_pipeline_run_status(run_id=run_id, status="RUNNING", db_path=str(staging_db))

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

        # 1. AŞAMA: STAGING
        update_pipeline_run_status(run_id=run_id, status="STAGING", db_path=str(staging_db))
        print(f"[AUDIT] Pipeline durumu: STAGING ({run_id})")

        # 2. AŞAMA: VALIDATE (Master Operational Gate)
        update_pipeline_run_status(run_id=run_id, status="VALIDATE", db_path=str(staging_db))
        print(f"[AUDIT] Pipeline durumu: VALIDATE ({run_id})")

        # Validation Gate dosya kontrolü yapmadan önce güncel run_id'yi metadata dosyasına yaz
        record_pipeline_run_metadata(run_id=run_id, status="VALIDATE", db_path=str(staging_db))

        validate_pipeline_run(run_id=run_id, db_path=str(staging_db))
        print("[AUDIT] Doğrulama başarılı: Matematiksel ve operasyonel veri bütünlüğü onaylandı.")

        # VALIDATE -> COMPLETED geçişi State Machine üzerinden yürütülür
        update_pipeline_run_status(run_id=run_id, status="COMPLETED", db_path=str(staging_db))
        print(f"[AUDIT] Pipeline durumu: COMPLETED ({run_id})")

        # 3. AŞAMA: SEAL ARTIFACTS (Promotion'dan ÖNCE tüm mühürleme ve denetim kayıtları tamamlanır!)
        print("[AUDIT] Artifacts & Metadata mühürleniyor (SEAL ARTIFACTS)...")

        # Gerçek sipariş sayısını staging veritabanından al
        actual_orders_count = 0
        try:
            from src.utils.db import get_db_connection

            with get_db_connection(str(staging_db)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM orders")
                row = cur.fetchone()
                if row:
                    actual_orders_count = row[0]
        except Exception:
            pass

        # Metadata kaydı (Sadece metadata alanlarını günceller, status değiştirmez)
        record_pipeline_run_metadata(
            run_id=run_id,
            orders_count=actual_orders_count,
            data_source="data/processed/factory_orders.csv",
            db_path=str(staging_db),
        )

        # Artifact Manifest Mühürleme (Dosyaların hash'leri ve parmak izi çıkarılır)
        manifest = generate_run_manifest(
            run_id=run_id, db_path=str(staging_db), input_source_path="data/processed/factory_orders.csv"
        )
        print(
            f"[AUDIT] Artifact Manifest mühürlendi -> reports/run_manifest.json ({manifest['total_artifacts']} dosya)"
        )

        # Environment değişkenlerini kaldır
        os.environ.pop("FACTORY_DB_PATH", None)
        os.environ.pop("FACTORY_PROCESSED_DIR", None)
        os.environ.pop("FACTORY_REPORTS_DIR", None)

        # Açık kalmış bağlantıları serbest bırak
        import gc

        gc.collect()
        time.sleep(0.5)

        # 1. Fiziksel Atomic Replacement: Staging DB & Artifacts -> Canonical Store
        max_retries = 5
        promoted = False
        for attempt in range(max_retries):
            try:
                shutil.copy2(staging_db, canonical_db)

                # Başarılı koşan koşumun artifact'lerini kanonik dizinlere terfi ettir (promote)
                canonical_processed = base_dir / "data" / "processed"
                canonical_reports = base_dir / "reports"
                canonical_processed.mkdir(parents=True, exist_ok=True)
                canonical_reports.mkdir(parents=True, exist_ok=True)

                if staging_processed.exists():
                    for item in staging_processed.glob("*.*"):
                        shutil.copy2(item, canonical_processed / item.name)

                if staging_reports.exists():
                    for item in staging_reports.glob("*.*"):
                        shutil.copy2(item, canonical_reports / item.name)

                # Immutable run bundle: source is staging only. Canonical caches
                # are never mixed into the historical run snapshot.
                run_artifacts_dir = base_dir / "artifacts" / "runs" / run_id
                run_artifacts_dir.mkdir(parents=True, exist_ok=True)

                if staging_db.exists():
                    shutil.copy2(staging_db, run_artifacts_dir / "factory.db")

                bundle_processed = run_artifacts_dir / "data" / "processed"
                bundle_reports = run_artifacts_dir / "reports"
                shutil.copytree(staging_processed, bundle_processed, dirs_exist_ok=True)
                shutil.copytree(staging_reports, bundle_reports, dirs_exist_ok=True)

                bundle_manifest = bundle_reports / "run_manifest.json"
                if bundle_manifest.exists():
                    shutil.copy2(bundle_manifest, run_artifacts_dir / "manifest.json")
                print(f"[AUDIT] P0-3 Run Isolation tamamlandı: {run_artifacts_dir}")

                promoted = True
                break
            except PermissionError:
                gc.collect()
                time.sleep(1.0)

        if not promoted:
            temp_target = canonical_db.with_suffix(f".tmp_{run_id}")
            shutil.copy2(staging_db, temp_target)
            if canonical_db.exists():
                try:
                    canonical_db.unlink()
                except PermissionError:
                    pass
            temp_target.replace(canonical_db)

        # 2. P0.4: Mutlak En Son Atomik İşlem -> CANONICAL DB Üzerinde ACTIVE Promosyonu
        # Kanonik DB tamamen diske oturduktan sonra tek bir atomik UPDATE ile ACTIVE yapılır.
        # Bu adımın arkasından hata verebilecek HİÇBİR I/O veya operasyon çalıştırılmaz.
        promote_run_to_active(run_id=run_id, db_path=str(canonical_db))

        # Retention only after successful promotion; staging must never mutate
        # canonical historical artifacts.
        apply_run_retention_policy(
            keep_last_n=20,
            db_path=str(canonical_db),
            artifacts_dir=str(base_dir / "artifacts" / "runs"),
        )

        # Staging dosyasını temizle (Başarısız olsa dahi pipeline'ı etkilemez)
        if staging_db.exists():
            try:
                staging_db.unlink()
            except Exception:
                pass

        print(f"[AUDIT] Atomic Run Promotion başarılı: {run_id} -> ACTIVE (data/factory.db güncellendi)")
        print("\n" + "#" * 85)
        print(f" TÜM ENTEGRE PIPELINE BAŞARIYLA TAMAMLANDI | Süre: {total_elapsed:.2f} saniye")
        print("#" * 85 + "\n")

        return True

    except Exception as exc:
        print(f"\n[CRITICAL PIPELINE FAILURE] Aşama hatası: {str(exc)}", file=sys.stderr)
        os.environ.pop("FACTORY_DB_PATH", None)
        os.environ.pop("FACTORY_PROCESSED_DIR", None)
        os.environ.pop("FACTORY_REPORTS_DIR", None)

        # Hata anında staging DB ve izole staging klasörü temizlenir, kanonik DB/dosyalara dokunulmaz!
        if staging_dir.exists():
            try:
                shutil.rmtree(staging_dir, ignore_errors=True)
            except Exception:
                pass

        # Record failure on canonical control DB without touching active run data.
        try:
            from src.utils.db import get_db_connection

            with get_db_connection(str(canonical_db)) as conn:
                init_pipeline_runs_table(conn)
                cur = conn.cursor()
                cur.execute(
                    "SELECT status FROM pipeline_runs WHERE run_id = ?",
                    (run_id,),
                )
                existing = cur.fetchone()
                if existing is None:
                    cur.execute(
                        "INSERT INTO pipeline_runs (run_id, timestamp, trigger_source, status) "
                        "VALUES (?, datetime('now'), 'pipeline_execution', 'INITIALIZED')",
                        (run_id,),
                    )
                    conn.commit()
                update_pipeline_run_status(run_id, "FAILED", db_path=str(canonical_db))
        except Exception as failure_audit_exc:
            print(f"[WARN] Failure audit kaydı yazılamadı: {failure_audit_exc}", file=sys.stderr)

        raise exc


if __name__ == "__main__":
    run_end_to_end_pipeline()
