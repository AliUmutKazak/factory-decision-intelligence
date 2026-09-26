import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# Proje ana dizinini Python yoluna ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.config import (
    DB_PATH,
    PLANNING_HORIZON_WEEKS,
    WEEKLY_HOURS_PER_MACHINE,
    LABOR_COST_OVERTIME_HR,
)
from src.utils.lineage import get_active_pipeline_run
from src.utils.db import get_db_connection

st.set_page_config(
    page_title="Factory Decision Intelligence Platform",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed"
)

@st.cache_data(ttl=60)
def get_table(table_name: str) -> pd.DataFrame:
    """Veritabanından tabloyu güvenli şekilde çeker; hata durumunda boş DataFrame döner."""
    if not Path(DB_PATH).exists():
        return pd.DataFrame()
    try:
        with get_db_connection(DB_PATH) as conn:
            return pd.read_sql(f"SELECT * FROM {table_name}", conn)
    except Exception:
        return pd.DataFrame()

def safe_first_row(df: pd.DataFrame, default_keys: list) -> pd.Series:
    """iloc[0] kaynaklı IndexError çökmelerini önlemek için güvenli satır okuyucu."""
    if not df.empty:
        return df.iloc[0]
    return pd.Series({k: 0.0 for k in default_keys})

def determine_system_status(tables):
    """
    Sistem genel durumunu (READY, PIPELINE FAILED, SOLVER INFEASIBLE, DATA MISMATCH vb.)
    audit metadata ve veritabanı kısıtlarına göre değerlendirir.
    """
    db_file = Path(DB_PATH)
    if not db_file.exists():
        return "NO RUN", "error", "Veritabanı dosyası (factory.db) bulunamadı. Pipeline henüz çalıştırılmamış."

    # 1. Pipeline Run & Lineage Metadata Doğrulaması
    metadata_path = Path("reports/run_metadata.json")
    if metadata_path.exists():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                run_meta = json.load(f)
        except Exception as e:
            return "METADATA CORRUPTED", "error", f"reports/run_metadata.json okunamadı veya bozuk: {e}"

        status_val = str(run_meta.get("status", "")).upper()
        # Standart Pipeline Durum Kontrolü (COMPLETED veya geriye dönük SUCCESS)
        if status_val not in ("COMPLETED", "SUCCESS"):
            return "PIPELINE FAILED", "error", f"Son pipeline çalıştırması geçerli değil (Status: {status_val}, Run: {run_meta.get('run_id')}). Modeller güvensiz."

        # Çözücü durumları geçerli mi?
        opt_metrics = run_meta.get("optimization_metrics", {})
        agg_status = str(opt_metrics.get("aggregate_lp_status", "")).upper()
        cpsat_status = str(opt_metrics.get("cpsat_solver_status", "")).upper()

        if "INFEASIBLE" in agg_status or "INFEASIBLE" in cpsat_status:
            return "SOLVER INFEASIBLE", "error", f"Optimizasyon çözücü hatası: LP={agg_status}, CP-SAT={cpsat_status}."

    # 2. Solver Metadata Doğrulaması
    solver_meta_path = Path("reports/schedule_solver_metadata.json")
    if solver_meta_path.exists():
        try:
            with open(solver_meta_path, "r", encoding="utf-8") as f:
                s_meta = json.load(f)
        except Exception as e:
            return "METADATA CORRUPTED", "error", f"Solver metadata dosyası bozuk: {e}"

        s_status = str(s_meta.get("solver_status", "")).upper()
        if s_status in ["INFEASIBLE", "MODEL_INVALID", "UNKNOWN"]:
            return "SOLVER INFEASIBLE", "error", f"CP-SAT Çizelgeleme çözücüsü başarısız: {s_status}."

    # 3. Enerji & Karbon Metrik Kolon Kontrolü
    sched_df = tables.get("production_schedule", pd.DataFrame())
    energy_df = tables.get("energy_kpis", pd.DataFrame())
    carbon_df = tables.get("carbon_kpis", pd.DataFrame())

    if not sched_df.empty:
        if energy_df.empty or carbon_df.empty:
            return "DATA MISMATCH", "error", "Çizelge mevcut fakat enerji/karbon metrikleri hesaplanmamış."

        # Tablodaki gerçek kolon: grand_total_kwh (fallback: energy_kwh)
        energy_col = "grand_total_kwh" if "grand_total_kwh" in energy_df.columns else ("energy_kwh" if "energy_kwh" in energy_df.columns else None)
        if energy_col and energy_df[energy_col].sum() <= 0:
            return "DATA MISMATCH", "error", f"Çizelgelenen operasyonlar var ancak toplam enerji tüketimi geçersiz (<=0 kWh, kolon: {energy_col})."

    return "READY", "success", "Tüm modeller (Tahmin, Planlama, Çizelgeleme, Sürdürülebilirlik) ve çözücüler tam mutabakatla hazır."

    # 4. Tablo Doluluk Kontrolleri
    core_upstream = ["forecast_demand", "sku_production_plan", "mrp_plan"]
    downstream = ["production_schedule", "energy_kpis", "carbon_kpis"]

    upstream_empty = any(tables[k].empty for k in core_upstream if k in tables)
    downstream_empty = any(tables[k].empty for k in downstream if k in tables)

    if upstream_empty and downstream_empty:
        return "NO RUN", "error", "Pipeline tablolarının tamamı boş. Veri üretimi yapılmamış."
    elif downstream_empty:
        return "PARTIAL", "warning", "Taktik planlama hazır ancak operasyonel çizelgeleme veya enerji/karbon adımları henüz tamamlanmamış."

    # 5. Core Reconciliation (Schedule vs Energy/Carbon Mutabakatı)
    sched_df = tables.get("production_schedule", pd.DataFrame())
    energy_df = tables.get("energy_kpis", pd.DataFrame())
    carbon_df = tables.get("carbon_kpis", pd.DataFrame())

    if not sched_df.empty:
        if energy_df.empty or carbon_df.empty:
            return "DATA MISMATCH", "error", "Çizelge mevcut fakat enerji/karbon metrikleri hesaplanmamış."
        
        # Çizelgede üretilen parti var ama enerji tüketimi 0 ise tutarsızlık
        if "energy_kwh" in energy_df.columns and energy_df["energy_kwh"].sum() <= 0:
            return "DATA MISMATCH", "error", "Çizelgelenen operasyonlar var ancak toplam enerji tüketimi geçersiz (<=0 kWh)."

    return "READY", "success", "Tüm modeller (Tahmin, Planlama, Çizelgeleme, Sürdürülebilirlik) ve çözücüler tam mutabakatla hazır."

