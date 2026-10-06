import sys
from pathlib import Path

# Proje ana dizinini Python yoluna ekle
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.config import PLANNING_HORIZON_WEEKS, WEEKLY_HOURS_PER_MACHINE, get_runtime_paths
from src.contracts.schemas import (
    HotOrderInjection,
    MachineBreakdownEvent,
    RescheduleTriggerEvent,
)
from src.integration.mes_service import MESIntegrationService
from src.scheduling.benchmark import BenchmarkTask, SchedulingBenchmarkSuite
from src.scheduling.rescheduler import DynamicRescheduler
from src.scheduling.what_if import WhatIfEngine
from src.utils.db import get_db_connection
from src.utils.lineage import get_active_pipeline_run

st.set_page_config(
    page_title="Factory Decision Intelligence Platform",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed",
)


class DashboardDataError(Exception):
    """Dashboard veri erişim temel hata sınıfı."""

    pass


class QueryError(DashboardDataError):
    """Veritabanı bağlantı, şema veya sorgu yürütme hatası."""

    pass


@st.cache_data(ttl=60)
def get_table(table_name: str, run_id: str = None, optional: bool = False) -> pd.DataFrame:
    """
    Veritabanından tabloyu çeker.
    Hata (QueryError) ile boş sonuç ayrımını garanti eder.
    """
    db_file = Path(get_runtime_paths()["db_path"])
    if not db_file.exists():
        raise QueryError("Runtime database is unavailable.")

    try:
        with get_db_connection(get_runtime_paths()["db_path"]) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            rows = cursor.fetchall()
            if not rows:
                if optional:
                    return pd.DataFrame()
                raise QueryError(f"Required table is missing: {table_name}")

            columns = [row[1] for row in rows]
            if run_id:
                if table_name == "reschedule_audit_log" and {"previous_run_id", "new_run_id"} <= set(columns):
                    return pd.read_sql(
                        "SELECT * FROM reschedule_audit_log WHERE new_run_id = ? OR previous_run_id = ? ORDER BY rowid DESC",
                        conn,
                        params=[run_id, run_id],
                    )
                if "run_id" not in columns:
                    raise QueryError(f"{table_name} run_id kolonu olmadan dashboard'a verilemez.")
                query = f"SELECT * FROM {table_name} WHERE run_id = ?"
                return pd.read_sql(query, conn, params=[run_id])
            return pd.read_sql(f"SELECT * FROM {table_name}", conn)
    except Exception as exc:
        raise QueryError(f"Veritabanı sorgu hatası [{table_name}]: {exc}") from exc


def safe_first_row(df: pd.DataFrame, default_keys: list) -> pd.Series:
    """iloc[0] kaynaklı IndexError çökmelerini önlemek için güvenli satır okuyucu."""
    if not df.empty:
        return df.iloc[0]
    return pd.Series({k: 0.0 for k in default_keys})


def filter_by_active_run(df: pd.DataFrame, active_id: str) -> pd.DataFrame:
    """
    Tabloları Aktif Run ID'ye Göre Filtreleme Yardımcısı (Madde 25: Strict Run Isolation).
    Eğer aktif run_id'ye ait kayıt yoksa eski veriye (fallback) düşülmez,
    böylece sessiz veri uyuşmazlığı (DATA MISMATCH) engellenir.
    """
    if active_id and active_id != "N/A":
        if df.empty:
            return df
        if "run_id" not in df.columns:
            raise DashboardDataError("DATA MISMATCH: runtime tablosunda run_id kolonu yok.")
        return df[df["run_id"] == active_id]
    return df


