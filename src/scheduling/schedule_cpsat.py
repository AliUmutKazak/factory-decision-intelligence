import os
import sqlite3
import pandas as pd
import numpy as np
from ortools.sat.python import cp_model
from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    WORK_DAYS_PER_WEEK,
    WEEKLY_MINUTES_PER_MACHINE,
    WEEKLY_HOURS_PER_MACHINE,
    LABOR_COST_OVERTIME_HR,
)

OUTPUT_SCHEDULE_PATH = PROCESSED_DATA_DIR / "production_schedule.csv"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    routing_df = pd.read_sql("SELECT * FROM routing", conn)
    setup_df = pd.read_sql("SELECT * FROM changeover_matrix", conn)
    sku_plan = pd.read_sql("SELECT * FROM sku_production_plan WHERE period_week = 1", conn)
    conn.close()
    return routing_df, setup_df, sku_plan

def create_batches(sku_plan):
    # Şartname Madde 25: Ürünler lotlara bölünür
    batch_config = {"P01": 2, "P02": 3, "P03": 2, "P04": 2, "P05": 2}
    
    batches = []
    for _, row in sku_plan.iterrows():
        pid = row["product_id"]
        total_units = row["planned_units"]
        n_batches = batch_config.get(pid, 2)
        base_qty = total_units // n_batches
        
        for b_idx in range(1, n_batches + 1):
            qty = base_qty if b_idx < n_batches else (total_units - base_qty * (n_batches - 1))
            batches.append({
                "batch_id": f"{pid}_B{b_idx}",
                "product_id": pid,
                "batch_qty": qty
            })
            
    return pd.DataFrame(batches)

def solve_heuristic_baseline(batches_df, routing_df, setup_dict):
    # FCFS Sezgisel Taban Model (Benchmark)
    machine_avail = {"M01": 0, "M02": 0, "M03": 0}
    machine_last_prod = {"M01": None, "M02": None, "M03": None}
    
    total_setup_min = 0

    for _, b_row in batches_df.iterrows():
        pid = b_row["product_id"]
        b_routing = routing_df[routing_df["product_id"] == pid].sort_values("operation_seq")

        prev_op_end = 0
        for _, op in b_routing.iterrows():
            m = op["machine_id"]
            proc_time = int(round(op["processing_time_min"] * (b_row["batch_qty"] / 25.0)))
            
            last_p = machine_last_prod[m]
            s_time = setup_dict.get((m, last_p, pid), 0) if last_p else 0
            total_setup_min += s_time

            start_t = max(machine_avail[m] + s_time, prev_op_end)
            end_t = start_t + proc_time

            machine_avail[m] = end_t
            machine_last_prod[m] = pid
            prev_op_end = end_t

    makespan = max(machine_avail.values())
    return makespan, total_setup_min