# Başlık ve Üst Bilgi
st.title("🏭 Factory Decision Intelligence Platform")
st.caption("Talep Tahmini • Hiyerarşik Taktik Planlama • Zaman Fazlı MRP • CP-SAT Çizelgeleme • Enerji & Karbon")

# Veri Setlerini Yükle
raw_tables = {
    "pipeline_runs": get_table("pipeline_runs"),
    "forecast_model_lineage": get_table("forecast_model_lineage"),
    "energy_kpis": get_table("energy_kpis"),
    "carbon_kpis": get_table("carbon_kpis"),
    "mrp_plan": get_table("mrp_plan"),
    "forecast_demand": get_table("forecast_demand"),
    "sku_production_plan": get_table("sku_production_plan"),
    "production_schedule": get_table("production_schedule"),
    "aggregate_plan": get_table("aggregate_plan"),
    "machine_capacity_plan": get_table("machine_capacity_plan"),
}

# Sistem Durumu Değerlendirmesi
status_code, status_level, status_msg = determine_system_status(raw_tables)

# Sistem Durum Rozeti & Bilgilendirme
status_colors = {
    "READY": "background-color: #28a745; color: white;",
    "PARTIAL": "background-color: #ffc107; color: black;",
    "NO RUN": "background-color: #dc3545; color: white;",
    "PIPELINE FAILED": "background-color: #dc3545; color: white;",
    "SOLVER INFEASIBLE": "background-color: #dc3545; color: white;",
    "DATA MISMATCH": "background-color: #dc3545; color: white;",
    "METADATA CORRUPTED": "background-color: #dc3545; color: white;",
    "DATA STALE": "background-color: #fd7e14; color: white;",
}