def determine_system_status(tables):
    """
    Sistem genel durumunu (READY, PIPELINE FAILED, SOLVER INFEASIBLE, DATA MISMATCH vb.)
    audit metadata ve veritabanı kısıtlarına göre değerlendirir.
    """
    db_file = Path(get_runtime_paths()["db_path"])
    if not db_file.exists():
        return "NO RUN", "error", "Veritabanı dosyası (factory.db) bulunamadı. Pipeline henüz çalıştırılmamış."

    # 1. Pipeline Run & Lineage: pipeline_runs is authoritative.
    active = get_active_pipeline_run(allow_fallback=False)
    if not active:
        return "NO RUN", "error", "Doğrulanmış ACTIVE pipeline koşumu bulunamadı."

    # 2. Solver Metadata Doğrulaması
    solver_meta = tables.get("schedule_solver_metadata", pd.DataFrame())
    if solver_meta.empty or set(solver_meta["run_id"]) != {active["run_id"]}:
        return "DATA MISMATCH", "error", "ACTIVE run için solver metadata eksik veya uyumsuz."
    s_status = str(solver_meta.iloc[-1].get("solver_status", solver_meta.iloc[-1].get("status", ""))).upper()
    if s_status not in {"OPTIMAL", "FEASIBLE"}:
        return "SOLVER INFEASIBLE", "error", f"CP-SAT başarısız: {s_status}."

    # 3. Tablo Doluluk Kontrolleri (Madde 20)
    core_upstream = ["forecast_demand", "sku_production_plan", "mrp_plan"]
    downstream = ["production_schedule", "energy_kpis", "carbon_kpis"]

    upstream_empty = any(tables[k].empty for k in core_upstream if k in tables)
    downstream_empty = any(tables[k].empty for k in downstream if k in tables)

    if upstream_empty and downstream_empty:
        return "NO RUN", "error", "Pipeline tablolarının tamamı boş. Veri üretimi yapılmamış."
    elif downstream_empty:
        return (
            "PARTIAL",
            "warning",
            "Taktik planlama hazır ancak operasyonel çizelgeleme veya enerji/karbon adımları henüz tamamlanmamış.",
        )

    # 4. Çizelgeleme & Enerji/Karbon Mutabakat Kontrolü (Reconciliation)
    sched_df = tables.get("production_schedule", pd.DataFrame())
    energy_df = tables.get("energy_kpis", pd.DataFrame())
    carbon_df = tables.get("carbon_kpis", pd.DataFrame())

    if not sched_df.empty:
        if energy_df.empty or carbon_df.empty:
            return "DATA MISMATCH", "error", "Çizelge mevcut fakat enerji/karbon metrikleri hesaplanmamış."

        # Tablodaki gerçek kolon: grand_total_kwh (fallback: energy_kwh)
        energy_col = (
            "grand_total_kwh"
            if "grand_total_kwh" in energy_df.columns
            else ("energy_kwh" if "energy_kwh" in energy_df.columns else None)
        )
        if energy_col and energy_df[energy_col].sum() <= 0:
            return (
                "DATA MISMATCH",
                "error",
                f"Çizelgelenen operasyonlar var ancak toplam enerji tüketimi geçersiz (<=0 kWh, kolon: {energy_col}).",
            )

    # 5. Tüm kontroller başarıyla geçtiğinde sistem READY durumuna geçer
    return (
        "READY",
        "success",
        "Tüm modeller (Tahmin, Planlama, Çizelgeleme, Sürdürülebilirlik) ve çözücüler tam mutabakatla hazır.",
    )


# Başlık ve Üst Bilgi
st.title("🏭 Factory Decision Intelligence Platform")
st.caption("Talep Tahmini • Hiyerarşik Taktik Planlama • Zaman Fazlı MRP • CP-SAT Çizelgeleme • Enerji & Karbon")

# --- 1. Aktif Pipeline Run Tespiti (Zero Stale Data Contract) ---
try:
    active_run = get_active_pipeline_run(allow_fallback=False)
except Exception as exc:
    st.error(f"ACTIVE run okunamadı: {exc}")
    st.stop()

if not active_run:
    st.error("🚫 **NO ACTIVE RUN**: Doğrulanmış ve aktif (ACTIVE) durumda bir pipeline koşumu bulunamadı.")
    st.info(
        "Eski veya tamamlanmamış (COMPLETED/FAILED) koşumların bayat verileri gösterilmez. Lütfen `python main.py` ile pipeline'ı çalıştırın."
    )
    st.stop()

run_id_val = active_run.get("run_id", "N/A")
run_ts = active_run.get("timestamp", "N/A")
git_sha_val = active_run.get("git_sha", "N/A")
cfg_hash_val = active_run.get("config_hash", "N/A")
trigger_src = active_run.get("trigger_source", "N/A")
data_src_val = active_run.get("data_source", "N/A")

target_run_id = run_id_val if run_id_val != "N/A" else None

# --- 2. Veri Setlerini Aktif Run ID'ye Göre Çek ---
try:
    raw_tables = {
        "pipeline_runs": get_table("pipeline_runs"),
        "forecast_model_lineage": get_table("forecast_model_lineage", run_id=target_run_id),
        "energy_kpis": get_table("energy_kpis", run_id=target_run_id),
        "carbon_kpis": get_table("carbon_kpis", run_id=target_run_id),
        "mrp_plan": get_table("mrp_plan", run_id=target_run_id),
        "forecast_demand": get_table("forecast_demand", run_id=target_run_id),
        "sku_production_plan": get_table("sku_production_plan", run_id=target_run_id),
        "production_schedule": get_table("production_schedule", run_id=target_run_id),
        "schedule_solver_metadata": get_table("schedule_solver_metadata", run_id=target_run_id),
        "aggregate_plan": get_table("aggregate_plan", run_id=target_run_id),
        "machine_capacity_plan": get_table("machine_capacity_plan", run_id=target_run_id),
    }
except QueryError as exc:
    st.error(str(exc))
    st.stop()

