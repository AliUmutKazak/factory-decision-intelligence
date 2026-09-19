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
    mrp_df = pd.read_sql("SELECT * FROM mrp_plan WHERE period_week = 1", conn)
    conn.close()
    return routing_df, setup_df, sku_plan, mrp_df

def create_batches(sku_plan):
    # Ürün lotlama mimarisi (SKU toplam adetlerini tam korur)
    batch_config = {"P01": 2, "P02": 3, "P03": 2, "P04": 2, "P05": 2}
    
    batches = []
    for _, row in sku_plan.iterrows():
        pid = row["product_id"]
        total_units = int(row["planned_units"])
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
    routing_df, setup_df, sku_plan, mrp_df = load_data()
    batches_df = create_batches(sku_plan)

    setup_dict = {}
    for _, row in setup_df.iterrows():
        for m in ["M01", "M02", "M03"]:
            setup_dict[(m, row["from_product"], row["to_product"])] = int(row["setup_time_min"])

    # 1. Baseline Heuristic
    base_makespan, base_setup = solve_heuristic_baseline(batches_df, routing_df, setup_dict)

    # 2. OR-Tools CP-SAT Modeli
    model = cp_model.CpModel()
    SEARCH_HORIZON = 20000  # Dakika cinsinden esnek ufuk

    all_tasks = {}
    machine_task_keys = {"M01": [], "M02": [], "M03": []}

    # MRP Entegrasyonu: Hafta 1 siparişleri için en erken serbest kalma dakikası
    # (Tüm kritik hammaddeler Hafta 1 başında hazır/expedite kabul edildiğinde r_b = 0)
    earliest_release_min = 0

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

            # MRP Malzeme Hazırlık Kısıtı: İlk operasyon malzeme tesliminden önce başlayamaz
            if seq == 1:
                model.Add(start_var >= earliest_release_min)

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

    # Kısıt 1: Precedence (İş Akış / Rota Sırası)
    for _, b_row in batches_df.iterrows():
        bid = b_row["batch_id"]
        pid = b_row["product_id"]
        b_routing = routing_df[routing_df["product_id"] == pid].sort_values("operation_seq")
        seqs = b_routing["operation_seq"].tolist()

        for s1, s2 in zip(seqs[:-1], seqs[1:]):
            model.Add(all_tasks[(bid, s2)]["start"] >= all_tasks[(bid, s1)]["end"])

    # Kısıt 2: Makine Çakışmazlığı & Sıra Bağımlı Setup Matrisi (Disjunctive Formulation)
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
                model.Add(all_tasks[t2]["start"] >= all_tasks[t1]["end"] + s12).OnlyEnforceIf(b)
                model.Add(all_tasks[t1]["start"] >= all_tasks[t2]["end"] + s21).OnlyEnforceIf(b.Not())

    # Amaç Fonksiyonu: Makespan'i Minimize Et
    makespan = model.NewIntVar(0, SEARCH_HORIZON, "makespan")
    model.AddMaxEquality(makespan, [t["end"] for t in all_tasks.values()])
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    print("=" * 85)
    print("      AŞAMA 6: DETAYLI ÇİZELGELEME (CP-SAT VS BASELINE HEURISTIC)      ")
    print("=" * 85)

    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        opt_makespan = int(solver.Value(makespan))
        best_bound = int(solver.BestObjectiveBound())
        gap_pct = (abs(opt_makespan - best_bound) / max(1, opt_makespan)) * 100.0
        status_str = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"

        # Ham operasyonları topla ve tezgâh sırasına göre diz
        raw_ops = []
        for key, t in all_tasks.items():
            raw_ops.append({
                "batch_id": t["batch_id"],
                "product_id": t["product_id"],
                "operation_seq": t["seq"],
                "machine_id": t["machine"],
                "start_min": int(solver.Value(t["start"])),
                "end_min": int(solver.Value(t["end"])),
                "duration_min": t["proc_time"],
                "batch_qty": t["batch_qty"],
                "kwh_unit": t["kwh_unit"]
            })

        df_raw = pd.DataFrame(raw_ops).sort_values(["machine_id", "start_min"])

        # Gerçek setup sürelerini ve iş yüklerini (workload) hesapla
        schedule_records = []
        machine_metrics = {m: {"proc_min": 0, "setup_min": 0} for m in ["M01", "M02", "M03"]}

        for m, group in df_raw.groupby("machine_id"):
            sorted_ops = group.sort_values("start_min").to_dict("records")
            last_p = None
            for op in sorted_ops:
                p = op["product_id"]
                s_time = setup_dict.get((m, last_p, p), 0) if (last_p is not None and last_p != p) else 0
                
                op["setup_before_min"] = s_time
                machine_metrics[m]["proc_min"] += op["duration_min"]
                machine_metrics[m]["setup_min"] += s_time
                
                last_p = p
                schedule_records.append(op)

        schedule_df = pd.DataFrame(schedule_records).sort_values(["machine_id", "start_min"])

        nominal_minutes = WEEKLY_MINUTES_PER_MACHINE  # 96 saat = 5.760 dk

        print(f"Çözücü Durumu (Status) : {status_str}")
        print(f"Amaç Değeri (Makespan) : {opt_makespan} dk ({opt_makespan / 60.0:.2f} saat)")
        print(f"En İyi Alt Sınır (Bound): {best_bound} dk ({best_bound / 60.0:.2f} saat)")
        print(f"Optimality Gap         : %{gap_pct:.2f}")
        print(f"Baseline Makespan      : {base_makespan} dk ({base_makespan / 60.0:.2f} saat)")
        gain = ((base_makespan - opt_makespan) / base_makespan) * 100
        print(f"Optimizasyon Tasarrufu : %{gain:.1f}")
        print("-" * 85)
        print("TEZGAH İŞ YÜKÜ (WORKLOAD) VE NET FAZLA MESAİ ANALİZİ:")
        print(f"  [Referans] Standart 2 Vardiya Kapasitesi: {WEEKLY_HOURS_PER_MACHINE} saat ({nominal_minutes} dk)")
        
        total_overtime_cost = 0.0
        for m in sorted(machine_metrics.keys()):
            p_min = machine_metrics[m]["proc_min"]
            s_min = machine_metrics[m]["setup_min"]
            w_min = p_min + s_min
            w_hrs = w_min / 60.0
            
            ot_min = max(0, w_min - nominal_minutes)
            ot_hrs = ot_min / 60.0
            ot_cost = ot_hrs * LABOR_COST_OVERTIME_HR
            total_overtime_cost += ot_cost
            
            utilization = (w_min / nominal_minutes) * 100.0
            print(f"  - {m}: İş Yükü = {w_hrs:5.1f} sa (İşleme: {p_min/60:.1f} sa | Setup: {s_min} dk) "
                  f"| Kullanım = %{utilization:5.1f} | Fazla Mesai = +{ot_hrs:4.1f} sa")

        print(f"  Toplam Net Fazla Mesai Maliyeti: {total_overtime_cost:,.2f} TL (@ {LABOR_COST_OVERTIME_HR:.2f} TL/saat)")
        print("-" * 85)

        # SKU Adet Mutabakat Doğrulaması (Assertion)
        total_sched_units = schedule_df[schedule_df["operation_seq"] == 1]["batch_qty"].sum()
        total_sku_units = sku_plan["planned_units"].sum()
        print(f"MUTABAKAT: SKU Planı = {total_sku_units} adet | Çizelgelenen = {total_sched_units} adet")
        assert total_sched_units == total_sku_units, f"Adet uyuşmazlığı! {total_sched_units} != {total_sku_units}"
        print("  [BAŞARILI] SKU Hedefleri ile Çizelgeleme Adetleri %100 Birebir Eşleşti.")
        print("-" * 85)

        print("ÇİZELGE ÖZETİ (İlk 10 Operasyon & Fiili Setup):")
        cols_to_show = ["batch_id", "machine_id", "setup_before_min", "start_min", "end_min", "duration_min"]
        print(schedule_df[cols_to_show].head(10).to_string(index=False))
        print("=" * 85)

        os.makedirs(os.path.dirname(OUTPUT_SCHEDULE_PATH), exist_ok=True)
        schedule_df.to_csv(OUTPUT_SCHEDULE_PATH, index=False)

        conn = sqlite3.connect(DB_PATH)
        schedule_df.to_sql("production_schedule", conn, index=False, if_exists="replace")
        conn.close()

        print(f"[OK] Çizelge Kaydedildi: {OUTPUT_SCHEDULE_PATH}")
        print(f"[OK] SQLite 'production_schedule' tablosu 'setup_before_min' ile güncellendi.")
        print("=" * 85)
    else:
        print("[HATA] CP-SAT uygun bir çözüm bulamadı!")

if __name__ == "__main__":
    solve_cpsat_schedule()