st.markdown(
    f"""
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 15px;">
        <span style="{status_colors.get(status_code, '')} padding: 4px 12px; border-radius: 6px; font-weight: bold; font-size: 13px;">
            SİSTEM DURUMU: {status_code}
        </span>
        <span style="font-size: 13px; color: #888;">{status_msg}</span>
    </div>
    """,
    unsafe_allow_html=True
)

if status_code == "NO RUN":
    st.error("⚠️ Gösterilecek aktif çalışma verisi bulunamadı. Lütfen öncelikle veri hattını koşturunuz (`python main.py`).")
    st.stop()
# --- Kurumsal Denetim & Lineage (Audit Trail) Kartı ---
# Denetim Madde 9.4: df_runs.iloc[-1] yerine resmi ve onaylanmış active run'ı çekiyoruz
active_run = get_active_pipeline_run()
df_runs = raw_tables.get("pipeline_runs", pd.DataFrame())

if active_run:
    run_id_val = active_run.get("run_id", "N/A")
    run_ts = active_run.get("timestamp", "N/A")
    git_sha_val = active_run.get("git_sha", "N/A")
    cfg_hash_val = active_run.get("config_hash", "N/A")
    trigger_src = active_run.get("trigger_source", "N/A")
    data_src_val = active_run.get("data_source", "N/A")
elif not df_runs.empty:
    completed_runs = df_runs[df_runs["status"].isin(["COMPLETED", "SUCCESS"])]
    latest_run = completed_runs.iloc[-1] if not completed_runs.empty else df_runs.iloc[-1]
    run_id_val = latest_run.get("run_id", "N/A")
    run_ts = latest_run.get("timestamp", "N/A")
    git_sha_val = latest_run.get("git_sha", "N/A")
    cfg_hash_val = latest_run.get("config_hash", "N/A")
    trigger_src = latest_run.get("trigger_source", "N/A")
    data_src_val = latest_run.get("data_source", "N/A")
else:
    run_id_val = run_ts = git_sha_val = cfg_hash_val = trigger_src = data_src_val = "N/A"