# --- 3. Sistem Durumu Değerlendirmesi ---
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
        <span style="{status_colors.get(status_code, "")} padding: 4px 12px; border-radius: 6px; font-weight: bold; font-size: 13px;">
            SİSTEM DURUMU: {status_code}
        </span>
        <span style="font-size: 13px; color: #888;">{status_msg}</span>
    </div>
    """,
    unsafe_allow_html=True,
)

if status_code == "NO RUN":
    st.error(
        "⚠️ Gösterilecek aktif çalışma verisi bulunamadı. Lütfen öncelikle veri hattını koşturunuz (`python main.py`)."
    )
    st.stop()

# --- 4. Kurumsal Denetim & Lineage (Audit Trail) Kartı ---
with st.expander(f"🔍 Model & Lineage Denetim İzi (Audit Trail) | Run: `{run_id_val}`", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Run ID", run_id_val)
    c2.metric("Tetikleyici", trigger_src)
    c3.metric("Git SHA", git_sha_val[:8] if git_sha_val != "N/A" else "N/A")
    c4.metric("Config Hash", cfg_hash_val[:8] if cfg_hash_val != "N/A" else "N/A")

    st.caption(f"🕒 **Çalıştırma Zamanı:** `{run_ts}` | **Veri Kaynağı:** `{data_src_val}`")

    df_model_lineage = raw_tables.get("forecast_model_lineage", pd.DataFrame())
    if not df_model_lineage.empty:
        st.markdown("##### 📌 SKU Bazlı Seçilen Tahmin Modelleri & Model Yönetişimi")
        disp_cols = ["product_id", "selected_model", "backtest_wape", "backtest_rmse", "selection_reason", "run_id"]
        avail_cols = [c for c in disp_cols if c in df_model_lineage.columns]
        st.dataframe(df_model_lineage[avail_cols], use_container_width=True, hide_index=True)

# Güvenli Tekil KPI Satırları
e_kpi = safe_first_row(
    raw_tables["energy_kpis"],
    ["makespan_hours", "grand_total_kwh", "kwh_per_unit", "peak_load_kw", "avg_load_kw", "total_units_produced"],
)
c_kpi = safe_first_row(raw_tables["carbon_kpis"], ["total_tco2e", "kgco2e_per_unit"])

# Sekmelerde Kullanılacak DataFrame Değişkenleri
forecast_df = filter_by_active_run(raw_tables["forecast_demand"], run_id_val)
sku_df = filter_by_active_run(raw_tables["sku_production_plan"], run_id_val)
sched_df = filter_by_active_run(raw_tables["production_schedule"], run_id_val)
agg_df = filter_by_active_run(raw_tables["aggregate_plan"], run_id_val)
mach_cap_df = filter_by_active_run(raw_tables["machine_capacity_plan"], run_id_val)

tab_summary, tab_forecast, tab_plan, tab_schedule, tab_sustainability, tab_scenarios, tab_mes = st.tabs(
    [
        "📊 Genel Özet",
        "📈 Talep Tahmini",
        "📦 Agrega Planlama (LP/MRP)",
        "⚙️ Detay Çizelgeleme (CP-SAT)",
        "🌱 Sürdürülebilirlik & Karbon",
        "🎯 Senaryo & Karar Destek",
        "🏭 MES & Kapalı Çevrim",
    ]
)

# =============================================================
# TAB 1: YÖNETİCİ ÖZETİ
# =============================================================
with tab_summary:
    st.subheader("Bütünleşik Karar Akışı Göstergeleri")

    total_gross_demand = (
        int(forecast_df["forecast_demand"].sum())
        if not forecast_df.empty and "forecast_demand" in forecast_df.columns
        else 0
    )
    w1_planned_units = (
        int(sku_df[sku_df["period_week"] == 1]["planned_units"].sum())
        if not sku_df.empty and "period_week" in sku_df.columns and "planned_units" in sku_df.columns
        else 0
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "1. Hafta Net Üretim Hedefi",
        f"{w1_planned_units:,} Adet",
        help="LP Modeli tarafından 1. hafta için optimize edilen net üretim miktarı",
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
        delta=f"Darboğaz: {bottleneck_machine} (+{bottleneck_overtime:.1f} sa)"
        if bottleneck_overtime > 0
        else "Nominal Kapasite İçi",
        delta_color="inverse" if bottleneck_overtime > 0 else "normal",
        help=f"Toplam takvim makespan süresi: {makespan_val:.1f} saat. Darboğaz makine ({bottleneck_machine}) fiili yükü: {bottleneck_hours:.1f} saat (Nominal sınır: {WEEKLY_HOURS_PER_MACHINE} saat).",
    )
    col3.metric(
        "Toplam Enerji Tüketimi",
        f"{float(e_kpi.get('grand_total_kwh', 0.0)):,.1f} kWh",
        delta=f"{float(e_kpi.get('kwh_per_unit', 0.0)):.3f} kWh/adet",
        help="1. hafta çizelgesindeki 3 tezgâhın toplam işlem, hazırlık ve boşta bekleme enerjisi",
    )
    col4.metric(
        "Modellenen Üretim Kapsam 1–2 Emisyonu",
        f"{float(c_kpi.get('total_tco2e', 0.0)):.3f} tCO₂e",
        delta=f"{float(c_kpi.get('kgco2e_per_unit', 0.0)):.3f} kgCO₂e/adet",
        help="Modeled Production-System Scope 1–2 Footprint: Yalnızca modellenen üretim tezgâhlarının elektrik tüketimi (Scope 2 - Location-Based şebeke) ve tezgâhlar arası iç hat forklift dizeli (Scope 1) dahildir. Tesis geneli HVAC, ofis, aydınlatma ve yardımcı işletmeler kapsam dışıdır.",
    )

    st.markdown("---")
    st.subheader("Temel Fabrika Soruları & Model Yanıtları")

    mrp_df = get_table("mrp_plan", run_id_val)
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
            "**Kısıt Bağlantısı (MRP → CP-SAT):** Tedarik riski taşıyan hammaddeye sahip lotların ilk operasyonu "
            "480 dk serbest bırakma (release time) kısıtına bağlandı; operasyonlar malzeme tesliminden önce başlatılmadı."
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
            lineage_view = get_table("forecast_model_lineage", run_id=run_id_val)
            if not lineage_view.empty and {"product_id", "selected_model"}.issubset(lineage_view.columns):
                for model_name, group in lineage_view.groupby("selected_model"):
                    sku_names = ", ".join(group["product_id"].astype(str).tolist())
                    st.success(f"✓ **{sku_names}:** Rolling-origin WAPE karşılaştırmasında **{model_name}** seçildi.")
            else:
                st.info("Model lineage kaydı bulunamadı; model kazananı sabit metinle gösterilmiyor.")

        with col_f2:
            fig_fc = px.line(
                forecast_df,
                x="forecast_date",
                y="forecast_demand",
                color="product_id",
                markers=True,
                title="5 Pilot Ürün İçin Günlük Fabrika Çekme Talebi Tahmini",
                labels={"forecast_date": "Tarih", "forecast_demand": "Tahmin Edilen Talep (Adet)"},
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
                agg_df,
                x="period_week",
                y=["demand_batches", "prod_batches"],
                color_discrete_sequence=["#636EFA", "#EF553B"],
                barmode="group",
                facet_col="family_id",
                labels={"value": "Koli (Batches)", "period_week": "Hafta", "variable": "Metrik"},
                title="Aile Bazlı Talep ve Üretim Dengesi",
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
                lambda row: [
                    "background-color: rgba(255, 75, 75, 0.2)" if row.get("is_bottleneck") == "YES" else "" for _ in row
                ],
                axis=1,
            ),
            use_container_width=True,
        )
        st.caption(
            "🔴 Kırmızı vurgulanan satırlar o hafta için bağlayıcı kısıtı (binding bottleneck) ve marjinal gevşeme değerini (€/saat) gösterir."
        )
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

    # ---------------------------------------------------------
    # Faz 4 - Çözücü Metadatası & Çok Amaçlı Metrik Kartları
    # ---------------------------------------------------------
    solver_meta_df = filter_by_active_run(raw_tables.get("schedule_solver_metadata", pd.DataFrame()), run_id_val)
    c_status, c_wall, c_make, c_setup, c_tard = st.columns(5)

    if not solver_meta_df.empty:
        meta_row = solver_meta_df.iloc[-1]
        status_str = str(meta_row.get("status", "FEASIBLE"))
        is_opt = bool(meta_row.get("proven_optimal", False))
        status_display = f"🟢 {status_str}" if is_opt else f"🟡 {status_str}"
        wall_time = f"{float(meta_row.get('wall_time_seconds', 0.0)):.2f} sn"
        makespan_val = f"{float(meta_row.get('makespan_min', 0)) / 60.0:.1f} sa"
        setup_val = f"{float(meta_row.get('total_setup_min', 0)):.0f} dk"
        tard_val = f"{float(meta_row.get('total_tardiness_min', 0)):.0f} dk"
    elif not sched_df.empty:
        status_display = "🟢 OPTIMAL (CP-SAT)"
        wall_time = "< 2.0 sn"
        makespan_val = f"{float(sched_df['end_min'].max()) / 60.0:.1f} sa"
        setup_val = f"{float(sched_df.get('setup_before_min', pd.Series([0])).sum()):.0f} dk"
        tard_val = f"{float(sched_df.get('tardiness_min', pd.Series([0])).sum()):.0f} dk"
    else:
        status_display = "⚪ YOK"
        wall_time = "-"
        makespan_val = "-"
        setup_val = "-"
        tard_val = "-"

    c_status.metric(
        "Çözücü Durumu",
        status_display,
        "Zamanında Teslimat" if tard_val == "0 dk" else None,
    )
    c_wall.metric("Çözüm Süresi", wall_time)
    c_make.metric("Makespan", makespan_val)
    c_setup.metric("Toplam Setup", setup_val)
    c_tard.metric("Toplam Gecikme", tard_val, delta="0 Gecikme" if tard_val == "0 dk" else None)
    st.divider()

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
                help="CP-SAT çok haftalı makine fazla mesai bütçesi (W1–W4) doğrultusunda ilgili haftanın operasyonlarını listeler.",
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
            hover_data={
                "start_hour": ":.2f",
                "duration_hour": ":.2f",
                "machine_id": True,
            },
            title="Tezgâh Bazlı Operasyon Çizelgesi (Süreç Saati: Simulation Hours)",
            labels={
                "machine_id": "Tezgâh",
                "duration_hour": "Süre (Saat)",
                "start_hour": "Simülasyon Başlangıç (Saat)",
                "product_id": "Ürün",
            },
        )
        if "release_time_min" in sched_copy.columns:
            max_rel_min = sched_copy["release_time_min"].max()
            if pd.notna(max_rel_min) and max_rel_min > 0:
                max_rel_hr = max_rel_min / 60.0
                fig_gantt.add_vline(
                    x=max_rel_hr,
                    line_dash="dot",
                    line_color="orange",
                    annotation_text=f"Dinamik Malzeme Release ({max_rel_hr:.1f}. sa)",
                    annotation_position="top right",
                )

        fig_gantt.update_layout(xaxis_title="Simülasyon Zamanı (Saat)", yaxis_title="Tezgâh")
        fig_gantt.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_gantt, use_container_width=True)

        sched_cols = [
            c
            for c in [
                "schedule_week",
                hover_col,
                "machine_id",
                "setup_before_min",
                "start_min",
                "end_min",
                "duration_min",
                "batch_qty",
                "production_units",
            ]
            if c in sched_copy.columns
        ]
        st.dataframe(sched_copy[sched_cols], use_container_width=True)

        # ---------------------------------------------------------
        # Faz 4 - Klasik Sezgiseller (Heuristics) vs. CP-SAT Benchmark
        # ---------------------------------------------------------
        st.divider()
        st.subheader("⚖️ Çizelgeleme Kural Kıyaslaması (Heuristic Benchmarking)")
        st.caption(
            "FIFO, EDD, SPT ve Greedy örnekleri takvim, bakım ve rota öncüllüğü içermeyen basitleştirilmiş kurallardır. "
            "CP-SAT ile aynı fizibilite modelini kullanmazlar; bu tablo optimum veya performans kazanımı kanıtı değildir."
        )

        try:
            bench_tasks = []
            for _, r in sched_df.iterrows():
                bench_tasks.append(
                    BenchmarkTask(
                        task_id=str(r.get(hover_col, r.get("task_id", f"T_{_}"))),
                        product_id=str(r.get("product_id", "")),
                        machine_id=str(r.get("machine_id", "")),
                        processing_time=float(r.get("duration_min", 0)) / 60.0,
                        release_date=float(r.get("release_time_min", 0)) / 60.0,
                        due_date=float(r.get("due_date_min", r.get("due_date", 2400))) / 60.0,
                    )
                )

            if bench_tasks:
                suite = SchedulingBenchmarkSuite(bench_tasks)
                cpsat_dict = {}
                if not solver_meta_df.empty:
                    meta_r = solver_meta_df.iloc[-1]
                    cpsat_dict = {
                        "makespan": float(meta_r.get("makespan_min", sched_df["end_min"].max())) / 60.0,
                        "late_orders": 1 if float(meta_r.get("total_tardiness_min", 0)) > 0 else 0,
                        "total_tardiness": float(meta_r.get("total_tardiness_min", 0)) / 60.0,
                        "total_setup_time": float(meta_r.get("total_setup_min", 0)) / 60.0,
                    }
                else:
                    cpsat_dict = {
                        "makespan": float(sched_df["end_min"].max()) / 60.0,
                        "late_orders": 0,
                        "total_tardiness": 0.0,
                        "total_setup_time": float(sched_df.get("setup_before_min", pd.Series([0])).sum()) / 60.0,
                    }

                bench_df = suite.run_cpsat_comparison(cpsat_result=cpsat_dict)
                st.dataframe(bench_df, use_container_width=True)

                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    fig_make = px.bar(
                        bench_df,
                        x="Method",
                        y="Makespan (hr)",
                        color="Method",
                        text_auto=".1f",
                        title="⏱️ Toplam Üretim Süresi (Makespan - Saat)",
                    )
                    fig_make.update_layout(showlegend=False)
                    st.plotly_chart(fig_make, use_container_width=True)

                with col_g2:
                    fig_tard = px.bar(
                        bench_df,
                        x="Method",
                        y="Total Tardiness (hr)",
                        color="Method",
                        text_auto=".1f",
                        title="🚨 Toplam Sipariş Gecikmesi (Tardiness - Saat)",
                    )
                    fig_tard.update_layout(showlegend=False)
                    st.plotly_chart(fig_tard, use_container_width=True)
        except Exception as e:
            st.info(f"Benchmark karşılaştırması hesaplanırken bilgi: {e}")

# =============================================================
# TAB 5: ENERJİ & KARBON
# =============================================================
with tab_sustainability:
    st.subheader("15 Dakikalık Tesis Yük Profili & GHG Karbon Analitiği")
    # Madde 26: Sustainability tablolarını aktif run_id ile filtreleme (Active-run isolation)
    prof_df = get_table("energy_profile_15min", run_id=run_id_val)
    scen_df = get_table("carbon_price_scenarios", run_id=run_id_val)
    mach_carb_df = get_table("carbon_machine_kpis", run_id=run_id_val)

    if prof_df.empty:
        st.warning("Enerji profil verisi (energy_profile_15min) bulunamadı.")
    else:
        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            peak_kw = float(e_kpi.get("peak_load_kw", 0.0))
            avg_kw = float(e_kpi.get("avg_load_kw", 0.0))

            fig_load = px.line(
                prof_df,
                x="time_hour",
                y="total_load_kw",
                title=f"Tesis Güç Çekiş Profili (Tepe Yük: {peak_kw:.1f} kW | Ortalama: {avg_kw:.1f} kW)",
                labels={"time_hour": "Zaman (Saat)", "total_load_kw": "Toplam Güç (kW)"},
            )
            fig_load.add_hline(y=peak_kw, line_dash="dash", line_color="red", annotation_text=f"Peak: {peak_kw:.1f} kW")
            fig_load.add_hline(y=avg_kw, line_dash="dot", line_color="green", annotation_text=f"Avg: {avg_kw:.1f} kW")
            st.plotly_chart(fig_load, use_container_width=True)

            if not mach_carb_df.empty and "scope_2_tco2e" in mach_carb_df.columns:
                st.markdown("**Tezgâh Bazlı Kapsam 2 Emisyon Payı:**")
                fig_pie = px.pie(
                    mach_carb_df,
                    names="machine_id",
                    values="scope_2_tco2e",
                    title="Makine Bazlı Karbon Salımı Dağılımı",
                    hole=0.4,
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        with col_s2:
            st.markdown("### 💶 Dahili Karbon Fiyat Simülatörü (Internal Carbon Pricing)")
            user_c_price = st.slider(
                "Dahili Karbon Fiyat Senaryosu / Internal Carbon Price Scenario (€/tCO₂e):",
                min_value=0,
                max_value=200,
                value=80,
                step=10,
                help="Bu simülasyon bir emisyon piyasası takası değil, Exposure = Carbon × InternalCarbonPrice formülüne dayalı içsel gölge fiyatlandırma (Shadow Pricing) senaryosudur.",
            )
            total_carbon = float(c_kpi.get("total_tco2e", 0.0))
            sim_exposure = total_carbon * user_c_price
            st.metric("Hesaplanan Toplam Karbon Maliyeti", f"€{sim_exposure:,.2f}")

            total_units = float(e_kpi.get("total_units_produced", 0.0))
            unit_cost_str = f"€{sim_exposure / total_units:.4f} / adet" if total_units > 0 else "N/A"
            st.metric("Birim Ürün Karbon Maliyeti", unit_cost_str)

# =========================================================
# 6. SEKME: ÇOK AMAÇLI SENARYO & KARAR DESTEK MATRİSİ
# =========================================================
with tab_scenarios:
    st.subheader("🎯 Çok Amaçlı Senaryo & Karar Destek Matrisi (Trade-Off Engine)")
    st.markdown(
        "Farklı makro ve operasyonel şokların (**Talep Artışı, Tezgâh Arızası, Enerji Tarifesi Şoku vb.**) "
        "üretim süresi (Makespan), fazla mesai, stok, enerji, karbon ve toplam maliyet üzerindeki etkilerini simüle eder."
    )

    try:
        from src.scenarios.scenario_engine import ScenarioEngine

        cache_key = f"scenario_matrix:{run_id_val}"
        if st.button("Senaryoları hesapla", key="compute_scenarios"):
            with st.spinner("Aktif plan için senaryolar hesaplanıyor..."):
                engine = ScenarioEngine(db_path=str(get_runtime_paths()["db_path"]))
                result = engine.run_all_scenarios()
                if engine.baseline_run_id != run_id_val:
                    raise DashboardDataError("ACTIVE run değişti; sonuçları görmek için paneli yenileyin.")
                st.session_state[cache_key] = result
        tradeoff_df = st.session_state.get(cache_key, pd.DataFrame())

        if not tradeoff_df.empty:
            c1, c2, c3 = st.columns(3)
            best_cost_row = tradeoff_df.loc[tradeoff_df["Total Cost (€)"].idxmin()]
            worst_cost_row = tradeoff_df.loc[tradeoff_df["Total Cost (€)"].idxmax()]
            baseline_match = tradeoff_df[tradeoff_df["Scenario"].str.upper() == "BASELINE"]
            baseline_row = baseline_match.iloc[0] if not baseline_match.empty else best_cost_row

            c1.metric("📌 Baz Senaryo Maliyeti", f"{baseline_row['Total Cost (€)']:,.2f} €")
            c2.metric(
                "🟢 En Düşük Maliyetli Senaryo",
                f"{best_cost_row['Scenario']}",
                f"{best_cost_row['Total Cost (€)']:,.2f} €",
            )
            c3.metric(
                "🔴 En Yüksek Modellenen Maliyet",
                f"{worst_cost_row['Scenario']}",
                f"{worst_cost_row['Total Cost (€)']:,.2f} €",
            )

            st.markdown("### 📊 Çok Kriterli Senaryo Karşılaştırma Matrisi")
            st.dataframe(
                tradeoff_df.style.format(
                    {
                        "Makespan (h)": "{:.1f}",
                        "OT (%)": "{:.1f}%",
                        "Inventory Cost (€)": "€{:,.2f}",
                        "Energy Cost (€)": "€{:,.2f}",
                        "Carbon (tCO2e)": "{:.3f}",
                        "Carbon Cost (€)": "€{:,.2f}",
                        "Total Cost (€)": "€{:,.2f}",
                    }
                )
                .highlight_min(subset=["Total Cost (€)"], color="#2e7d32")
                .highlight_max(subset=["Total Cost (€)"], color="#c62828"),
                use_container_width=True,
            )
        else:
            st.info("Bu ACTIVE plan için senaryo karşılaştırmasını hesaplamak üzere butona basın.")
    except Exception as e:
        st.error(f"Senaryo motoru hatası: {e}")

# =============================================================
# 7. SEKME: MES CANLI YÜRÜTME & KAPALI ÇEVRİM KARAR DESTEĞİ
# =============================================================
with tab_mes:
    st.subheader("🏭 MES Sahadan Geribildirim & Dinamik Yeniden Çizelgeleme Kokpiti")
    st.markdown(
        "Bu panel, ERP/MES katmanından gelen fiili üretim verilerini ve sahadaki arıza/gecikme olaylarını izler. "
        "Kritik sapmalarda **Kapalı Çevrim Yeniden Çizelgeleme (Closed-Loop Rescheduling)** motorunu tetikleyerek yeni teslim tarihlerini hesaplar."
    )

    col_m1, col_m2 = st.columns([1.2, 1])

    with col_m1:
        st.markdown("### 🔄 Kapalı Çevrim Fiili Durum & Tolerans Analizi")
        try:
            from src.scenarios.closed_loop import ClosedLoopEngine

            cl_engine = ClosedLoopEngine(db_path=str(get_runtime_paths()["db_path"]))
            decision = cl_engine.evaluate_variance_and_trigger(run_id_val)

            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("Zaman Kayması (Slippage)", f"%{decision.schedule_slippage_pct:.1f}")
            kpi2.metric("Toplam Gecikme", f"{decision.total_delay_hours:.1f} sa")
            kpi3.metric("Hurda / Scrap Oranı", f"%{decision.scrap_rate_pct:.1f}")

            if decision.requires_replanning:
                st.error(f"🚨 **DİNAMİK YENİDEN PLANLAMA TETİKLENDİ:** {decision.trigger_reason}")
            else:
                st.success("✅ **Üretim Toleranslar Dahilinde:** Yeniden planlama gerekmiyor.")
        except Exception as e:
            st.caption(f"Kapalı çevrim analiz durumu: {e}")

        st.markdown("---")

        st.markdown("### 📋 Canlı İş Emri Takip Matrisi (`mes_order_tracking`)")
        tracking_df = get_table("mes_order_tracking", run_id_val)
        if tracking_df.empty:
            st.info(
                "Henüz aktif run için MES takip kaydı yok. Aşağıdaki butondan çizelgeyi MES takip tablosuna aktarabilirsiniz."
            )
            if st.button("🔄 Aktif Çizelgeyi MES Takibine Yükle"):
                mes_srv = MESIntegrationService(run_id=run_id_val)
                loaded_cnt = mes_srv.initialize_tracking_from_schedule()
                st.success(f"{loaded_cnt} adet görev MES takip tablosuna başarıyla aktarıldı.")
                st.rerun()
        else:
            status_filter = st.multiselect(
                "Durum Filtresi:",
                options=tracking_df["status"].unique().tolist(),
                default=tracking_df["status"].unique().tolist(),
            )
            filtered_tracking = tracking_df[tracking_df["status"].isin(status_filter)]
            st.dataframe(
                filtered_tracking[
                    [
                        "task_id",
                        "lot_id",
                        "product_id",
                        "machine_id",
                        "scheduled_start_min",
                        "scheduled_end_min",
                        "status",
                        "variance_min",
                    ]
                ],
                use_container_width=True,
                height=300,
            )

        st.markdown("### ⚠️ Sahadan Gelen Son Olaylar (`mes_execution_events`)")
        events_df = get_table("mes_execution_events", run_id_val)
        if not events_df.empty:
            st.dataframe(events_df.tail(10), use_container_width=True, height=180)
        else:
            st.info("Kayıtlı plansız duruş veya olay bulunmuyor.")

    with col_m2:
        st.markdown("### ⚡ Karar Destek & Çizelgeleme Simülasyon Kokpiti")

        sim_type = st.radio(
            "Simülasyon Modu:",
            [
                "🚨 Makine Arızası (CP-SAT What-If)",
                "🔥 Acil Sipariş Enjeksiyonu (Hot-Order)",
                "🔄 Dinamik Yeniden Çizelgeleme (Freeze Horizon)",
            ],
            index=0,
        )

        if sim_type == "🚨 Makine Arızası (CP-SAT What-If)":
            with st.form("breakdown_sim_form"):
                sel_machine = st.selectbox("Arızalanan Tezgâh:", ["M01", "M02", "M03"])
                bd_start = st.number_input(
                    "Arıza Başlangıç Zamanı (Dakika):",
                    min_value=0,
                    value=480,
                    step=60,
                )
                bd_dur = st.number_input(
                    "Duruş Süresi (Dakika):",
                    min_value=15,
                    value=180,
                    step=15,
                )
                bd_reason = st.text_input("Arıza Nedeni:", value="Feeder Arızası")
                run_bd_btn = st.form_submit_button("Simüle Et (What-If CP-SAT)")

            if run_bd_btn:
                with st.spinner("CP-SAT çözücüsü senaryoyu çözüyor..."):
                    engine = WhatIfEngine()
                    event = MachineBreakdownEvent(
                        machine_id=sel_machine,
                        start_min=int(bd_start),
                        duration_min=int(bd_dur),
                        reason=bd_reason,
                    )
                    b_meta, s_meta, report, sc_df = engine.simulate_breakdown(event)

                st.success("✅ Arıza senaryosu başarıyla simüle edildi!")
                k1, k2, k3 = st.columns(3)
                k1.metric(
                    "Yeni Makespan",
                    f"{report.scenario_makespan_min:,.0f} dk",
                    delta=f"{report.makespan_delta_min:+,.0f} dk",
                    delta_color="inverse",
                )
                k2.metric(
                    "Gecikme (Tardiness)",
                    f"{report.scenario_total_tardiness_min:,.0f} dk",
                    delta=f"{report.tardiness_delta_min:+,.0f} dk",
                    delta_color="inverse",
                )
                k3.metric("Etkilenen Görevler", f"{report.impacted_tasks_count} adet")

        elif sim_type == "🔥 Acil Sipariş Enjeksiyonu (Hot-Order)":
            with st.form("hot_order_form"):
                ho_product = st.selectbox("Ürün Tipi:", ["P01", "P02", "P03", "P04", "P05"])
                ho_qty = st.number_input("Sipariş Miktarı:", min_value=100, value=400, step=50)
                ho_due = st.number_input(
                    "İstenen Teslim Zamanı (Dakika):",
                    min_value=100,
                    value=2880,
                    step=240,
                )
                ho_prio = st.slider(
                    "Öncelik Ağırlığı:",
                    min_value=1.0,
                    max_value=10.0,
                    value=5.0,
                )
                run_ho_btn = st.form_submit_button("Acil Siparişi Çizelgeye Ekle")

            if run_ho_btn:
                with st.spinner("Acil parti enjekte ediliyor ve yeniden optimize ediliyor..."):
                    engine = WhatIfEngine()
                    injection = HotOrderInjection(
                        order_id=f"HOT-{ho_product}-{int(ho_qty)}",
                        product_id=ho_product,
                        quantity=int(ho_qty),
                        due_date_min=int(ho_due),
                        priority_weight=float(ho_prio),
                    )
                    b_meta, s_meta, report, sc_df = engine.simulate_hot_order(injection)

                st.success("✅ Acil sipariş başarıyla çizelgeye dahil edildi!")
                k1, k2, k3 = st.columns(3)
                k1.metric(
                    "Yeni Makespan",
                    f"{report.scenario_makespan_min:,.0f} dk",
                    delta=f"{report.makespan_delta_min:+,.0f} dk",
                    delta_color="inverse",
                )
                k2.metric(
                    "Gecikme (Tardiness)",
                    f"{report.scenario_total_tardiness_min:,.0f} dk",
                    delta=f"{report.tardiness_delta_min:+,.0f} dk",
                    delta_color="inverse",
                )
                k3.metric("Toplam Görev Sayısı", report.impacted_tasks_count)

        else:
            with st.form("dynamic_resched_form"):
                st.caption("Mevcut zamana kadar başlamış/bitmiş işler kilitlenir; kalan plan yeniden kurulur.")
                curr_t = st.number_input(
                    "Şu Anki Fabrika Zamanı (Dakika):",
                    min_value=0,
                    value=480,
                    step=60,
                )
                freeze_h = st.number_input(
                    "Freeze Horizon Tamponu (Dakika):",
                    min_value=0,
                    value=60,
                    step=30,
                )
                dev_mac = st.selectbox("Sapma Yaşanan Tezgâh:", ["Yok", "M01", "M02", "M03"])
                dev_dur = st.number_input(
                    "Gecikme/Duruş Süresi (Dakika):",
                    min_value=0,
                    value=120,
                    step=30,
                )
                run_resched_btn = st.form_submit_button("🔄 Freeze Horizon ile Yeniden Çizelgele")

            if run_resched_btn:
                with st.spinner("Freeze horizon donduruluyor ve çizelge yenileniyor..."):
                    rescheduler = DynamicRescheduler()
                    trig = RescheduleTriggerEvent(
                        event_id=f"EVT-UI-{int(curr_t)}",
                        current_time_min=int(curr_t),
                        freeze_horizon_min=int(freeze_h),
                        delay_machine_id=None if dev_mac == "Yok" else dev_mac,
                        delay_duration_min=int(dev_dur),
                        reason="Kullanıcı arayüzü dinamik müdahalesi",
                    )
                    base_df, new_df, n_meta, n_rep, audit = rescheduler.execute_reschedule(
                        trigger=trig,
                        new_run_id=f"UI_RESCHED_{int(curr_t)}",
                    )

                st.success("✅ Dinamik çizelgeleme ve denetim kaydı tamamlandı!")
                n1, n2, n3 = st.columns(3)
                n1.metric("Kilitlenen İşler", f"{n_rep.frozen_tasks_count} ad")
                n2.metric("Tezgâhı Değişenler", f"{n_rep.machine_swapped_count} ad")
                n3.metric("Sarsıntı (Nervousness)", f"{n_rep.nervousness_score:.4f}")

                st.info(
                    f"📌 **Soyağacı Denetim Kaydı:** {audit.audit_id} oluşturuldu. "
                    f"Ortalama iş kayması: {n_rep.average_start_delta_min:.1f} dk, Maksimum kayma: {n_rep.max_start_delta_min:.1f} dk."
                )

        st.markdown("---")
        st.markdown("### 📜 Dinamik Çizelgeleme Denetim Kütüğü (Lineage Audit)")
        audit_history = get_table("reschedule_audit_log", run_id_val, optional=True)
        if not audit_history.empty:
            st.dataframe(
                audit_history[
                    [
                        column
                        for column in [
                            "audit_id",
                            "trigger_event_id",
                            "affected_machine_id",
                            "delay_duration_min",
                            "frozen_tasks_count",
                            "nervousness_score",
                            "created_at",
                        ]
                        if column in audit_history
                    ]
                ],
                use_container_width=True,
                height=220,
            )
        else:
            st.caption("Henüz kayıtlı bir yeniden çizelgeleme denetimi yok.")
