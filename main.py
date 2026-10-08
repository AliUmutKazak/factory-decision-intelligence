"""
Factory Decision Intelligence Platform - Master Pipeline Orchestrator
----------------------------------------------------------------------
Uçtan uca hiyerarşik üretim planlama, detaylı çizelgeleme,
malzeme gereksinim planlaması, enerji ve karbon muhasebesi zincirini çalıştırır.
"""

import os
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from src.carbon.carbon_analytics import compute_carbon_analytics
from src.config import runtime_path_context
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
from src.utils.run_bundle import export_run_database, seal_run_bundle, verify_run_bundle
from src.utils.runtime_lock import run_mutation_lock


def run_end_to_end_pipeline():
    base = Path.cwd() if (Path.cwd() / "data").exists() else Path(__file__).resolve().parent
    canonical = Path(os.environ.get("FACTORY_CANONICAL_DB", base / "data" / "factory.db"))
    run_id = generate_run_id()
    staging = base / "runs" / run_id
    with (
        run_mutation_lock(canonical),
        runtime_path_context(
            base_dir=base,
            data_dir=base / "data",
            db_path=staging / f"factory_staging_{run_id}.db",
            processed_dir=staging / "data" / "processed",
            reports_dir=staging / "reports",
        ),
    ):
        return _run_end_to_end_pipeline(run_id)


def _run_end_to_end_pipeline(run_id):
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
        with closing(sqlite3.connect(canonical_db)) as source, closing(sqlite3.connect(staging_db)) as target:
            source.backup(target)

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

        validate_pipeline_run(run_id=run_id, db_path=str(staging_db), reports_dir=str(staging_reports))
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
                cur.execute("SELECT COUNT(*) FROM orders WHERE run_id = ?", (run_id,))
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
            run_id=run_id, db_path=str(staging_db), input_source_path=str(staging_processed / "factory_orders.csv")
        )
        print(
            f"[AUDIT] Artifact Manifest mühürlendi -> reports/run_manifest.json ({manifest['total_artifacts']} dosya)"
        )

        # Seal and verify the complete private bundle BEFORE the authoritative
        # canonical pointer can change. No canonical DB or cache is touched here.
        run_artifacts_dir = base_dir / "artifacts" / "runs" / run_id
        run_artifacts_dir.mkdir(parents=True, exist_ok=False)
        export_run_database(staging_db, run_artifacts_dir / "factory.db", run_id)
        shutil.copytree(staging_processed, run_artifacts_dir / "data" / "processed")
        shutil.copytree(staging_reports, run_artifacts_dir / "reports")
        seal_run_bundle(run_artifacts_dir, run_id, run_type="PIPELINE")
        verify_run_bundle(run_artifacts_dir, run_id)

        # ACTIVE and ARCHIVED are switched inside the private staging database.
        # Publishing a complete DB through same-filesystem os.replace is the
        # single commit point; a failed seal/promotion leaves the old DB intact.
        promote_run_to_active(run_id=run_id, db_path=str(staging_db))
        canonical_db.parent.mkdir(parents=True, exist_ok=True)
        pending_db = canonical_db.with_name(f".{canonical_db.name}.{run_id}.tmp")
        try:
            with closing(sqlite3.connect(staging_db)) as source, closing(sqlite3.connect(pending_db)) as target:
                source.backup(target)
            os.replace(pending_db, canonical_db)
        finally:
            pending_db.unlink(missing_ok=True)

        # Compatibility caches are derived from the sealed run. Cache/retention
        # failures after publication cannot turn a committed ACTIVE run into a
        # reported pipeline failure or erase the prior version.
        try:
            for source_dir, target_dir in (
                (staging_processed, base_dir / "data" / "processed"),
                (staging_reports, base_dir / "reports"),
            ):
                target_dir.mkdir(parents=True, exist_ok=True)
                for item in source_dir.glob("*.*"):
                    shutil.copy2(item, target_dir / item.name)
            apply_run_retention_policy(
                keep_last_n=20,
                db_path=str(canonical_db),
                artifacts_dir=str(base_dir / "artifacts" / "runs"),
            )
        except Exception as cache_error:
            print(f"[CACHE] ACTIVE run committed; cache/retention refresh failed: {cache_error}")

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
    # Keep report output legible on Windows consoles with a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    run_end_to_end_pipeline()