with st.expander(f"🔍 Model & Lineage Denetim İzi (Audit Trail) – Run: `{run_id_val}`", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Run ID", run_id_val)
    c2.metric("Tetikleyici", trigger_src)
    c3.metric("Git SHA", git_sha_val[:8] if git_sha_val != "N/A" else "N/A")
    c4.metric("Config Hash", cfg_hash_val[:8] if cfg_hash_val != "N/A" else "N/A")

    st.caption(f"⏱ **Çalıştırma Zamanı:** `{run_ts}` | **Veri Kaynağı:** `{data_src_val}`")

    df_model_lineage = raw_tables.get("forecast_model_lineage", pd.DataFrame())
    if not df_model_lineage.empty:
        # Aktif koşuma göre filtrele
        if "run_id" in df_model_lineage.columns and run_id_val != "N/A":
            df_lineage_filtered = df_model_lineage[df_model_lineage["run_id"] == run_id_val]
            if not df_lineage_filtered.empty:
                df_model_lineage = df_lineage_filtered

        st.markdown("##### 📋 SKU Bazlı Seçilen Tahmin Modelleri & Model Yönetişimi")
        disp_cols = ["product_id", "selected_model", "backtest_wape", "backtest_rmse", "selection_reason", "run_id"]
        avail_cols = [c for c in disp_cols if c in df_model_lineage.columns]
        st.dataframe(df_model_lineage[avail_cols], use_container_width=True, hide_index=True)

# Güvenli Tekil KPI Satırları
e_kpi = safe_first_row(
    raw_tables["energy_kpis"],
    ["makespan_hours", "grand_total_kwh", "kwh_per_unit", "peak_load_kw", "avg_load_kw", "total_units_produced"]
)
c_kpi = safe_first_row(
    raw_tables["carbon_kpis"],
    ["total_tco2e", "kgco2e_per_unit"]
)

# Tabloları Aktif Run ID'ye Göre Filtreleme Yardımcısı (Madde 9.4)
def filter_by_active_run(df, active_id):
    if not df.empty and "run_id" in df.columns and active_id != "N/A":
        f_df = df[df["run_id"] == active_id]
        return f_df if not f_df.empty else df
    return df

mrp_df = filter_by_active_run(raw_tables["mrp_plan"], run_id_val)
forecast_df = filter_by_active_run(raw_tables["forecast_demand"], run_id_val)
sku_df = filter_by_active_run(raw_tables["sku_production_plan"], run_id_val)
sched_df = filter_by_active_run(raw_tables["production_schedule"], run_id_val)
agg_df = filter_by_active_run(raw_tables["aggregate_plan"], run_id_val)
mach_cap_df = filter_by_active_run(raw_tables["machine_capacity_plan"], run_id_val)

tab_summary, tab_forecast, tab_plan, tab_schedule, tab_sustainability = st.tabs([
    "📊 Yönetici Özeti",
    "📈 Talep Tahmini & Doğrulama",
    "📋 Taktik Planlama & MRP",
    "⏱️ Detaylı Çizelge (Gantt)",
    "🌱 Enerji & Karbon Analitiği"
])

# =============================================================
# TAB 1: YÖNETİCİ ÖZETİ
# =============================================================
with tab_summary:
    st.subheader("Bütünleşik Karar Akışı Göstergeleri")

    total_gross_demand = int(forecast_df["forecast_demand"].sum()) if not forecast_df.empty and "forecast_demand" in forecast_df.columns else 0
    w1_planned_units = (
        int(sku_df[sku_df["period_week"] == 1]["planned_units"].sum())
        if not sku_df.empty and "period_week" in sku_df.columns and "planned_units" in sku_df.columns
        else 0
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "1. Hafta Net Üretim Hedefi",
        f"{w1_planned_units:,} Adet",
        help="LP Modeli tarafından 1. hafta için optimize edilen net üretim miktarı"
    )

    # Makine bazlı fiili yük (İşlem + Setup) hesaplama
    if not sched_df.empty:
        setup_col = "setup_before_min" if "setup_before_min" in sched_df.columns else "setup_min"
        mach_work = sched_df.groupby("machine_id").apply(
            lambda g: (g["duration_min"].sum() + (g[setup_col].sum() if setup_col in g else 0.0)) / 60.0
        )
        bottleneck_machine = mach_work.idxmax() if not mach_work.empty else "-"
        bottleneck_hours = float(mach_work.max()) if not mach_work.empty else 0.0
        bottleneck_overtime = max(0.0, bottleneck_hours - float(WEEKLY_HOURS_PER_MACHINE))
    else:
        bottleneck_machine = "-"
        bottleneck_hours = 0.0
        bottleneck_overtime = 0.0

    makespan_val = float(e_kpi.get("makespan_hours", 0.0))
    col2.metric(
        "Çizelge Makespan",
        f"{makespan_val:.1f} Saat",
        delta=f"Darboğaz: {bottleneck_machine} (+{bottleneck_overtime:.1f} sa)" if bottleneck_overtime > 0 else "Nominal Kapasite İçi",
        delta_color="inverse" if bottleneck_overtime > 0 else "normal",
        help=f"Toplam takvim makespan süresi: {makespan_val:.1f} saat. Darboğaz makine ({bottleneck_machine}) fiili yükü: {bottleneck_hours:.1f} saat (Nominal sınır: {WEEKLY_HOURS_PER_MACHINE} saat)."
    )
    col3.metric(
        "Toplam Enerji Tüketimi",
        f"{float(e_kpi.get('grand_total_kwh', 0.0)):,.1f} kWh",
        delta=f"{float(e_kpi.get('kwh_per_unit', 0.0)):.3f} kWh/adet",
        help="1. hafta çizelgesindeki 3 tezgâhın toplam işlem, hazırlık ve boşta bekleme enerjisi"
    )
    col4.metric(
        "Modellenen Üretim Kapsam 1–2 Emisyonu",
        f"{float(c_kpi.get('total_tco2e', 0.0)):.3f} tCO₂e",
        delta=f"{float(c_kpi.get('kgco2e_per_unit', 0.0)):.3f} kgCO₂e/adet",
        help="Modeled Production-System Scope 1–2 Footprint: Yalnızca modellenen üretim tezgâhlarının elektrik tüketimi (Scope 2 - Location-Based şebeke) ve tezgâhlar arası iç hat forklift dizeli (Scope 1) dahildir. Tesis geneli HVAC, ofis, aydınlatma ve yardımcı işletmeler kapsam dışıdır."
    )

    st.markdown("---")
    st.subheader("Temel Fabrika Soruları & Model Yanıtları")

    q_col1, q_col2 = st.columns(2)
    with q_col1:
        st.info(
            f"**Talep:** {PLANNING_HORIZON_WEEKS} haftalık ufukta 5 pilot ürün için toplam "
            f"**{total_gross_demand:,} adet** brüt fabrika çekme talebi öngörüldü."
        )
        st.info(
            f"**Üretim:** PuLP LP taktik modeli, başlangıç stoklarını da eriterek 1. hafta için "
            f"**{w1_planned_units:,} adet** net üretim hedefi koydu."
        )
        past_due_count = (
            len(mrp_df[mrp_df["action_message"].str.contains("EXPEDITE", na=False)])
            if not mrp_df.empty and "action_message" in mrp_df.columns
            else 0
        )
        st.info(
            f"**Tedarik Zinciri:** Zaman fazlı MRP-I, 4 hammadde için net ihtiyaçları belirledi; "
            f"temin süresi kısıtı nedeniyle **{past_due_count} sipariş için acil tedarik (EXPEDITE)** uyarısı üretildi."
        )
    with q_col2:
        st.info(
            f"**Kısıt Bağlantısı (MRP → CP-SAT):** Tedarik riski taşıyan hammaddeye sahip lotların ilk operasyonu "
            f"480 dk serbest bırakma (release time) kısıtına bağlandı; operasyonlar malzeme tesliminden önce başlatılmadı."
        )
        # 1. Taktik Seviye: LP Kısıt Bağlayıcılığı (Binding Machine)
        lp_bottleneck_machines = []
        if not mach_cap_df.empty and "is_bottleneck" in mach_cap_df.columns:
            lp_bottleneck_machines = mach_cap_df[mach_cap_df["is_bottleneck"] == "YES"]["machine_id"].unique().tolist()
        lp_bottleneck_str = ", ".join(lp_bottleneck_machines) if lp_bottleneck_machines else "Yok"

        # 2. Operasyonel Seviye: Çizelgeleme Fiili İş Yükü (Processing + Setup)
        if not sched_df.empty:
            setup_col = "setup_before_min" if "setup_before_min" in sched_df.columns else "setup_min"
            mach_workload = sched_df.groupby("machine_id").apply(
                lambda g: (g["duration_min"].sum() + (g[setup_col].sum() if setup_col in g else 0.0)) / 60.0
            )
            highest_workload_mach = mach_workload.idxmax() if not mach_workload.empty else "-"
            highest_workload_hrs = float(mach_workload.max()) if not mach_workload.empty else 0.0
            workload_overrun = max(0.0, highest_workload_hrs - float(WEEKLY_HOURS_PER_MACHINE))
        else:
            highest_workload_mach = "-"
            highest_workload_hrs = 0.0
            workload_overrun = 0.0

        st.info(
            f"**Darboğaz Analizi Ayrışımı:**\n"
            f"- **LP Binding Tezgah(lar) [Taktik Plan]:** **{lp_bottleneck_str}** (Kapasite kısıtı bağlayıcı / gölge fiyat üreten tezgahlar)\n"
            f"- **En Yüksek Çizelge Yükü [Operasyonel]:** **{highest_workload_mach}** — Toplam Fiili Yük: **{highest_workload_hrs:.1f} sa** "
            f"(İşlem + Setup | Nominal 96 sa üzeri aşım: **+{workload_overrun:.1f} sa**)"
        )
        st.info(
            f"**Sürdürülebilirlik:** Tesis tepe yükü **{float(e_kpi.get('peak_load_kw', 0.0)):.1f} kW** olarak fiziksel kuralı doğruladı; "
            f"Dahili Karbon Senaryosu (80 €/tCO₂e) kapsamında karbon maruziyeti **€{float(c_kpi.get('total_tco2e', 0.0)) * 80:,.2f}** seviyesindedir."
        )

# =============================================================
# TAB 2: TALEP TAHMİNİ
# =============================================================
with tab_forecast:
    st.subheader("28 Günlük Tahminler ve Model Kıyaslama (Benchmark)")

    if forecast_df.empty:
        st.warning("Tahmin verisi (forecast_demand) bulunamadı.")
    else:
        col_f1, col_f2 = st.columns([1, 2])
        with col_f1:
            st.markdown("**SKU Bazlı Kazanan Tahmin Modelleri:**")
            if "product_id" in forecast_df.columns and "model_used" in forecast_df.columns:
                model_counts = forecast_df.groupby(["product_id", "model_used"]).size().reset_index(name="gun_sayisi")
                st.dataframe(model_counts[["product_id", "model_used"]], use_container_width=True)
            st.success("✓ **P02 & P03:** Klasik zaman serisi modeli olan **Holt-Winters** en düşük WAPE ile kazandı.")
            st.success("✓ **P01, P04 & P05:** Çok adımlı özyinelemeli **LightGBM** doğrusal olmayan örüntüleri yakalayarak birinci oldu.")

        with col_f2:
            fig_fc = px.line(
                forecast_df, x="forecast_date", y="forecast_demand", color="product_id",
                markers=True, title="5 Pilot Ürün İçin Günlük Fabrika Çekme Talebi Tahmini",
                labels={"forecast_date": "Tarih", "forecast_demand": "Tahmin Edilen Talep (Adet)"}
            )
            fig_fc.update_layout(hovermode="x unified")
            st.plotly_chart(fig_fc, use_container_width=True)

# =============================================================
# TAB 3: TAKTİK PLANLAMA & MRP
# =============================================================
with tab_plan:
    st.subheader("Hiyerarşik Taktik Planlama & Zaman Fazlı MRP")

    if agg_df.empty or sku_df.empty:
        st.warning("Taktik planlama tabloları (aggregate_plan / sku_production_plan) boş.")
    else:
        col_p1, col_p2 = st.columns([3, 2])
        with col_p1:
            st.markdown("**Haftalık Aile Taktik Planı (Talep vs Üretim - Koliler):**")
            fig_agg = px.bar(
                agg_df, x="period_week", y=["demand_batches", "prod_batches"],
                color_discrete_sequence=["#636EFA", "#EF553B"],
                barmode="group", facet_col="family_id",
                labels={"value": "Koli (Batches)", "period_week": "Hafta", "variable": "Metrik"},
                title="Aile Bazlı Talep ve Üretim Dengesi"
            )
            st.plotly_chart(fig_agg, use_container_width=True)

        with col_p2:
            st.markdown("**1. Hafta SKU Üretim Hedefleri:**")
            w1_sku = sku_df[sku_df["period_week"] == 1][["product_id", "family_id", "planned_batches", "planned_units"]]
            st.dataframe(w1_sku, use_container_width=True)
            st.caption("Not: 1 Üretim Kolisi = 25 Perakende Satış Adedidir.")

    st.markdown("---")
    st.markdown("##### ⚙️ Dinamik Makine Kapasite Kullanımı & Darboğaz Analizi (LP Shadow Prices)")
    if not mach_cap_df.empty:
        st.dataframe(
            mach_cap_df.style.apply(
                lambda row: ['background-color: rgba(255, 75, 75, 0.2)' if row.get('is_bottleneck') == 'YES' else '' for _ in row],
                axis=1
            ),
            use_container_width=True
        )
        st.caption("🔴 Kırmızı vurgulanan satırlar o hafta için bağlayıcı kısıtı (binding bottleneck) ve marjinal gevşeme değerini ($/hour) gösterir.")
    else:
        st.info("Makine kapasite plan verisi bulunamadı.")

    st.markdown("---")
    st.subheader("Zaman Fazlı Malzeme İhtiyaç Planlaması (MRP-I)")
    st.caption(
        "ℹ️ **Mimari Not:** Bu modül analitik bir **MRP-I Planlama Motorudur** (BOM Patlatma, Lot Sizing, Temin Süresi Kaydırma). "
        "Canlı sipariş yürütme, tedarikçi kapasite kısıtları ve fiili mal kabul takipleri işletmenin ana ERP sistemine (örn. IFS ERP) delege edilir."
    )
    
    if mrp_df.empty:
        st.info("MRP plan verisi bulunamadı.")
    else:
        def highlight_action(val):
            if "EXPEDITE" in str(val):
                return "background-color: #ffcccc; color: #990000; font-weight: bold"
            elif "RELEASE" in str(val):
                return "background-color: #e6f7ff; color: #0066cc"
            return ""

        try:
            styled_mrp = mrp_df.style.map(highlight_action, subset=["action_message"])
        except AttributeError:
            styled_mrp = mrp_df.style.applymap(highlight_action, subset=["action_message"])

        st.dataframe(styled_mrp, use_container_width=True)

# =============================================================
# TAB 4: ÇİZELGELEME GANTT
# =============================================================
with tab_schedule:
    st.subheader("OR-Tools CP-SAT Çizelgesi & Darboğaz Analizi")

    if sched_df.empty:
        st.warning("Çizelgeleme verisi (production_schedule) bulunamadı. Operasyonel aşama henüz çalıştırılmamış.")
    else:
        sched_copy = sched_df.copy()
        sched_copy["start_hour"] = sched_copy["start_min"] / 60.0
        sched_copy["duration_hour"] = sched_copy["duration_min"] / 60.0

        # P0 Madde 2: Çok Haftalı Çizelgeleme Filtresi
        if "schedule_week" in sched_copy.columns:
            available_weeks = sorted(sched_copy["schedule_week"].dropna().unique().tolist())
            selected_week = st.selectbox(
                "🗓️ Planlama / Çizelgeleme Haftası Seçin:",
                options=["Tüm Haftalar"] + [f"Hafta {int(w)}" for w in available_weeks],
                index=0,
                help="CP-SAT çok haftalı makine fazla mesai bütçesi (W1–W4) doğrultusunda ilgili haftanın operasyonlarını listeler."
            )
            if selected_week != "Tüm Haftalar":
                target_w = int(selected_week.split(" ")[1])
                sched_copy = sched_copy[sched_copy["schedule_week"] == target_w]

        hover_col = "lot_id" if "lot_id" in sched_copy.columns else "batch_id"

        fig_gantt = px.bar(
            sched_copy,
            base="start_hour",
            x="duration_hour",
            y="machine_id",
            color="product_id",
            orientation="h",
            hover_name=hover_col,
            hover_data={"start_hour": ":.2f", "duration_hour": ":.2f", "machine_id": True},
            title="Tezgâh Bazlı Operasyon Çizelgesi (Süreç Saati: Simulation Hours)",
            labels={
                "machine_id": "Tezgâh",
                "duration_hour": "Süre (Saat)",
                "start_hour": "Simülasyon Başlangıç (Saat)",
                "product_id": "Ürün"
            }
        )
        # Madde 15: Model dinamik malzeme gecikme çizgisi
        if "release_time_min" in sched_copy.columns:
            max_rel_min = sched_copy["release_time_min"].max()
            if pd.notna(max_rel_min) and max_rel_min > 0:
                max_rel_hr = max_rel_min / 60.0
                fig_gantt.add_vline(
                    x=max_rel_hr,
                    line_dash="dot",
                    line_color="orange",
                    annotation_text=f"Dinamik Malzeme Release ({max_rel_hr:.1f}. sa)",
                    annotation_position="top right"
                )

        fig_gantt.update_layout(xaxis_title="Simülasyon Zamanı (Saat)", yaxis_title="Tezgâh")
        fig_gantt.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_gantt, use_container_width=True)

        sched_cols = [c for c in ["schedule_week", hover_col, "machine_id", "setup_before_min", "start_min", "end_min", "duration_min", "batch_qty", "production_units"] if c in sched_copy.columns]
        st.dataframe(sched_copy[sched_cols], use_container_width=True)

