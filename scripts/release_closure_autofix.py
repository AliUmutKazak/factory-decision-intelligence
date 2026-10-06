"""One-shot release-closure semantic fixer.

Temporary migration helper. It is removed once release verification is green.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old in text:
        write(path, text.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    text = read(path)
    start_index = text.find(start)
    end_index = text.find(end, start_index + len(start)) if start_index >= 0 else -1
    if start_index < 0 or end_index < 0:
        return
    write(path, text[:start_index] + replacement + text[end_index:])


def ensure_before(path: str, anchor: str, insertion: str) -> None:
    text = read(path)
    if insertion.strip() in text:
        return
    if anchor not in text:
        raise RuntimeError(f"Anchor not found in {path}: {anchor!r}")
    write(path, text.replace(anchor, insertion + anchor, 1))


def ensure_after(path: str, anchor: str, insertion: str) -> None:
    text = read(path)
    if insertion.strip() in text:
        return
    if anchor not in text:
        raise RuntimeError(f"Anchor not found in {path}: {anchor!r}")
    write(path, text.replace(anchor, anchor + insertion, 1))


def fix_energy() -> None:
    replace_once(
        "src/energy/energy_analytics.py",
        '         kpi_df["run_id"] = run_id',
        '        kpi_df["run_id"] = run_id',
    )
    old = """    weekly_machine_ot_hours = {}
    try:
        conn = get_db_connection(active_db_path)
        cap_df = pd.read_sql("SELECT period_week, machine_id, overtime_hours FROM machine_capacity_plan", conn)
        conn.close()
        for _, r in cap_df.iterrows():
            weekly_machine_ot_hours[(int(r["period_week"]), str(r["machine_id"]))] = float(r["overtime_hours"])
    except Exception:
        pass
"""
    new = """    weekly_machine_ot_hours = {}
    with get_db_connection(active_db_path) as conn:
        cap_df = pd.read_sql(
            "SELECT period_week, machine_id, overtime_hours "
            "FROM machine_capacity_plan WHERE run_id = ?",
            conn,
            params=(str(run_id),),
        )
    if cap_df.empty:
        raise RuntimeError(
            f"[ENERGY] machine_capacity_plan bulunamadı for run_id={run_id}."
        )
    for _, row in cap_df.iterrows():
        weekly_machine_ot_hours[(int(row["period_week"]), str(row["machine_id"]))] = float(
            row["overtime_hours"]
        )
"""
    replace_once("src/energy/energy_analytics.py", old, new)


def fix_service_level() -> None:
    ensure_before(
        "src/scheduling/service_level.py",
        "import pandas as pd\n",
        "from src.config import ECONOMIC_CONFIG\n\n",
    )
    replace_once(
        "src/scheduling/service_level.py",
        "# Varsayılan dakika başı gecikme maliyeti (TL/dk veya $/dk)\nDEFAULT_TARDINESS_COST_PER_MIN = 2.50",
        "# Economic SSOT: configured currency per tardy minute.\n"
        "DEFAULT_TARDINESS_COST_PER_MIN = ECONOMIC_CONFIG.tardiness_cost_per_hour / 60.0",
    )


def fix_scheduler_imports() -> None:
    ensure_before(
        "src/scheduling/schedule_cpsat.py",
        "from src.utils.db import",
        "from src.scheduling.calendar_service import MachineCalendarService\n"
        "from src.scheduling.maintenance import load_machine_maintenance_windows\n",
    )


def fix_orders_history() -> None:
    replace_once(
        "src/data/build_database_and_eda.py",
        '    cursor.execute("DELETE FROM orders;")\n    conn.commit()',
        """    if run_id:
        cursor.execute("DELETE FROM orders WHERE run_id = ?", (str(run_id),))
    else:
        cursor.execute("DELETE FROM orders")
    conn.commit()""",
    )


def fix_validation_and_retention() -> None:
    ensure_after(
        "src/utils/lineage.py",
        "from pathlib import Path\n\n",
        "from src import config\n",
    )

    ot_start = "            # -----------------------------------------------------------------\n            # MADDE 18: Machine x Week Bazlı Operasyonel Overtime Validation"
    ot_end = "        # 3.1. ENERJİ MUTABAKATI"
    ot_block = """            # MADDE 18: DB-backed machine x week overtime validation.
            cap_df = pd.read_sql(
                "SELECT machine_id, overtime_hours FROM machine_capacity_plan "
                "WHERE run_id = ? AND period_week = 1",
                conn,
                params=(run_id,),
            )
            allowed_w1_ot_min = {
                str(row["machine_id"]): float(row["overtime_hours"]) * 60.0
                for _, row in cap_df.iterrows()
            }
            ot_col = "overtime_minutes" if "overtime_minutes" in sched_full.columns else None
            if ot_col:
                week_col = "schedule_week" if "schedule_week" in sched_full.columns else None
                if week_col:
                    for (machine_id, week_index), group in sched_full.groupby(
                        ["machine_id", week_col]
                    ):
                        processing_ot = float(group[ot_col].sum())
                        setup_ot = (
                            float(group["setup_overtime_minutes"].sum())
                            if "setup_overtime_minutes" in group.columns
                            else 0.0
                        )
                        actual_ot = processing_ot + setup_ot
                        if int(week_index) == 1:
                            budget = allowed_w1_ot_min.get(str(machine_id), 0.0)
                            if actual_ot > budget + 1e-6:
                                raise ValueError(
                                    f"[VALIDATION GATE FAIL] W1 OT aşıldı: {machine_id} "
                                    f"{actual_ot:.1f} dk > {budget:.1f} dk"
                                )
                        elif actual_ot > 1e-6:
                            raise ValueError(
                                f"[VALIDATION GATE FAIL] Spillover OT yasak: "
                                f"{machine_id}, W{week_index}={actual_ot:.1f} dk"
                            )

