import json
import os
import sqlite3
import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
import src.config as cfg

from src.config import (
    DB_PATH,
    MRP_EXPEDITE_RELEASE_TIME_MIN,
    CPSAT_TIME_LIMIT_SECONDS,
    CPSAT_NUM_SEARCH_WORKERS,
    CPSAT_RANDOM_SEED,
)

def run_cpsat_scheduling(sku_plan=None, run_id=None):
    print("--- 4. CP-SAT Detaylı Çizelgeleme (Sıra Bağımlı Komşu Setup & MRP Kısıtları) ---")
    conn = sqlite3.connect(DB_PATH)

    # 1. 1. Hafta SKU Planından Partileri Yükle
    if sku_plan is None:
        sku_plan = pd.read_sql("SELECT * FROM sku_production_plan WHERE period_week = 1", conn)
    routing_df = pd.read_sql("SELECT * FROM routing", conn)
    changeover_df = pd.read_sql("SELECT * FROM changeover_matrix", conn)
    bom_df = pd.read_sql("SELECT * FROM bom", conn)
    mrp_df = pd.read_sql("SELECT * FROM mrp_plan WHERE period_week = 1", conn)
    # LP Taktik Seviyeden 1. Hafta Fazla Mesai (OT) Bütçesini Al
    machine_ot_hours = {}
    try:
        cap_df = pd.read_sql("SELECT * FROM machine_capacity_plan WHERE period_week = 1", conn)
        for _, r in cap_df.iterrows():
            machine_ot_hours[str(r["machine_id"])] = float(r.get("overtime_hours", 0.0))
    except Exception:
        machine_ot_hours = {}

    # Changeover matrisi dinamik okuma
    setup_dict = {}
    machines = routing_df["machine_id"].unique()
    
    # Sıkı Veri Sözleşmesi: Setup süresi doğrudan dakika cinsinden okunur (setup_time_min)
    f_col = "from_product" if "from_product" in changeover_df.columns else [c for c in changeover_df.columns if "from" in c][0]
    t_col = "to_product" if "to_product" in changeover_df.columns else [c for c in changeover_df.columns if "to" in c][0]
    
    if "setup_time_min" in changeover_df.columns:
        time_col = "setup_time_min"
    else:
        # Fallback: time içeren kolon veya ilk numerik olmayan f/t dışındaki kolon
        time_candidates = [c for c in changeover_df.columns if "time" in c]
        time_col = time_candidates[0] if time_candidates else [c for c in changeover_df.columns if c not in (f_col, t_col)][0]

    for _, row in changeover_df.iterrows():
        f_p = row[f_col]
        t_p = row[t_col]
        # Sezgisel saat/dakika dönüşümü kaldırıldı; değer doğrudan dakika kabul edilir
        s_val = int(round(float(row[time_col])))
        for m in machines:
            setup_dict[(m, f_p, t_p)] = s_val

    # -------------------------------------------------------------
    # Closed-Loop MRP -> CP-SAT: Dinamik Malzeme Hazır Oluş Zamanı
    # r_lot = max_{m in BOM} t_availability,m
    # -------------------------------------------------------------
    # MRP'de 1. hafta teslimatı acil olan (EXPEDITE) malzemeler için dinamik tedarik gecikmesi
    # planned_release_week <= 0 veya past due olan kalemlerin tedarik gecikme ofseti (dakika)
    mat_availability = {}
    if "material_id" in mrp_df.columns and "action_message" in mrp_df.columns:
        w1_mrp = mrp_df[mrp_df["period_week"] == 1]
        for _, m_row in w1_mrp.iterrows():
            m_id = m_row["material_id"]
            action = str(m_row.get("action_message", ""))
            rel_week = int(m_row.get("planned_release_week", 1))
            
            if "EXPEDITE" in action:
                # Gecikme derinliğine göre dinamik varış süresi:
                # rel_week = 0 -> 480 dk (1 vardiya ekspres teslimat)
                # rel_week < 0 -> her negatif hafta için +480 dk ek tedarik gecikmesi
                delay_min = 480 + max(0, -rel_week) * 480
                mat_availability[m_id] = delay_min
            else:
                mat_availability[m_id] = 0

    # Her SKU için BOM bileşenlerinin en geç varış anını (max availability) belirle
    sku_release_times = {}
    for pid in sku_plan["product_id"].unique():
        prod_materials = bom_df[bom_df["product_id"] == pid]["material_id"].unique()
        if len(prod_materials) > 0:
            sku_release_times[pid] = max(mat_availability.get(mid, 0) for mid in prod_materials)
        else:
            sku_release_times[pid] = 0

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

                tasks.append({
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
                })
                task_counter += 1
    if not tasks:
        canonical_cols = [
            "task_id", "lot_id", "parent_lot_id", "sub_lot_index", "product_id", "operation_seq",
            "machine_id", "batch_count", "batch_size_units", "production_units",
            "start_min", "end_min", "duration_min",
            "setup_before_min", "setup_end_min", "setup_start_min",
            "is_overtime", "calendar_shift", "release_time_min"
        ]
        empty_df = pd.DataFrame(columns=canonical_cols)
        if run_id:
            empty_df["run_id"] = run_id
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
                model.Add(all_tasks[tid]["start"] >= r_j)

    # 3. Tezgâh Çakışma Önleme & Kesin Zamanlı Setup İntervalleri (AddCircuit + OptionalInterval)
    for mid, tids in machine_to_tasks.items():
        n_m = len(tids)
        if n_m <= 1:
            model.AddNoOverlap([all_tasks[tid]["interval"] for tid in tids])
            continue

        dummy = n_m
        circuit_arcs = []
        machine_setup_intervals = []

        # 1) Dummy -> Task (Günün ilk işi): Tezgâh başlangıç durumuna (Initial State) göre setup
        p_init = getattr(cfg, "INITIAL_MACHINE_STATE", {}).get(mid, None)
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
        break_intervals = []
        allowed_ot_min = int(machine_ot_hours.get(str(mid), 0.0) * 60)
        total_days = (horizon // 1440) + 2

        # Pazar günleri ve planlı duruşlar kesin kapalıdır
        for day in range(total_days):
            day_of_week = day % 7
            if day_of_week == 6:
                # Pazar günü tam gün (24 saat) kapalı
                sun_start = day * 1440
                sun_dur = 24 * 60
                sun_end = sun_start + sun_dur
                if sun_start < horizon:
                    sun_int = model.NewIntervalVar(
                        sun_start,
                        min(sun_dur, max(0, horizon - sun_start)),
                        min(sun_end, horizon),
                        f"sunday_break_{mid}_d{day}"
                    )
                    break_intervals.append(sun_int)
            else:
                # Eğer makineye taktik LP hiç fazla mesai (OT) vermemişse gece pencereleri kapalıdır.
                # Eğer OT verilmişse gece pencereleri (00:00-08:00) açık mesai alanı olarak kullanılabilir.
                if allowed_ot_min == 0:
                    night_start = day * 1440
                    night_dur = 8 * 60
                    if night_start < horizon:
                        n_int = model.NewIntervalVar(
                            night_start,
                            min(night_dur, max(0, horizon - night_start)),
                            min(night_start + night_dur, horizon),
                            f"night_break_closed_{mid}_d{day}"
                        )
                        break_intervals.append(n_int)

        # Tezgâhta hem işlerin hem de aktif hazırlık intervallerinin çakışmasını engelle
        model.AddNoOverlap([all_tasks[tid]["interval"] for tid in tids] + machine_setup_intervals + break_intervals)
        model.AddCircuit(circuit_arcs)


    # Amaç: Makespan Minimize Et
    makespan = model.NewIntVar(0, horizon, "makespan")
    for tid in all_tasks:
        model.Add(makespan >= all_tasks[tid]["end"])
    model.Minimize(makespan)

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

    best_makespan = int(solver.ObjectiveValue())
    best_bound = int(solver.BestObjectiveBound())
    gap = ((best_makespan - best_bound) / best_makespan) * 100 if best_makespan > 0 else 0.0

    print(f"Makespan: {best_makespan} dakika ({best_makespan / 60:.2f} saat)")
    print(f"Dual Bound: {best_bound} dakika | Optimality Gap: %{gap:.2f}")

    schedule_rows = []
    for mid, tids in machine_to_tasks.items():
        m_tasks = []
        for tid in tids:
            s_val = int(solver.Value(all_tasks[tid]["start"]))
            e_val = int(solver.Value(all_tasks[tid]["end"]))
            m_tasks.append({
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
            })

        m_tasks = sorted(m_tasks, key=lambda x: x["start_min"])
        last_prod = getattr(cfg, "INITIAL_MACHINE_STATE", {}).get(mid, None)
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
            
            ot_duration_in_task = 0
            cur_cursor = s_min
            while cur_cursor < e_min:
                day_cursor = cur_cursor % 1440
                if day_cursor < 480:  # 00:00 - 08:00 aralığı
                    step = min(e_min - cur_cursor, 480 - day_cursor)
                    ot_duration_in_task += step
                    cur_cursor += step
                else:  # 08:00 - 24:00 normal vardiya aralığı
                    step = min(e_min - cur_cursor, 1440 - day_cursor)
                    cur_cursor += step

            item["overtime_min"] = ot_duration_in_task
            item["is_overtime"] = 1 if ot_duration_in_task > 0 else 0
            item["calendar_shift"] = "OVERTIME" if ot_duration_in_task > (item["duration_min"] / 2) else "REGULAR"

            schedule_rows.append(item)

    sched_df = pd.DataFrame(schedule_rows)

    # 3. Madde: batch_qty veri sözleşmesi gereği kanonik şema kontrolü
    canonical_schedule_cols = [
        "task_id", "lot_id", "parent_lot_id", "sub_lot_index", "product_id", "operation_seq",
        "machine_id", "batch_count", "batch_size_units", "production_units",
        "duration_min", "start_min", "end_min",
        "setup_before_min", "setup_start_min", "setup_end_min",
        "is_overtime", "calendar_shift", "release_time_min"
    ]
    for col in canonical_schedule_cols:
        if col not in sched_df.columns:
            sched_df[col] = 0 if "min" in col or "units" in col or "count" in col else ""

    os.makedirs('data/processed', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    sched_df.to_csv('data/processed/production_schedule.csv', index=False)

    # -------------------------------------------------------------
    # Madde 24: CP-SAT Optimization Solver Metadata & Proof Lineage
    # -------------------------------------------------------------
    obj_val = float(solver.ObjectiveValue()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    best_bound = float(solver.BestObjectiveBound()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None

    # Gap hesabı: (|Objective - Bound| / max(1.0, |Objective|)) * 100
    if obj_val is not None and best_bound is not None:
        optimality_gap = abs(obj_val - best_bound) / max(1.0, abs(obj_val)) * 100.0
    else:
        optimality_gap = None

    solver_metadata = [{
        "solver_name": "Google OR-Tools CP-SAT",
        "solver_status": status_name,
        "is_optimal": bool(status == cp_model.OPTIMAL),
        "objective_value_min": obj_val,
        "best_bound_min": best_bound,
        "optimality_gap_pct": round(optimality_gap, 4) if optimality_gap is not None else None,
        "solve_time_seconds": round(float(solver.WallTime()), 4),
        "configured_num_search_workers": int(CPSAT_NUM_SEARCH_WORKERS),
        "effective_num_search_workers": int(getattr(solver.parameters, "num_search_workers", CPSAT_NUM_SEARCH_WORKERS)),
        "num_workers": int(getattr(solver.parameters, "num_search_workers", CPSAT_NUM_SEARCH_WORKERS)),
        "random_seed": int(CPSAT_RANDOM_SEED),
        "max_time_in_seconds": float(getattr(solver.parameters, "max_time_in_seconds", 0.0)),
        "tasks_scheduled": len(sched_df),
        "total_scheduled_units": int(sched_df["production_units"].sum()) if "production_units" in sched_df.columns else 0,
        "week_1_horizon_min": 7 * 24 * 60,
        "cross_week_spillover_min": max(0, int(obj_val - (7 * 24 * 60))),
        "cross_week_execution_allowed": 1,
        "execution_policy": "CROSS_WEEK_SPILLOVER_ALLOWED",
    }]

    if run_id:
        sched_df["run_id"] = run_id

    solver_meta_df = pd.DataFrame(solver_metadata)
    if run_id:
        solver_meta_df["run_id"] = run_id

    solver_meta_df.to_csv('data/processed/schedule_solver_metadata.csv', index=False)

    with open('reports/schedule_solver_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(solver_metadata[0], f, indent=2, ensure_ascii=False)

    conn = sqlite3.connect(DB_PATH)
    sched_df.to_sql("production_schedule", conn, if_exists="replace", index=False)
    solver_meta_df.to_sql("schedule_solver_metadata", conn, if_exists="replace", index=False)
    conn.close()
    print('✓ production_schedule.csv ve schedule_solver_metadata güncellendi.')

    # Hiyerarşik Kapasite Mutabakatı (Tactical LP vs. Operational CP-SAT)
    print()
    print("--- Hiyerarşik Kapasite Mutabakatı (Tactical LP vs. Operational CP-SAT) ---")
    cap_plan_path = 'data/processed/machine_capacity_plan.csv'
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
            audit_records.append({
                "machine_id": m_id,
                "lp_max_allowed_hr": lp_allowed_max_hr,
                "proc_hours": proc_hours,
                "setup_hours": setup_hours,
                "total_workload_hr": total_workload_hr,
                "setup_overrun_hr": overrun_hr
            })
        audit_df = pd.DataFrame(audit_records)
        print(audit_df.to_string(index=False))
        print("✓ HPP Tasarım Prensibi: Agrega LP saf işlem süresini sınırlar; sıra bağımlı hazırlık yükü operasyonel seviyede eklenir.")
        print()

    # Mutabakat
    sched_summary = sched_df[sched_df["operation_seq"] == 1].groupby("product_id")["production_units"].sum().reset_index()
    merged_audit = pd.merge(sku_plan[["product_id", "planned_units"]], sched_summary, on="product_id", how="left").fillna(0)
    merged_audit.rename(columns={"production_units": "scheduled_units"}, inplace=True)
    merged_audit["diff"] = merged_audit["planned_units"] - merged_audit["scheduled_units"]

    print("\n--- SKU Plan ve Çizelge Mutabakatı (Audit) ---")
    print(merged_audit.to_string(index=False))
    if (merged_audit["diff"] == 0).all():
        print("✓ MUTABAKAT: %100 Eşleşti. Tüm planlanan SKU parti adetleri tam olarak çizelgelendi.")
    else:
            print("⚠ DİKKAT: Plan ve çizelge adetleri arasında uyumsuzluk var!")

    # Fazla Mesai (OT) Bütçe Uyumu Denetimi
    actual_ot_min = sched_df[sched_df["machine_id"] == "M01"]["overtime_min"].sum()
    allowed_ot_min = int(machine_ot_hours.get("M01", 0.0) * 60)
    print("\n--- Fazla Mesai (OT) Bütçe Denetimi ---")
    print(f"M01 İzin Verilen OT : {allowed_ot_min} dk ({allowed_ot_min / 60:.2f} saat)")
    print(f"M01 Fiili Net OT    : {actual_ot_min} dk ({actual_ot_min / 60:.2f} saat)")
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
    print(f"Hafta 2'ye Sarkan    : {tasks_spillover_count} görev | Taşma Süresi: {spillover_min} dk ({spillover_min / 60:.2f} saat)")
    print("✓ MODEL B PRENSİBİ: Taktik LP agrega yükü belirler; MRP gecikmesi & sıra bağımlı setup nedeniyle")
    print("                   operasyonel çizelge kesintisiz akışla (rolling horizon) Hafta 2'ye sarkar.")

    conn.close()
    print("--- CP-SAT Detaylı Çizelgeleme Tamamlandı ---\n")

solve_cpsat_schedule = run_cpsat_scheduling

if __name__ == "__main__":
    run_cpsat_scheduling()