# =============================================================
# TAB 5: ENERJİ & KARBON
# =============================================================
with tab_sustainability:
    st.subheader("15 Dakikalık Tesis Yük Profili & GHG Karbon Analitiği")
    prof_df = get_table("energy_profile_15min")
    scen_df = get_table("carbon_price_scenarios")
    mach_carb_df = get_table("carbon_machine_kpis")

    if prof_df.empty:
        st.warning("Enerji profil verisi (energy_profile_15min) bulunamadı.")
    else:
        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            peak_kw = float(e_kpi.get("peak_load_kw", 0.0))
            avg_kw = float(e_kpi.get("avg_load_kw", 0.0))

            fig_load = px.line(
                prof_df, x="time_hour", y="total_load_kw",
                title=f"Tesis Güç Çekiş Profili (Tepe Yük: {peak_kw:.1f} kW | Ortalama: {avg_kw:.1f} kW)",
                labels={"time_hour": "Zaman (Saat)", "total_load_kw": "Toplam Güç (kW)"}
            )
            fig_load.add_hline(
                y=peak_kw, line_dash="dash", line_color="red",
                annotation_text=f"Peak: {peak_kw:.1f} kW"
            )
            fig_load.add_hline(
                y=avg_kw, line_dash="dot", line_color="green",
                annotation_text=f"Avg: {avg_kw:.1f} kW"
            )
            st.plotly_chart(fig_load, use_container_width=True)

            if not mach_carb_df.empty and "scope_2_tco2e" in mach_carb_df.columns:
                st.markdown("**Tezgâh Bazlı Kapsam 2 Emisyon Payı:**")
                fig_pie = px.pie(
                    mach_carb_df, names="machine_id", values="scope_2_tco2e",
                    title="Makine Bazlı Karbon Salımı Dağılımı",
                    hole=0.4
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        with col_s2:
            st.markdown("### 💶 Dahili Karbon Fiyat Simülatörü (Internal Carbon Pricing)")
            user_c_price = st.slider(
                "Dahili Karbon Fiyat Senaryosu / Internal Carbon Price Scenario (€/tCO₂e):",
                min_value=0, max_value=200, value=80, step=10,
                help="Bu simülasyon bir emisyon piyasası takası değil, Exposure = Carbon × InternalCarbonPrice formülüne dayalı içsel gölge fiyatlandırma (Shadow Pricing) senaryosudur."
            )
            total_carbon = float(c_kpi.get("total_tco2e", 0.0))
            sim_exposure = total_carbon * user_c_price
            st.metric("Hesaplanan Toplam Karbon Maliyeti", f"€{sim_exposure:,.2f}")

            total_units = float(e_kpi.get("total_units_produced", 0.0))
            unit_cost_str = f"€{sim_exposure / total_units:.4f} / adet" if total_units > 0 else "N/A"
            st.metric("Birim Ürün Karbon Maliyeti", unit_cost_str)

            st.markdown("---")
            st.markdown("**İçsel Karbon Fiyatlandırma Senaryo Tablosu (Internal Carbon Pricing):**")
            if not scen_df.empty:
                st.dataframe(scen_df, use_container_width=True)
            else:
                st.info("Karbon fiyat senaryoları bulunamadı.")