def solve_cpsat_schedule():
    routing_df, setup_df, sku_plan = load_data()
    batches_df = create_batches(sku_plan)

    setup_dict = {}
    for _, row in setup_df.iterrows():
        for m in ["M01", "M02", "M03"]:
            setup_dict[(m, row["from_product"], row["to_product"])] = int(row["setup_time_min"])

    # 1. Baseline Heuristic
    base_makespan, base_setup = solve_heuristic_baseline(batches_df, routing_df, setup_dict)

    # 2. OR-Tools CP-SAT Matematiksel Model
    model = cp_model.CpModel()
    
    # Çözüm arama ufkunu esnek tutuyoruz (Darboğazın gerçek makespan'ini bulması için)
    SEARCH_HORIZON = 20000  

    all_tasks = {}
    machine_task_keys = {"M01": [], "M02": [], "M03": []}
    machine_intervals = {"M01": [], "M02": [], "M03": []}

    for _, b_row in batches_df.iterrows():
        bid = b_row["batch_id"]
        pid = b_row["product_id"]
        b_routing = routing_df[routing_df["product_id"] == pid].sort_values("operation_seq")

        for _, op in b_routing.iterrows():
            seq = int(op["operation_seq"])
            m = op["machine_id"]
            proc_time = int(round(op["processing_time_min"] * (b_row["batch_qty"] / 25.0)))

            start_var = model.NewIntVar(0, SEARCH_HORIZON, f"start_{bid}_{seq}")
            end_var = model.NewIntVar(0, SEARCH_HORIZON, f"end_{bid}_{seq}")
            interval_var = model.NewIntervalVar(start_var, proc_time, end_var, f"interval_{bid}_{seq}")

            task_key = (bid, seq)
            all_tasks[task_key] = {
                "start": start_var,
                "end": end_var,
                "interval": interval_var,
                "machine": m,
                "proc_time": proc_time,
                "product_id": pid,
                "batch_id": bid,
                "seq": seq,
                "kwh_unit": op["variable_kwh_per_unit"],
                "batch_qty": b_row["batch_qty"]
            }
            machine_task_keys[m].append(task_key)
            machine_intervals[m].append(interval_var)

    # Kısıt 1: Precedence (İş Akış / Öncelik Sırası)
    for _, b_row in batches_df.iterrows():
        bid = b_row["batch_id"]
        pid = b_row["product_id"]
        b_routing = routing_df[routing_df["product_id"] == pid].sort_values("operation_seq")
        seqs = b_routing["operation_seq"].tolist()

        for s1, s2 in zip(seqs[:-1], seqs[1:]):
            model.Add(all_tasks[(bid, s2)]["start"] >= all_tasks[(bid, s1)]["end"])

    # Kısıt 2: Makine Çakışmazlığı (No-Overlap) ve Sıra Bağımlı Setup Matrisi (Disjunctive Formulation)
    for m, keys in machine_task_keys.items():
        n = len(keys)
        for i in range(n):
            for j in range(i + 1, n):
                t1, t2 = keys[i], keys[j]
                p1 = all_tasks[t1]["product_id"]
                p2 = all_tasks[t2]["product_id"]

                s12 = setup_dict.get((m, p1, p2), 0)
                s21 = setup_dict.get((m, p2, p1), 0)

                b = model.NewBoolVar(f"order_{m}_{t1[0]}_{t2[0]}")
                # b=True ise t1 önce biter, s12 setup süresi sonrası t2 başlar
                model.Add(all_tasks[t2]["start"] >= all_tasks[t1]["end"] + s12).OnlyEnforceIf(b)
                # b=False ise t2 önce biter, s21 setup süresi sonrası t1 başlar
                model.Add(all_tasks[t1]["start"] >= all_tasks[t2]["end"] + s21).OnlyEnforceIf(b.Not())

    # Amaç Fonksiyonu: Makespan'i Minimize Et
    makespan = model.NewIntVar(0, SEARCH_HORIZON, "makespan")
    model.AddMaxEquality(makespan, [t["end"] for t in all_tasks.values()])
    model.Minimize(makespan)

    # Çözücü Ayarları
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    print("=" * 80)
    print("      AŞAMA 6: DETAYLI ÇİZELGELEME (CP-SAT VS BASELINE HEURISTIC)      ")
    print("=" * 80)

    schedule_records = []
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        opt_makespan = solver.Value(makespan)
        nominal_2shifts = WEEKLY_MINUTES_PER_MACHINE  # 6 gün * 16 saat = 5.760 dk
        capacity_24_7 = WORK_DAYS_PER_WEEK * 24 * 60   # 6 gün * 24 saat = 8.640 dk

        print(f"Çözüm Durumu        : {'OPTIMAL' if status == cp_model.OPTIMAL else 'FEASIBLE'}")
        print(f"Baseline Makespan   : {base_makespan} dakika ({base_makespan / 60:.1f} saat)")
        print(f"CP-SAT Makespan     : {opt_makespan} dakika ({opt_makespan / 60:.1f} saat)")
        gain = ((base_makespan - opt_makespan) / base_makespan) * 100
        print(f"Optimizasyon Kazancı: %{gain:.1f} Zaman Tasarrufu")
        print("-" * 80)
        print("KAPASİTE & DARBOĞAZ DEĞERLENDİRMESİ:")
        print(f"  - Standart 2 Vardiya Sınırı : {nominal_2shifts} dk ({nominal_2shifts/60:.0f} saat)")
        print(f"  - Maksimum 3 Vardiya Tavanı : {capacity_24_7} dk ({capacity_24_7/60:.0f} saat)")
        
        if opt_makespan > nominal_2shifts:
            extra_h = (opt_makespan - nominal_2shifts) / 60.0
            overtime_cost = extra_h * LABOR_COST_OVERTIME_HR
            print(f"  [KAPASİTE AŞIMI] M01 darboğazı nedeniyle standart 2 vardiya ({WEEKLY_HOURS_PER_MACHINE} sa) aşıldı.")
            print(f"  - Gereken Fazla Mesai / 3. Vardiya : +{extra_h:.1f} saat")
            print(f"  - Ek İşçilik Maliyeti (Overtime)   : ${overtime_cost:,.2f} (@ ${LABOR_COST_OVERTIME_HR:.2f}/saat)")
        else:
            print("  [OK] Çizelge standart 2 vardiya (96 saat) sınırları içinde tamamlandı.")
        print("-" * 80)

        for key, t in all_tasks.items():
            st = solver.Value(t["start"])
            et = solver.Value(t["end"])
            schedule_records.append({
                "batch_id": t["batch_id"],
                "product_id": t["product_id"],
                "operation_seq": t["seq"],
                "machine_id": t["machine"],
                "start_min": st,
                "end_min": et,
                "duration_min": t["proc_time"],
                "batch_qty": t["batch_qty"],
                "kwh_unit": t["kwh_unit"]
            })

        schedule_df = pd.DataFrame(schedule_records).sort_values(["machine_id", "start_min"])
        print("ÇİZELGE ÖZETİ (İlk 10 Operasyon):")
        print(schedule_df[["batch_id", "machine_id", "start_min", "end_min", "duration_min"]].head(10).to_string(index=False))
        print("=" * 80)

        os.makedirs(os.path.dirname(OUTPUT_SCHEDULE_PATH), exist_ok=True)
        schedule_df.to_csv(OUTPUT_SCHEDULE_PATH, index=False)

        conn = sqlite3.connect(DB_PATH)
        schedule_df.to_sql("production_schedule", conn, index=False, if_exists="replace")
        conn.close()

        print(f"[OK] Detaylı Çizelge Kaydedildi: {OUTPUT_SCHEDULE_PATH}")
        print(f"[OK] SQLite 'production_schedule' tablosu güncellendi.")
        print("=" * 80)
    else:
        print("[HATA] CP-SAT uygun bir çözüm bulamadı!")

if __name__ == "__main__":
    solve_cpsat_schedule()