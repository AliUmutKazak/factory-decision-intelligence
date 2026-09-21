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

def run_cpsat_scheduling(sku_plan=None):
    print("--- 4. CP-SAT Detaylı Çizelgeleme (Sıra Bağımlı Komşu Setup & MRP Kısıtları) ---")
    conn = sqlite3.connect(DB_PATH)

    # 1. 1. Hafta SKU Planından Partileri Yükle
    if sku_plan is None:
        sku_plan = pd.read_sql("SELECT * FROM sku_production_plan WHERE period_week = 1", conn)
    routing_df = pd.read_sql("SELECT * FROM routing", conn)
    changeover_df = pd.read_sql("SELECT * FROM changeover_matrix", conn)
    bom_df = pd.read_sql("SELECT * FROM bom", conn)
    mrp_df = pd.read_sql("SELECT * FROM mrp_plan WHERE period_week = 1", conn)

    # Changeover matrisi dinamik okuma
    setup_dict = {}
    machines = routing_df["machine_id"].unique()
    
    # Kolonları dinamik yakala
    f_col = [c for c in changeover_df.columns if "from" in c][0]
    t_col = [c for c in changeover_df.columns if "to" in c][0]
    val_cols = [c for c in changeover_df.columns if c not in (f_col, t_col)]
    time_col = val_cols[0] if val_cols else changeover_df.columns[-1]

    for _, row in changeover_df.iterrows():
        f_p = row[f_col]
        t_p = row[t_col]
        raw_val = float(row[time_col])
        s_val = int(round(raw_val * 60)) if raw_val < 5.0 else int(round(raw_val))
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
    batch_size = getattr(cfg, "PRODUCTION_BATCH_SIZE", 25)
    enable_streaming = getattr(cfg, "ENABLE_LOT_STREAMING", True)
    max_sub_batches = getattr(cfg, "MAX_SUB_LOT_BATCHES", 40)

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
                    "lot_qty": sub_units,
                    "batch_qty": sub_b_qty,
                    "operation_seq": seq,
                    "machine_id": mid,
                    "duration": duration,
                })
                task_counter += 1
    if not tasks:
        empty_cols = [
            "task_id", "lot_id", "product_id", "operation_id", "machine_id",
            "start_min", "end_min", "duration_min", "setup_before_min",
            "setup_start_min", "setup_end_min", "batch_units"
        ]
        return pd.DataFrame(columns=empty_cols)
    tasks_df = pd.DataFrame(tasks)

    # -------------------------------------------------------------
    # CP-SAT MODEL TANIMI
    # -------------------------------------------------------------
    model = cp_model.CpModel()
    horizon = int(tasks_df["duration"].sum() + len(tasks_df) * 120 + 5000)

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
            "product_id": t["product_id"],
            "operation_seq": t["operation_seq"],
            "machine_id": mid,
            "duration": dur,
            "lot_qty": t["lot_qty"]
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

        # 1) Dummy -> Task (Günün ilk işi): Başlangıç setup süresi 0
        for i, tid in enumerate(tids):
            lit = model.NewBoolVar(f"arc_start_{mid}_{tid}")
            circuit_arcs.append((dummy, i, lit))

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

        # Tezgâhta hem işlerin hem de aktif hazırlık intervallerinin çakışmasını engelle
        model.AddNoOverlap([all_tasks[tid]["interval"] for tid in tids] + machine_setup_intervals)
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
                "product_id": all_tasks[tid]["product_id"],
                "operation_seq": all_tasks[tid]["operation_seq"],
                "machine_id": mid,
                "lot_qty": all_tasks[tid]["lot_qty"],
                "batch_qty": all_tasks[tid].get("batch_qty", 1),
                "duration_min": all_tasks[tid]["duration"],
                "start_min": s_val,
                "end_min": e_val,
            })
        
        m_tasks = sorted(m_tasks, key=lambda x: x["start_min"])
        last_prod = None
        for item in m_tasks:
            curr_prod = item["product_id"]
            setup_val = 0
            if last_prod is not None and last_prod != curr_prod:
                setup_val = setup_dict.get((mid, last_prod, curr_prod), 0)
            item["setup_before_min"] = setup_val
            item["setup_end_min"] = float(item["start_min"])
            item["setup_start_min"] = float(item["start_min"]) - float(setup_val)
            last_prod = curr_prod
            schedule_rows.append(item)

    sched_df = pd.DataFrame(schedule_rows)
    sched_df["batch_id"] = sched_df["lot_id"]
    sched_df["batch_qty"] = sched_df["lot_qty"]

    sched_df.to_sql("production_schedule", conn, if_exists="replace", index=False)
    
    # Repodaki CSV dosyasini SQLite ile senkronize tut
    import os
    os.makedirs('data/processed', exist_ok=True)
    sched_df.to_csv('data/processed/production_schedule.csv', index=False)
    print('✓ production_schedule.csv guncellendi.')

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
    sched_summary = sched_df[sched_df["operation_seq"] == 1].groupby("product_id")["lot_qty"].sum().reset_index()
    merged_audit = pd.merge(sku_plan[["product_id", "planned_units"]], sched_summary, on="product_id", how="left").fillna(0)
    merged_audit.rename(columns={"lot_qty": "scheduled_units"}, inplace=True)
    merged_audit["diff"] = merged_audit["planned_units"] - merged_audit["scheduled_units"]

    print("\n--- SKU Plan ve Çizelge Mutabakatı (Audit) ---")
    print(merged_audit.to_string(index=False))
    if (merged_audit["diff"] == 0).all():
        print("✓ MUTABAKAT: %100 Eşleşti. Tüm planlanan SKU parti adetleri tam olarak çizelgelendi.")
    else:
        print("⚠ DİKKAT: Plan ve çizelge adetleri arasında uyumsuzluk var!")

    conn.close()
    print("--- CP-SAT Detaylı Çizelgeleme Tamamlandı ---\n")

solve_cpsat_schedule = run_cpsat_scheduling

if __name__ == "__main__":
    run_cpsat_scheduling()