"""
    replace_between("src/utils/lineage.py", ot_start, ot_end, ot_block)

    retention_start = "def apply_run_retention_policy("
    retention_end = "def generate_run_manifest("
    retention = '''def apply_run_retention_policy(
    keep_last_n: int = 20,
    db_path: str = None,
    artifacts_dir: str = None,
) -> int:
    """Delete old run versions transactionally while always preserving ACTIVE."""
    import shutil

    if keep_last_n < 1:
        raise ValueError("keep_last_n en az 1 olmalıdır.")

    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or str(
        get_runtime_paths()["db_path"]
    )
    if not os.path.exists(active_db):
        return 0

    conn = get_db_connection(active_db)
    init_pipeline_runs_table(conn)
    cur = conn.cursor()
    active_ids = {
        row[0]
        for row in cur.execute(
            "SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE'"
        ).fetchall()
    }
    keep_non_active = max(0, keep_last_n - len(active_ids))
    old_runs = [
        row[0]
        for row in cur.execute(
            "SELECT run_id FROM pipeline_runs WHERE status != 'ACTIVE' "
            "ORDER BY timestamp DESC LIMIT -1 OFFSET ?",
            (keep_non_active,),
        ).fetchall()
    ]

    if old_runs:
        placeholders = ",".join("?" for _ in old_runs)
        run_scoped_tables = [
            "orders",
            "forecast_demand",
            "forecast_model_lineage",
            "aggregate_plan",
            "sku_production_plan",
            "machine_capacity_plan",
            "mrp_plan",
            "production_schedule",
            "schedule_solver_metadata",
            "energy_kpis",
            "energy_profile_15min",
            "energy_machine_kpis",
            "carbon_kpis",
            "carbon_machine_kpis",
            "carbon_price_scenarios",
            "machine_state_snapshot",
            "mes_order_tracking",
            "mes_execution_events",
            "input_source_lineage",
            "decision_ledger",
        ]
        try:
            conn.execute("BEGIN")
            for table_name in run_scoped_tables:
                exists = cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                    (table_name,),
                ).fetchone()
                if not exists:
                    continue
                columns = {
                    row[1]
                    for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()
                }
                if "run_id" in columns:
                    cur.execute(
                        f"DELETE FROM {table_name} WHERE run_id IN ({placeholders})",
                        old_runs,
                    )
            if cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reschedule_audit_log'"
            ).fetchone():
                cur.execute(
                    f"DELETE FROM reschedule_audit_log "
                    f"WHERE new_run_id IN ({placeholders}) "
                    f"OR previous_run_id IN ({placeholders})",
                    old_runs + old_runs,
                )
            cur.execute(
                f"DELETE FROM pipeline_runs WHERE run_id IN ({placeholders})",
                old_runs,
            )
            deleted_count = cur.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
    else:
        deleted_count = 0

    target_artifacts = (
        Path(artifacts_dir)
        if artifacts_dir
        else Path(get_runtime_paths()["base_dir"]) / "artifacts" / "runs"
    )
    for old_run_id in old_runs:
        old_dir = target_artifacts / old_run_id
        if old_dir.exists() and old_dir.is_dir():
            shutil.rmtree(old_dir)

    conn.close()
    return deleted_count


'''
    replace_between("src/utils/lineage.py", retention_start, retention_end, retention)


def fix_main_bundle() -> None:
    ensure_before(
        "main.py",
        "from src.utils.lineage import (",
        "from src.utils.run_bundle import seal_run_bundle\n",
    )
    replace_once(
        "main.py",
        '                bundle_manifest = bundle_reports / "run_manifest.json"\n'
        "                if bundle_manifest.exists():\n"
        '                    shutil.copy2(bundle_manifest, run_artifacts_dir / "manifest.json")\n'
        '                print(f"[AUDIT] P0-3 Run Isolation tamamlandı: {run_artifacts_dir}")',
        '                seal_run_bundle(run_artifacts_dir, run_id, run_type="PIPELINE")\n'
        '                print(f"[AUDIT] Run bundle mühürlendi: {run_artifacts_dir}")',
    )
    replace_once(
        "main.py",
        '                cur.execute("SELECT COUNT(*) FROM orders")\n                row = cur.fetchone()',
        '                cur.execute("SELECT COUNT(*) FROM orders WHERE run_id = ?", (run_id,))\n'
        "                row = cur.fetchone()",
    )
    old = """        # 2. P0.4: Mutlak En Son Atomik İşlem -> CANONICAL DB Üzerinde ACTIVE Promosyonu
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
"""
    new = """        # Retention canonical DB ve immutable run bundle üzerinde, ACTIVE
        # promotion'dan önce tamamlanır. Hata olursa eski ACTIVE değişmeden kalır.
        apply_run_retention_policy(
            keep_last_n=20,
            db_path=str(canonical_db),
            artifacts_dir=str(base_dir / "artifacts" / "runs"),
        )

        # Final critical state transition. Schedule/data mutation does not occur
        # after this point; ACTIVE is the authoritative production pointer.
        promote_run_to_active(run_id=run_id, db_path=str(canonical_db))
"""
    replace_once("main.py", old, new)


def main() -> None:
    fix_energy()
    fix_service_level()
    fix_scheduler_imports()
    fix_orders_history()
    fix_validation_and_retention()
    fix_main_bundle()


if __name__ == "__main__":
    main()
