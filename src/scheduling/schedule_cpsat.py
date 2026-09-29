import json
import os
from pathlib import Path

import pandas as pd
from ortools.sat.python import cp_model

import src.config as cfg
from src.config import (
    CPSAT_NUM_SEARCH_WORKERS,
    CPSAT_RANDOM_SEED,
    CPSAT_TIME_LIMIT_SECONDS,
    DB_PATH,
    SCHEDULING_WEIGHT_MAKESPAN,
    SCHEDULING_WEIGHT_SETUP,
)
from src.utils.db import get_db_connection


def get_initial_machine_states(conn) -> dict:
    """
    Denetim Madde 21: Tezgâh başlangıç durumunu öncelikle SQLite 'machine_state'
    (MES runtime snapshot) tablosundan okur. Tablo yoksa config.INITIAL_MACHINE_STATE'e düşer.
    """
    states = {}
    try:
        df_state = pd.read_sql("SELECT machine_id, last_product_id FROM machine_state", conn)
        for _, r in df_state.iterrows():
            states[str(r["machine_id"])] = str(r["last_product_id"])
    except Exception:
        pass

    if not states:
        states = getattr(cfg, "INITIAL_MACHINE_STATE", {})
    return states


def run_cpsat_scheduling(sku_plan=None, run_id=None):
    print("--- 4. CP-SAT Detaylı Çizelgeleme (Sıra Bağımlı Komşu Setup & MRP Kısıtları) ---")
    conn = get_db_connection(DB_PATH)
    machine_initial_states = get_initial_machine_states(conn)

    # Madde 30: Machine state run-scope snapshot mühürleme
    if run_id and machine_initial_states:
        try:
            snapshot_records = [
                {
                    "run_id": run_id,
                    "machine_id": m_id,
                    "last_product_id": p_id,
                    "state_timestamp": pd.Timestamp.now().isoformat(),
                    "source_system": "MES_DATABASE",
                }
                for m_id, p_id in machine_initial_states.items()
            ]
            pd.DataFrame(snapshot_records).to_sql("machine_state_snapshot", conn, if_exists="append", index=False)
        except Exception as e:
            print(f"[WARN] machine_state_snapshot kaydedilemedi: {e}")

    # 1. 1. Hafta SKU Planından Partileri Yükle
    if sku_plan is None:
        sku_plan = pd.read_sql("SELECT * FROM sku_production_plan WHERE period_week = 1", conn)
    routing_df = pd.read_sql("SELECT * FROM routing", conn)
    changeover_df = pd.read_sql("SELECT * FROM changeover_matrix", conn)
    bom_df = pd.read_sql("SELECT * FROM bom", conn)
    mrp_df = pd.read_sql("SELECT * FROM mrp_plan WHERE period_week = 1", conn)

    # -------------------------------------------------------------------------
    # OPERASYONEL POLİTİKA (Model A - Week-1 Finite Overtime Authorization):
    # Çizelgeleyici Hafta 1 iş yükünü çözer. Fazla mesai bütçesi taktik LP'den
    # yalnızca aktif yürütüm haftası (W1) için tahsis edilir.
    # W2+ taşma (spillover) döneminde ek gece fazla mesaisi kapalıdır.
    # -------------------------------------------------------------------------
    weekly_machine_ot_budget_min = {}
    machine_ot_hours = {}
    try:
        cap_df = pd.read_sql(
            "SELECT period_week, machine_id, overtime_hours FROM machine_capacity_plan WHERE period_week = 1", conn
        )
        for _, r in cap_df.iterrows():
            m_id = str(r["machine_id"])
            ot_h = float(r.get("overtime_hours", 0.0))
            machine_ot_hours[m_id] = ot_h
            weekly_machine_ot_budget_min[(1, m_id)] = ot_h * 60.0
    except Exception:
        weekly_machine_ot_budget_min = {}
        machine_ot_hours = {}

    # Denetim Madde 31: machine_calendar öncelikli, yoksa machines.max_daily_hours SSOT
    machine_daily_hours = {}
    try:
        cal_df = pd.read_sql(
            "SELECT machine_id, AVG(available_hours) as avg_hours FROM machine_calendar WHERE is_available = 1 GROUP BY machine_id",
            conn,
        )
        for _, r in cal_df.iterrows():
            machine_daily_hours[str(r["machine_id"])] = float(r["avg_hours"])
    except Exception:
        pass

    # Eksik kalan veya takvimde olmayan makineler için machines tablosuna fallback
    m_df = pd.read_sql("SELECT machine_id, max_daily_hours FROM machines", conn)
    for _, r in m_df.iterrows():
        mid = str(r["machine_id"])
        if mid not in machine_daily_hours:
            machine_daily_hours[mid] = float(r["max_daily_hours"])

    # Changeover matrisi dinamik okuma
    setup_dict = {}
    machines = routing_df["machine_id"].unique()

    # Sıkı Veri Sözleşmesi: Setup süresi doğrudan dakika cinsinden okunur (setup_time_min)
    f_col = (
        "from_product"
        if "from_product" in changeover_df.columns
        else [c for c in changeover_df.columns if "from" in c][0]
    )
    t_col = (
        "to_product" if "to_product" in changeover_df.columns else [c for c in changeover_df.columns if "to" in c][0]
    )

    if "setup_time_min" in changeover_df.columns:
        time_col = "setup_time_min"
    else:
        # Fallback: time içeren kolon veya ilk numerik olmayan f/t dışındaki kolon
        time_candidates = [c for c in changeover_df.columns if "time" in c]
        time_col = (
            time_candidates[0] if time_candidates else [c for c in changeover_df.columns if c not in (f_col, t_col)][0]
        )

    has_mid_col = "machine_id" in changeover_df.columns
    for _, row in changeover_df.iterrows():
        f_p = row[f_col]
        t_p = row[t_col]
        s_val = int(round(float(row[time_col])))
        row_mid = row["machine_id"] if has_mid_col and pd.notna(row.get("machine_id")) else None

        # Denetim Madde 22: Tezgâh bağımlı setup (machine_id, from_product, to_product)
        # Eğer makine belirtilmişse yalnızca o makineye, belirtilmemişse genel varsayılan olarak tüm makinelere atanır
        if row_mid and row_mid in machines:
            setup_dict[(row_mid, f_p, t_p)] = s_val
        else:
            for m in machines:
                # Makineye özel bir kural daha önce yazılmamışsa genel değeri uygula
                if (m, f_p, t_p) not in setup_dict:
                    setup_dict[(m, f_p, t_p)] = s_val

    # -------------------------------------------------------------
    # Madde 29: Closed-Loop MRP -> CP-SAT Endüstriyel Malzeme Mevcudiyeti Sözleşmesi
    # Availability = Open PO + Supplier Lead Time + Goods Receipt + QC Hold
    # r_lot = max_{m in BOM} t_availability,m
    # -------------------------------------------------------------
    # Endüstriyel parametre ayrımı (varsayılan ekspres operasyon dağılımı: 480 dk)
    DEFAULT_SUPPLIER_EXPEDITE_LT_MIN = 240  # Hızlandırılmış tedarikçi temin süresi
    DEFAULT_GOODS_RECEIPT_MIN = 120  # Mal kabul, boşaltma ve ERP girişi
    DEFAULT_QC_HOLD_MIN = 120  # Kalite kontrol / karantina onay süresi

    mat_availability = {}
    mat_availability_details = {}
    horizon_start_dt = pd.Timestamp("2018-01-01 08:00:00")  # Operasyonel takvim başlangıcı

    if "material_id" in mrp_df.columns and "action_message" in mrp_df.columns:
        w1_mrp = mrp_df[mrp_df["period_week"] == 1]
        for _, m_row in w1_mrp.iterrows():
            m_id = m_row["material_id"]
            action = str(m_row.get("action_message", ""))
            rel_week = int(m_row.get("planned_release_week", 1))

            if "EXPEDITE" in action:
                # Endüstriyel bileşenlerin toplamı: Open PO -> Supplier LT -> Goods Receipt -> QC Hold
                base_delay = DEFAULT_SUPPLIER_EXPEDITE_LT_MIN + DEFAULT_GOODS_RECEIPT_MIN + DEFAULT_QC_HOLD_MIN
                extra_week_delay = max(0, -rel_week) * 480
                total_delay_min = base_delay + extra_week_delay

                mat_availability[m_id] = total_delay_min
                mat_availability_details[m_id] = {
                    "open_po_expedited": True,
                    "supplier_lead_time_min": DEFAULT_SUPPLIER_EXPEDITE_LT_MIN + extra_week_delay,
                    "goods_receipt_min": DEFAULT_GOODS_RECEIPT_MIN,
                    "qc_hold_min": DEFAULT_QC_HOLD_MIN,
                    "material_available_min": total_delay_min,
                    "material_availability_datetime": (
                        horizon_start_dt + pd.Timedelta(minutes=total_delay_min)
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                }
            else:
                mat_availability[m_id] = 0
                mat_availability_details[m_id] = {
                    "open_po_expedited": False,
                    "supplier_lead_time_min": 0,
                    "goods_receipt_min": 0,
                    "qc_hold_min": 0,
                    "material_available_min": 0,
                    "material_availability_datetime": horizon_start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                }

    # Her SKU için BOM bileşenlerinin en geç varış anını (max availability) belirle
    sku_release_times = {}
    sku_material_datetimes = {}
    for pid in sku_plan["product_id"].unique():
        prod_materials = bom_df[bom_df["product_id"] == pid]["material_id"].unique()
        if len(prod_materials) > 0:
            max_rel = max(mat_availability.get(mid, 0) for mid in prod_materials)
            sku_release_times[pid] = max_rel
            sku_material_datetimes[pid] = (horizon_start_dt + pd.Timedelta(minutes=max_rel)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            sku_release_times[pid] = 0
            sku_material_datetimes[pid] = horizon_start_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Operasyonları Planlanan Partilere (planned_batches) Göre Oluştur
    # Lot Streaming / Transfer Batching desteği ile alt lot ayrıştırma
    tasks = []
    task_counter = 0
    batch_size = cfg.PRODUCTION_BATCH_SIZE
    enable_streaming = cfg.ENABLE_LOT_STREAMING
    max_sub_batches = cfg.MAX_SUB_LOT_BATCHES

    for _, row in sku_plan.iterrows():
        pid = row["product_id"]
        total_batches = int(row["planned_batches"])
        total_units = int(row["planned_units"])

        # SIFIR MİKTARLI HAYALET İŞLERİ ENGELLE
        if total_batches <= 0 or total_units <= 0:
            continue

        # Alt lot (sub-lot) paketlerini belirle
        sub_batches_list = []
        if enable_streaming and total_batches > max_sub_batches:
            rem = total_batches
            while rem > 0:
                alloc = min(rem, max_sub_batches)
                sub_batches_list.append(alloc)
                rem -= alloc
        else:
            sub_batches_list = [total_batches]

        lot_routings = routing_df[routing_df["product_id"] == pid].sort_values("operation_seq")

        for sub_idx, sub_b_qty in enumerate(sub_batches_list, start=1):
            sub_lot_id = f"LOT_{pid}_L{sub_idx}" if len(sub_batches_list) > 1 else f"LOT_{pid}"
            sub_units = sub_b_qty * batch_size

            for _, op in lot_routings.iterrows():
                seq = int(op["operation_seq"])
                mid = op["machine_id"]
                proc_time_per_batch = float(op["processing_time_min"])
                duration = int(round(sub_b_qty * proc_time_per_batch))

                tasks.append(
                    {
                        "task_id": task_counter,
                        "lot_id": sub_lot_id,
                        "parent_lot_id": f"LOT_{pid}",
                        "sub_lot_index": sub_idx,
                        "product_id": pid,
                        "batch_count": sub_b_qty,
                        "batch_size_units": batch_size,
                        "production_units": sub_units,
                        "operation_seq": seq,
                        "machine_id": mid,
                        "duration": duration,
                    }
                )
                task_counter += 1
    if not tasks:
        canonical_schedule_cols = [
            "task_id",
            "lot_id",
            "parent_lot_id",
            "sub_lot_index",
            "product_id",
            "operation_seq",
            "machine_id",
            "batch_count",
            "batch_size_units",
            "production_units",
            "duration_min",
            "start_min",
            "end_min",
            "regular_minutes",
            "overtime_minutes",
            "setup_before_min",
            "setup_start_min",
            "setup_end_min",
            "is_overtime",
            "calendar_shift",
            "release_time_min",
        ]
        empty_df = pd.DataFrame(columns=canonical_schedule_cols)
        empty_df["run_id"] = run_id if run_id else "DEFAULT_RUN"
        empty_df.to_sql("production_schedule", conn, if_exists="replace", index=False)
        os.makedirs("data/processed", exist_ok=True)
        empty_df.to_csv("data/processed/production_schedule.csv", index=False)
        return empty_df
    tasks_df = pd.DataFrame(tasks)

    # -------------------------------------------------------------
    # CP-SAT MODEL TANIMI
    # -------------------------------------------------------------
    model = cp_model.CpModel()
    # 7 Günlük Gerçek Takvim Ufku (168 saat = 10,080 dakika) ve iş yükü payı
    CALENDAR_HORIZON_MIN = 7 * 24 * 60
    horizon = int(max(CALENDAR_HORIZON_MIN, tasks_df["duration"].sum() + len(tasks_df) * 120 + 5000))

    all_tasks = {}
    machine_to_tasks = {}

    for _, t in tasks_df.iterrows():
        tid = t["task_id"]
        mid = t["machine_id"]
        dur = t["duration"]

        start_var = model.NewIntVar(0, horizon, f"start_{tid}")
        end_var = model.NewIntVar(0, horizon, f"end_{tid}")
        interval_var = model.NewIntervalVar(start_var, dur, end_var, f"interval_{tid}")

        all_tasks[tid] = {
            "start": start_var,
            "end": end_var,
            "interval": interval_var,
            "lot_id": t["lot_id"],
            "parent_lot_id": t.get("parent_lot_id", t["lot_id"]),
            "product_id": t["product_id"],
            "operation_seq": t["operation_seq"],
            "machine_id": t["machine_id"],
            "batch_count": t["batch_count"],
            "batch_size_units": t["batch_size_units"],
            "production_units": t["production_units"],
            "sub_lot_index": t.get("sub_lot_index", 0),
            "duration": t["duration"],
        }

        if mid not in machine_to_tasks:
            machine_to_tasks[mid] = []
        machine_to_tasks[mid].append(tid)

    # 1. Rota Öncelik Kısıtı (Precedence: Op 1 -> Op 2 -> Op 3)
    for lid, group in tasks_df.groupby("lot_id"):
        sorted_ops = group.sort_values("operation_seq")
        prev_tid = None
        for _, op in sorted_ops.iterrows():
            curr_tid = op["task_id"]
            if prev_tid is not None:
                model.Add(all_tasks[curr_tid]["start"] >= all_tasks[prev_tid]["end"])
            prev_tid = curr_tid
    # Alt Lotlar Arası Sıralama (FIFO): Aynı SKU'nun sub_k+1 partisi aynı operasyonda sub_k partisinden önce başlayamaz
    for (pid, op_seq), grp in tasks_df.groupby(["product_id", "operation_seq"]):
        if len(grp) > 1:
            sorted_subs = grp.sort_values("sub_lot_index")
            prev_tid = None
            for _, sub_row in sorted_subs.iterrows():
                curr_tid = sub_row["task_id"]
                if prev_tid is not None:
                    model.Add(all_tasks[curr_tid]["start"] >= all_tasks[prev_tid]["start"])
                prev_tid = curr_tid
    # 2. Closed-Loop MRP Serbest Bırakma Kısıtı (r_j = max_{m in BOM} t_availability,m)
    for tid, t_info in all_tasks.items():
        if t_info["operation_seq"] == 1:
            pid = t_info["product_id"]
            r_j = sku_release_times.get(pid, 0)
            if r_j > 0:
                model.Add(t_info["start"] >= r_j)

        # 3. Tezgâh Çakışma Önleme & Kesin Zamanlı Setup İntervalleri (AddCircuit + OptionalInterval)
        all_setup_terms = []
    for mid, tids in machine_to_tasks.items():
        n_m = len(tids)
        if n_m == 0:
            continue

        dummy = n_m
        circuit_arcs = []
        machine_setup_intervals = []

        # 1) Dummy -> Task (Günün ilk işi): Tezgâh başlangıç durumuna (Initial State) göre setup
        p_init = machine_initial_states.get(mid, None)
        for i, tid in enumerate(tids):
            lit = model.NewBoolVar(f"first_{mid}_{tid}")
            circuit_arcs.append((dummy, i, lit))

            p_first = all_tasks[tid]["product_id"]
            s_init = int(setup_dict.get((mid, p_init, p_first), 0)) if p_init else 0
            if s_init > 0:
                s_start = model.NewIntVar(0, horizon, f"init_setup_start_{mid}_{tid}")
                s_end = model.NewIntVar(0, horizon, f"init_setup_end_{mid}_{tid}")
                s_interval = model.NewOptionalIntervalVar(s_start, s_init, s_end, lit, f"init_setup_int_{mid}_{tid}")
                machine_setup_intervals.append(s_interval)
                model.Add(s_end <= all_tasks[tid]["start"]).OnlyEnforceIf(lit)
                all_setup_terms.append(lit * s_init)

        # 2) Task -> Dummy (Günün son işi)
        for i, tid in enumerate(tids):
            lit = model.NewBoolVar(f"arc_end_{mid}_{tid}")
            circuit_arcs.append((i, dummy, lit))

        # 3) Task i -> Task j (Doğrudan komşu işler ve fiziksel hazırlık intervalleri)
        for i in range(n_m):
            t1 = tids[i]
            p1 = all_tasks[t1]["product_id"]
            for j in range(n_m):
                if i == j:
                    continue
                t2 = tids[j]
                p2 = all_tasks[t2]["product_id"]

                lit = model.NewBoolVar(f"arc_{mid}_{t1}_{t2}")
                circuit_arcs.append((i, j, lit))

                s12 = int(setup_dict.get((mid, p1, p2), 0))
                if s12 > 0:
                    # Fiziksel Setup İntervali: Model içinde optimize edilen bağımsız zaman aralığı
                    s_start = model.NewIntVar(0, horizon, f"setup_start_{mid}_{t1}_{t2}")
                    s_end = model.NewIntVar(0, horizon, f"setup_end_{mid}_{t1}_{t2}")
                    s_interval = model.NewOptionalIntervalVar(s_start, s12, s_end, lit, f"setup_int_{mid}_{t1}_{t2}")
                    all_setup_terms.append(lit * s12)
                    machine_setup_intervals.append(s_interval)

                    # Hazırlık öncül iş bitmeden başlayamaz
                    model.Add(s_start >= all_tasks[t1]["end"]).OnlyEnforceIf(lit)
                    # Hazırlık ardıl iş başlamadan hemen önce biter (Just-in-Time Setup)
                    model.Add(s_end == all_tasks[t2]["start"]).OnlyEnforceIf(lit)
                else:
                    model.Add(all_tasks[t2]["start"] >= all_tasks[t1]["end"]).OnlyEnforceIf(lit)
        # ---------------------------------------------------------------------
        # 2. Fiziksel Takvim Modeli: 96h Regular + Explicit OT Pencereleri
        # ---------------------------------------------------------------------
        # Hafta İçi (Pzt-Cmt): 08:00-24:00 (16h Regular) -> 6 x 16 = 96h Regular
        #                     00:00-08:00 (8h Explicit OT Penceresi) -> 6 x 8 = 48h Max OT
        # Pazar (Gün 6, 13..): 24h Kesin Kapalı Duruş / Bakım (Hard Break)
        # ---------------------------------------------------------------------
        # ---------------------------------------------------------------------
        # P0 DÜZELTMESİ: Hafta Bazlı Sert OT Bütçe Kısıtı (Solver-Enforced OT Budget)
        # ---------------------------------------------------------------------
        break_intervals = []
        if str(mid) not in machine_ot_hours:
            raise ValueError(f"Eksik makine takvim verisi (fail-fast): Tezgah {mid} icin OT limiti tanimlanmamis!")
        allowed_ot_min = int(machine_ot_hours[str(mid)] * 60)
        total_days = (horizon // 1440) + 2

        # Hafta bazlı gece OT kullanımını biriktirmek için sözlük: {hafta_indeksi: [ot_kullanildi_boolean_değişkenleri]}
        week_ot_active_vars = {}

        for day in range(total_days):
            day_of_week = day % 7
            week_idx = day // 7

            if day_of_week == 6:
                # Pazar günü: 24 saat kesin kapalı duruş (Hard Break)
                sun_start = day * 1440
                if sun_start < horizon:
                    sun_end = min(sun_start + 1440, horizon)
                    sun_dur = sun_end - sun_start
                    if sun_dur > 0:
                        sun_int = model.NewIntervalVar(sun_start, sun_dur, sun_end, f"sunday_break_{mid}_d{day}")
                        break_intervals.append(sun_int)
            else:
                # Pazartesi - Cumartesi: Gece penceresi (00:00 - 08:00) = 480 dakika
                night_start = day * 1440
                if night_start < horizon:
                    night_end = min(night_start + 8 * 60, horizon)
                    night_dur = night_end - night_start
                    if night_dur > 0:
                        if allowed_ot_min <= 0:
                            # LP bu makineye hiç OT vermediyse gece penceresi kesin kapalıdır
                            n_int = model.NewIntervalVar(
                                night_start, night_dur, night_end, f"night_break_closed_{mid}_d{day}"
                            )
                            break_intervals.append(n_int)
                        else:
                            # LP bütçe verdiyse: Gece penceresi koşullu duruştur.
                            # is_ot_closed = 1 ise gece KAPALIDIR (üretim yapılamaz, OT tüketilmez)
                            # is_ot_closed = 0 ise gece AÇIKTIR (üretim yapılabilir, 480 dk OT bütçesinden harcanır)
                            is_ot_closed = model.NewBoolVar(f"ot_closed_{mid}_d{day}")
                            opt_break = model.NewOptionalIntervalVar(
                                night_start, night_dur, night_end, is_ot_closed, f"opt_night_break_{mid}_d{day}"
                            )
                            break_intervals.append(opt_break)

                            # Gece açıldıysa (is_ot_active = 1 - is_ot_closed)
                            is_ot_active = model.NewBoolVar(f"ot_active_{mid}_d{day}")
                            model.Add(is_ot_active + is_ot_closed == 1)

                            if week_idx not in week_ot_active_vars:
                                week_ot_active_vars[week_idx] = []
                            week_ot_active_vars[week_idx].append(is_ot_active)

        # SERT MATEMATİKSEL KISIT (Model A Politikası - Week-1 Exclusive Overtime):
        for w_idx, act_vars in week_ot_active_vars.items():
            if w_idx == 0:
                # 1. Hafta (W1): Taktik LP'den onaylanan bütçe tavanı kadar gece penceresi açılabilir
                max_allowed_blocks = (allowed_ot_min + 479) // 480 if allowed_ot_min > 0 else 0
                model.Add(sum(act_vars) <= max_allowed_blocks)
            else:
                # 2. Hafta ve sonrası (Spillover): Model A politikası gereği W2+ gece fazla mesaisi açılamaz
                model.Add(sum(act_vars) == 0)

        # Hafta 1 tezgah toplam iş yükü fiili OT kısıtı:
        # Tezgahta Hafta 1'de tamamlanan işlerin toplam süresi (Regular 5760 dk + allowed_ot_min) aşamaz.
        if allowed_ot_min >= 0 and tids:
            REGULAR_WEEK_MIN = 6 * 16 * 60  # 96 saat = 5760 dakika
            week_1_durations = [all_tasks[tid]["duration"] for tid in tids]
            model.Add(sum(week_1_durations) <= REGULAR_WEEK_MIN + allowed_ot_min)

        # Tezgâhta hem işlerin hem de aktif hazırlık intervallerinin çakışmasını engelle
        model.AddNoOverlap([all_tasks[tid]["interval"] for tid in tids] + machine_setup_intervals + break_intervals)
        if circuit_arcs:
            model.AddCircuit(circuit_arcs)

    # ---------------------------------------------------------------------
    # P2: Çok Amaçlı Karar Fonksiyonu (Multi-Objective Optimization)
    # Makespan ana hedef, sıra bağımlı ayar (setup) süreleri ikincil cezadır.
    # ---------------------------------------------------------------------
    makespan = model.NewIntVar(0, horizon, "makespan")
    for tid in all_tasks:
        model.Add(makespan >= all_tasks[tid]["end"])

    total_setup_duration = sum(all_setup_terms) if all_setup_terms else 0

    # Weighted-Sum Skalerleştirme: Makespan ağırlıklı birincil bileşen,
    # setup süresi ise ikincil bileşen olarak penalize edilir.
    # (Not: Katı leksikografik garanti için Faz 1 makespan, Faz 2 setup iki aşamalı çözümü yol haritasındadır.)
    objective_expr = int(SCHEDULING_WEIGHT_MAKESPAN) * makespan + int(SCHEDULING_WEIGHT_SETUP) * total_setup_duration
    model.Minimize(objective_expr)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(CPSAT_TIME_LIMIT_SECONDS)
    solver.parameters.num_search_workers = int(CPSAT_NUM_SEARCH_WORKERS)
    solver.parameters.random_seed = int(CPSAT_RANDOM_SEED)

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    print(f"CP-SAT Çözücü Durumu: {status_name}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        conn.close()
        raise RuntimeError(
            f"CP-SAT scheduling failed to find a feasible solution. "
            f"Solver status: {status_name}. Pipeline terminated immediately."
        )

    best_makespan = int(solver.Value(makespan))
    total_setup_val = int(solver.Value(total_setup_duration)) if all_setup_terms else 0
    obj_val = float(solver.ObjectiveValue())
    best_bound = float(solver.BestObjectiveBound()) if solver.BestObjectiveBound() > 0 else 0.0
    gap = (abs(obj_val - best_bound) / max(1.0, abs(obj_val))) * 100.0 if obj_val > 0 else 0.0

    print(f"Makespan: {best_makespan} dakika ({best_makespan / 60:.2f} saat) | Toplam Setup: {total_setup_val} dakika")
    print(f"Bileşik Amaç Değeri (Objective): {obj_val:.1f} | Dual Bound: {best_bound:.1f} | Optimality Gap: %{gap:.2f}")

    schedule_rows = []
    weekly_accounting_rows = []
    for mid, tids in machine_to_tasks.items():
        m_tasks = []
        for tid in tids:
            s_val = int(solver.Value(all_tasks[tid]["start"]))
            e_val = int(solver.Value(all_tasks[tid]["end"]))
            m_tasks.append(
                {
                    "task_id": tid,
                    "lot_id": all_tasks[tid]["lot_id"],
                    "parent_lot_id": all_tasks[tid].get("parent_lot_id", all_tasks[tid]["lot_id"]),
                    "sub_lot_index": all_tasks[tid].get("sub_lot_index", 0),
                    "product_id": all_tasks[tid]["product_id"],
                    "operation_seq": all_tasks[tid]["operation_seq"],
                    "machine_id": mid,
                    "batch_count": all_tasks[tid]["batch_count"],
                    "batch_size_units": all_tasks[tid]["batch_size_units"],
                    "production_units": all_tasks[tid]["production_units"],
                    "duration_min": all_tasks[tid]["duration"],
                    "start_min": s_val,
                    "end_min": e_val,
                    "release_time_min": sku_release_times.get(all_tasks[tid]["product_id"], 0),
                    "material_availability_datetime": sku_material_datetimes.get(
                        all_tasks[tid]["product_id"], horizon_start_dt.strftime("%Y-%m-%d %H:%M:%S")
                    ),
                }
            )

        m_tasks = sorted(m_tasks, key=lambda x: x["start_min"])
        last_prod = machine_initial_states.get(mid, None)
        for item in m_tasks:
            curr_prod = item["product_id"]
            setup_val = 0
            if last_prod is not None:
                setup_val = setup_dict.get((mid, last_prod, curr_prod), 0)
            item["setup_before_min"] = setup_val
            item["setup_end_min"] = float(item["start_min"])
            item["setup_start_min"] = float(item["start_min"]) - float(setup_val)
            last_prod = curr_prod

            # Takvim & Fazla Mesai (OT) Gerçek Örtüşme Tespiti (00:00 - 08:00 arası OT penceresidir)
            # Bir işin yalnızca gece penceresine düşen dakikaları OT sayılır
            s_min = item["start_min"]
            e_min = item["end_min"]
            total_duration = item["duration_min"]

            # Denetim Madde 23: Takvim penceresini doğrudan machines.max_daily_hours'tan al (SSOT)
            m_max_h = machine_daily_hours.get(mid, getattr(cfg, "DAILY_PRODUCTION_HOURS", 16.0))
            ot_cutoff_min = max(0.0, (24.0 - m_max_h) * 60.0)

            # Hafta bazlı OT ayrıştırması (Week 1, Week 2, Week 3, Week 4)
            WEEK_LEN_MIN = 7 * 24 * 60  # 10080 dk
            task_week = int(s_min // WEEK_LEN_MIN) + 1

            # Madde 13: Hafta sınırlarını (W1, W2..) aşan işler için operasyonel muhasebe ayrıştırması
            task_week_breakdown = {}  # {week_num: {"regular": 0.0, "ot": 0.0, "setup_ot": 0.0}}

            ot_duration_in_task = 0.0
            cur_cursor = s_min
            while cur_cursor < e_min:
                cur_w = int(cur_cursor // WEEK_LEN_MIN) + 1
                if cur_w not in task_week_breakdown:
                    task_week_breakdown[cur_w] = {"regular": 0.0, "ot": 0.0, "setup_ot": 0.0}

                next_week_boundary = cur_w * WEEK_LEN_MIN
                day_cursor = cur_cursor % 1440
                if day_cursor < ot_cutoff_min:  # Gece Fazla Mesai Penceresi [0, ot_cutoff_min)
                    step = min(e_min - cur_cursor, ot_cutoff_min - day_cursor, next_week_boundary - cur_cursor)
                    ot_duration_in_task += step
                    task_week_breakdown[cur_w]["ot"] += step
                    cur_cursor += step
                else:  # Normal çalışma aralığı [ot_cutoff_min, 1440)
                    step = min(e_min - cur_cursor, 1440 - day_cursor, next_week_boundary - cur_cursor)
                    task_week_breakdown[cur_w]["regular"] += step
                    cur_cursor += step

            # Madde 11 & 13: Setup süresi ve hafta dağılımı
            setup_ot_duration = 0.0
            s_setup_min = item.get("setup_start_min", 0.0)
            e_setup_min = item.get("setup_end_min", 0.0)
            if e_setup_min > s_setup_min:
                cur_s = s_setup_min
                while cur_s < e_setup_min:
                    cur_sw = int(cur_s // WEEK_LEN_MIN) + 1
                    if cur_sw not in task_week_breakdown:
                        task_week_breakdown[cur_sw] = {"regular": 0.0, "ot": 0.0, "setup_ot": 0.0}

                    next_w_bound = cur_sw * WEEK_LEN_MIN
                    day_cur = cur_s % 1440
                    if day_cur < ot_cutoff_min:
                        step_s = min(e_setup_min - cur_s, ot_cutoff_min - day_cur, next_w_bound - cur_s)
                        setup_ot_duration += step_s
                        task_week_breakdown[cur_sw]["setup_ot"] += step_s
                        cur_s += step_s
                    else:
                        step_s = min(e_setup_min - cur_s, 1440 - day_cur, next_w_bound - cur_s)
                        cur_s += step_s

            item["setup_overtime_minutes"] = setup_ot_duration
            total_actual_ot = ot_duration_in_task + setup_ot_duration
            regular_duration_in_task = max(0, total_duration - ot_duration_in_task)

            # Denetim Madde 20 & 25 Değişmezi: Görev süresi korunumu (duration_min == regular_minutes + overtime_minutes)
            item["schedule_week"] = task_week
            item["production_overtime_minutes"] = ot_duration_in_task
            item["overtime_min"] = ot_duration_in_task
            item["overtime_minutes"] = ot_duration_in_task
            item["total_overtime_minutes"] = total_actual_ot
            item["regular_minutes"] = regular_duration_in_task
            item["is_overtime"] = 1 if total_actual_ot > 0 else 0
            item["calendar_shift"] = "OVERTIME" if total_actual_ot > (total_duration / 2) else "REGULAR"

            schedule_rows.append(item)

            # Madde 13: Gerçek operasyonel muhasebe satırları (Weekly Task Accounting)
            for w_num, w_data in sorted(task_week_breakdown.items()):
                weekly_accounting_rows.append(
                    {
                        "task_id": item.get("task_id", ""),
                        "lot_id": item.get("lot_id", ""),
                        "machine_id": item.get("machine_id", mid),
                        "schedule_week": w_num,
                        "regular_minutes": round(w_data["regular"], 2),
                        "overtime_minutes": round(w_data["ot"] + w_data["setup_ot"], 2),
                        "production_ot_minutes": round(w_data["ot"], 2),
                        "setup_ot_minutes": round(w_data["setup_ot"], 2),
                        "total_work_minutes": round(w_data["regular"] + w_data["ot"] + w_data["setup_ot"], 2),
                    }
                )

    sched_df = pd.DataFrame(schedule_rows)

    # 3. Madde: batch_qty veri sözleşmesi gereği kanonik şema kontrolü
    canonical_schedule_cols = [
        "task_id",
        "lot_id",
        "parent_lot_id",
        "sub_lot_index",
        "product_id",
        "operation_seq",
        "machine_id",
        "batch_count",
        "batch_size_units",
        "production_units",
        "duration_min",
        "start_min",
        "end_min",
        "schedule_week",
        "regular_minutes",
        "overtime_minutes",
        "setup_overtime_minutes",
        "setup_before_min",
        "setup_start_min",
        "setup_end_min",
        "is_overtime",
        "calendar_shift",
        "release_time_min",
    ]
    for col in canonical_schedule_cols:
        if col not in sched_df.columns:
            sched_df[col] = 0 if "min" in col or "units" in col or "count" in col else ""

    os.makedirs("data/processed", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    sched_df.to_csv("data/processed/production_schedule.csv", index=False)
    if weekly_accounting_rows:
        accounting_df = pd.DataFrame(weekly_accounting_rows)
        accounting_df.to_csv("data/processed/task_weekly_accounting.csv", index=False)

    # P0 Madde 2 / Madde 20: Hafta bazlı kümülatif OT bütçe kontrolü (Source of Truth: weekly_accounting)
    if weekly_accounting_rows and weekly_machine_ot_budget_min:
        accounting_df = pd.DataFrame(weekly_accounting_rows)
        weekly_actual_ot = accounting_df.groupby(["schedule_week", "machine_id"])["overtime_minutes"].sum().to_dict()
        for (w, m), act_ot_min in weekly_actual_ot.items():
            budget_min = weekly_machine_ot_budget_min.get((w, m), 48.0 * 60.0)
            if act_ot_min > budget_min:
                print(
                    f"[AUDIT-OT] Hafta {w}, Makine {m}: Gerçekleşen OT={act_ot_min:.1f} dk, Bütçe={budget_min:.1f} dk"
                )

    # -------------------------------------------------------------
    # Madde 24: CP-SAT Optimization Solver Metadata & Proof Lineage
    # -------------------------------------------------------------
    obj_val = float(solver.ObjectiveValue()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    best_bound = float(solver.BestObjectiveBound()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None

    obj_val = float(solver.ObjectiveValue())
    best_bound = float(solver.BestObjectiveBound()) if solver.BestObjectiveBound() > 0 else 0.0

    # Gap hesabı: (|Objective - Bound| / max(1.0, |Objective|)) * 100
    if obj_val is not None and best_bound is not None:
        optimality_gap = abs(obj_val - best_bound) / max(1.0, abs(obj_val)) * 100.0
    else:
        optimality_gap = None

    solver_metadata = [
        {
            "solver_name": "Google OR-Tools CP-SAT",
            "solver_status": status_name,
            "is_optimal": bool(status == cp_model.OPTIMAL),
            "objective_value_min": obj_val,
            "best_bound_min": best_bound,
            "optimality_gap_pct": round(optimality_gap, 4) if optimality_gap is not None else None,
            "solve_time_seconds": round(float(solver.WallTime()), 4),
            "configured_num_search_workers": int(CPSAT_NUM_SEARCH_WORKERS),
            "effective_num_search_workers": int(
                getattr(solver.parameters, "num_search_workers", CPSAT_NUM_SEARCH_WORKERS)
            ),
            "num_workers": int(getattr(solver.parameters, "num_search_workers", CPSAT_NUM_SEARCH_WORKERS)),
            "random_seed": int(CPSAT_RANDOM_SEED),
            "max_time_in_seconds": float(getattr(solver.parameters, "max_time_in_seconds", 0.0)),
            "tasks_scheduled": len(sched_df),
            "total_scheduled_units": int(sched_df["production_units"].sum())
            if "production_units" in sched_df.columns
            else 0,
            "week_1_horizon_min": 7 * 24 * 60,
            "cross_week_spillover_min": max(0, int(solver.Value(makespan) - (7 * 24 * 60))),
            "cross_week_execution_allowed": 1,
            "execution_policy": "CROSS_WEEK_SPILLOVER_ALLOWED",
            "ot_policy": "MODEL_A_WEEK1_ONLY",
            "ot_policy_description": "Overtime authorized strictly for Week-1; cross-week spillover runs under regular shifts only.",
            "objective_type": "MINIMIZE_MAKESPAN_AND_SETUP",
            "operational_objectives_backlog": "MAKESPAN_AND_SEQUENCE_DEPENDENT_SETUP",
            "mrp_coupling_mode": "EXPLICIT_MATERIAL_AVAILABILITY_DATETIME_CHAIN",
            "mrp_erp_operational_chain": "OPEN_PO_SUPPLIER_LT_GOODS_RECEIPT_QC_HOLD",
            "mrp_qc_hold_enforced": 1,
            "objective_makespan_min": int(solver.Value(makespan)),
            "objective_setup_min": int(solver.Value(total_setup_duration)) if all_setup_terms else 0,
            "total_objective_value": float(solver.ObjectiveValue()),
        }
    ]

    effective_run_id = run_id if run_id else "DEFAULT_RUN"
    solver_meta_df = pd.DataFrame(solver_metadata)
    solver_meta_df["run_id"] = effective_run_id
    sched_df["run_id"] = effective_run_id

    # Staging-aware reports path (Item 28)
    reports_dir = Path(os.environ.get("FACTORY_REPORTS_DIR", "reports"))
    reports_dir.mkdir(parents=True, exist_ok=True)
    with open(reports_dir / "schedule_solver_metadata.json", "w", encoding="utf-8") as f:
        json.dump(solver_metadata[0], f, indent=2, ensure_ascii=False)

    conn = get_db_connection(DB_PATH)
    sched_df.to_sql("production_schedule", conn, if_exists="replace", index=False)
    solver_meta_df.to_sql("schedule_solver_metadata", conn, if_exists="replace", index=False)
    conn.close()
    print("✓ production_schedule.csv ve schedule_solver_metadata güncellendi.")

    # Hiyerarşik Kapasite Mutabakatı (Tactical LP vs. Operational CP-SAT)
    print()
    print("--- Hiyerarşik Kapasite Mutabakatı (Tactical LP vs. Operational CP-SAT) ---")
    cap_plan_path = "data/processed/machine_capacity_plan.csv"
    if os.path.exists(cap_plan_path):
        cap_df = pd.read_csv(cap_plan_path)
        w1_cap = cap_df[cap_df["period_week"] == 1]
        audit_records = []
        for m_id in sorted(sched_df["machine_id"].unique()):
            m_sched = sched_df[sched_df["machine_id"] == m_id]
            m_cap_row = w1_cap[w1_cap["machine_id"] == m_id]
            lp_allowed_max_hr = float(m_cap_row["total_capacity_hours"].iloc[0]) if not m_cap_row.empty else 134.4
            proc_hours = round(float((m_sched["end_min"] - m_sched["start_min"]).sum() / 60.0), 2)
            setup_hours = round(float(m_sched["setup_before_min"].sum() / 60.0), 2)
            total_workload_hr = round(proc_hours + setup_hours, 2)
            overrun_hr = max(0.0, round(total_workload_hr - lp_allowed_max_hr, 2))
            audit_records.append(
                {
                    "machine_id": m_id,
                    "lp_max_allowed_hr": lp_allowed_max_hr,
                    "proc_hours": proc_hours,
                    "setup_hours": setup_hours,
                    "total_workload_hr": total_workload_hr,
                    "setup_overrun_hr": overrun_hr,
                }
            )
        audit_df = pd.DataFrame(audit_records)
        print(audit_df.to_string(index=False))
        print(
            "✓ HPP Tasarım Prensibi: Agrega LP saf işlem süresini sınırlar; sıra bağımlı hazırlık yükü operasyonel seviyede eklenir."
        )
        print()

    # Mutabakat
    sched_summary = (
        sched_df[sched_df["operation_seq"] == 1].groupby("product_id")["production_units"].sum().reset_index()
    )
    merged_audit = pd.merge(
        sku_plan[["product_id", "planned_units"]], sched_summary, on="product_id", how="left"
    ).fillna(0)
    merged_audit.rename(columns={"production_units": "scheduled_units"}, inplace=True)
    merged_audit["diff"] = merged_audit["planned_units"] - merged_audit["scheduled_units"]

    print("\n--- SKU Plan ve Çizelge Mutabakatı (Audit) ---")
    print(merged_audit.to_string(index=False))
    if (merged_audit["diff"] == 0).all():
        print("✓ MUTABAKAT: %100 Eşleşti. Tüm planlanan SKU parti adetleri tam olarak çizelgelendi.")
    else:
        print("⚠ DİKKAT: Plan ve çizelge adetleri arasında uyumsuzluk var!")

    # Fazla Mesai (OT) Bütçe Uyumu Denetimi (Source of Truth: Weekly Accounting)
    if weekly_accounting_rows:
        acc_df_audit = pd.DataFrame(weekly_accounting_rows)
        m01_w1_mask = (acc_df_audit["machine_id"] == "M01") & (acc_df_audit["schedule_week"] == 1)
        actual_ot_min = float(acc_df_audit[m01_w1_mask]["overtime_minutes"].sum())
    else:
        actual_ot_min = (
            float(sched_df[sched_df["machine_id"] == "M01"]["overtime_min"].sum())
            if "overtime_min" in sched_df.columns
            else 0.0
        )

    allowed_ot_min = int(machine_ot_hours.get("M01", 0.0) * 60)
    print("\n--- Fazla Mesai (OT) Bütçe Denetimi (Hafta 1 - Accounting Dilimli) ---")
    print(f"M01 İzin Verilen OT : {allowed_ot_min} dk ({allowed_ot_min / 60:.2f} saat)")
    print(f"M01 Fiili Net OT    : {actual_ot_min:.1f} dk ({actual_ot_min / 60:.2f} saat)")
    if actual_ot_min <= allowed_ot_min:
        print("✓ BÜTÇE UYUMLU: Fiili fazla mesai LP tavan sınırını aşmadı.")
    else:
        print("⚠ BÜTÇE AŞIMI: Fiili fazla mesai LP sınırının üzerinde!")

    # Cross-Week Spillover (Hafta Aşımı) Analizi & Model B Mutabakatı
    WEEK_1_HORIZON_MIN = 7 * 24 * 60  # 10,080 dakika
    tasks_week1_count = (sched_df["end_min"] <= WEEK_1_HORIZON_MIN).sum()
    tasks_spillover_count = (sched_df["end_min"] > WEEK_1_HORIZON_MIN).sum()
    spillover_min = max(0, int(best_makespan - WEEK_1_HORIZON_MIN))

    print("\n--- Çizelge Zaman Ufku & Hafta Aşımı (Cross-Week Execution) Denetimi ---")
    print(f"Hafta 1 Nominal Ufuk : {WEEK_1_HORIZON_MIN} dk (168.00 saat)")
    print(f"Fiili Makespan       : {best_makespan} dk ({best_makespan / 60:.2f} saat)")
    print(f"Hafta İçi Biten İşler: {tasks_week1_count} görev")
    print(
        f"Hafta 2'ye Sarkan    : {tasks_spillover_count} görev | Taşma Süresi: {spillover_min} dk ({spillover_min / 60:.2f} saat)"
    )
    print("✓ MODEL B PRENSİBİ: Taktik LP agrega yükü belirler; MRP gecikmesi & sıra bağımlı setup nedeniyle")
    print("                   operasyonel çizelge kesintisiz akışla (rolling horizon) Hafta 2'ye sarkar.")

    conn.close()
    print("--- CP-SAT Detaylı Çizelgeleme Tamamlandı ---\n")


solve_cpsat_schedule = run_cpsat_scheduling

if __name__ == "__main__":
    run_cpsat_scheduling()
