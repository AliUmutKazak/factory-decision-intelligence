
    from src import config
    from src.config import get_runtime_paths

    active_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    root_dir = Path(__file__).resolve().parent.parent.parent

    # Runtime path is authoritative; validation must never read canonical reports
    # while an isolated staging environment is active.
    if reports_dir:
        resolved_reports_dir = Path(reports_dir)
    elif os.environ.get("FACTORY_REPORTS_DIR"):
        resolved_reports_dir = Path(os.environ["FACTORY_REPORTS_DIR"])
    elif db_path:
        resolved_reports_dir = Path(db_path).parent / "reports"
    else:
        resolved_reports_dir = Path(get_runtime_paths()["reports_dir"])

    conn = get_db_connection(active_db)
    try:
        cur = conn.cursor()

        # 1. SAME RUN: validate only the requested run; historical rows are allowed.
        tables_to_check = [
            "production_schedule", "energy_kpis", "energy_machine_kpis",
            "carbon_kpis", "carbon_machine_kpis", "carbon_price_scenarios",
            "forecast_demand", "forecast_model_lineage",
            "sku_production_plan", "aggregate_plan", "machine_capacity_plan", "mrp_plan",
        ]
        for tbl in tables_to_check:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (tbl,))
            if not cur.fetchone():
                raise ValueError(f"[VALIDATION GATE FAIL] Gerekli tablo yok: {tbl}")
            cur.execute(f"PRAGMA table_info({tbl})")
            cols = [r[1] for r in cur.fetchall()]
            if "run_id" not in cols:
                raise ValueError(f"[VALIDATION GATE FAIL] {tbl} run_id kolonu olmadan kabul edilemez.")
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE run_id = ?", (run_id,))
            if cur.fetchone()[0] == 0:
                raise ValueError(f"[VALIDATION GATE FAIL] {tbl} için {run_id} verisi yok.")
        # 2. MATH: SKU Mutabakatı & Miktar Korunumu
        sched_df = pd.read_sql("SELECT lot_id, product_id, production_units FROM production_schedule", conn)
        sku_plan_df = pd.read_sql(
            "SELECT product_id, planned_units FROM sku_production_plan WHERE period_week = 1", conn
        )

        if not sched_df.empty and not sku_plan_df.empty:
            unique_lots = sched_df.drop_duplicates(subset=["lot_id"])
            s_agg = unique_lots.groupby("product_id")["production_units"].sum()
            p_agg = sku_plan_df.groupby("product_id")["planned_units"].sum()

            for pid, p_val in p_agg.items():
                s_val = s_agg.get(pid, 0.0)
                if abs(p_val - s_val) > 1e-4:
                    raise ValueError(
                        f"[VALIDATION GATE FAIL] SKU Mutabakatı Bozuldu! Ürün: {pid}, "
                        f"W1 Planlanan: {p_val}, Çizelgelenen (Tekil Lot): {s_val}"
                    )

        # 3. PHYSICS: Aynı Tezgahta Sıfır Zaman Çakışması & OT Bütçesi
        sched_full = pd.read_sql("SELECT * FROM production_schedule", conn)
        if not sched_full.empty:
            for m_id, m_df in sched_full.groupby("machine_id"):
                m_sorted = m_df.sort_values(by="start_min").reset_index(drop=True)
                for i in range(len(m_sorted) - 1):
                    current_end = m_sorted.loc[i, "end_min"]
                    next_start = m_sorted.loc[i + 1, "start_min"]
                    if next_start < current_end - 1e-4:
                        raise ValueError(
                            f"[VALIDATION GATE FAIL] Fiziksel Kısıt İhlali: {m_id} tezgahında zaman çakışması! "
                            f"Görev {m_sorted.loc[i, 'lot_id']} bitiş: {current_end}, "
                            f"Görev {m_sorted.loc[i + 1, 'lot_id']} başlangıç: {next_start}"
                        )

            # -----------------------------------------------------------------
            # MADDE 18: Machine x Week Bazlı Operasyonel Overtime Validation
            # -----------------------------------------------------------------
            # Global eşik (total_ot > 60000) yerine tezgâh ve hafta bazlı katı kural
            weekly_acc_path = Path(os.environ.get("FACTORY_PROCESSED_DIR", str(get_runtime_paths()["processed_dir"]))) / "task_weekly_accounting.csv"
            allowed_w1_ot_min_by_machine = {"M01": 48 * 60}  # M01 W1 tavanı: 48h = 2880 dk

            if weekly_acc_path.exists():
                try:
                    w_df = pd.read_csv(weekly_acc_path)
                    if not w_df.empty and "machine_id" in w_df.columns and "week_index" in w_df.columns:
                        ot_metric_col = next(
                            (c for c in ["overtime_minutes", "ot_minutes", "overtime_min"] if c in w_df.columns), None
                        )
                        if ot_metric_col:
                            for (m_id, w_idx), grp in w_df.groupby(["machine_id", "week_index"]):
                                grp_ot = grp[ot_metric_col].sum()
                                if w_idx == 0:
                                    max_allowed = allowed_w1_ot_min_by_machine.get(str(m_id), 0)
                                    if grp_ot > max_allowed:
                                        raise ValueError(
                                            f"[VALIDATION GATE FAIL] Tezgâh Hafta-1 OT Aşıldı! "
                                            f"Tezgâh: {m_id}, Fiili OT: {grp_ot} dk, İzin Verilen: {max_allowed} dk"
                                        )
                                else:
                                    # Hafta 2 ve sonrası (Spillover): Model A politikası gereği OT = 0 olmalıdır
                                    if grp_ot > 0:
                                        raise ValueError(
                                            f"[VALIDATION GATE FAIL] Spillover Döneminde (Hafta {w_idx + 1}) Yetkisiz OT! "
                                            f"Tezgâh: {m_id}, Fiili OT: {grp_ot} dk (Maksimum: 0 dk)"
                                        )
                except Exception as e:
                    if "[VALIDATION GATE FAIL]" in str(e):
                        raise
            else:
                # Yedek kontrol (fallback): production_schedule üzerindeki tezgâh toplamları
                ot_col = (
                    "overtime_minutes"
                    if "overtime_minutes" in sched_full.columns
                    else ("overtime_min" if "overtime_min" in sched_full.columns else None)
                )
                if ot_col:
                    for m_id, grp in sched_full.groupby("machine_id"):
                        m_ot = grp[ot_col].sum()
                        max_allowed = allowed_w1_ot_min_by_machine.get(str(m_id), 0)
                        if m_ot > max_allowed:
                            raise ValueError(
                                f"[VALIDATION GATE FAIL] Tezgâh Toplam OT Sınırı Aşıldı! "
                                f"Tezgâh: {m_id}, Fiili OT: {m_ot} dk, İzin Verilen: {max_allowed} dk"
                            )

        # 3.1. ENERJİ MUTABAKATI: Tesis Toplamı == Tezgah Toplamları
        cur.execute("PRAGMA table_info(energy_kpis)")
        e_cols = [r[1] for r in cur.fetchall()]
        cur.execute("PRAGMA table_info(energy_machine_kpis)")
        em_cols = [r[1] for r in cur.fetchall()]
        if e_cols and em_cols:
            energy_kpi = pd.read_sql("SELECT * FROM energy_kpis", conn)
            machine_kpi = pd.read_sql("SELECT * FROM energy_machine_kpis", conn)
            if not energy_kpi.empty and not machine_kpi.empty:
                # energy_kpis tablosunda tesis toplam kWh: grand_total_kwh
                e_col_name = (
                    "grand_total_kwh"
                    if "grand_total_kwh" in energy_kpi.columns
                    else ("total_kwh" if "total_kwh" in energy_kpi.columns else None)
                )
                m_col_name = (
                    "total_kwh"
                    if "total_kwh" in machine_kpi.columns
                    else ("grand_total_kwh" if "grand_total_kwh" in machine_kpi.columns else None)
                )

                if e_col_name and m_col_name:
                    e_tot = float(energy_kpi[e_col_name].iloc[0])
                    m_tot = float(machine_kpi[m_col_name].sum())
                    if abs(e_tot - m_tot) > 0.5:
                        raise ValueError(
                            f"[VALIDATION GATE FAIL] Enerji Korunum Dengesizliği: Tesis={e_tot:.2f} kWh != Tezgahlar={m_tot:.2f} kWh"
                        )
