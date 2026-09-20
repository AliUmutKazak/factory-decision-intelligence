import sys
from pathlib import Path

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

st.set_page_config(
    page_title="Factory Decision Intelligence Platform",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="collapsed"
)

@st.cache_data(ttl=60)
def get_table(table_name: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql(f"SELECT * FROM {table_name}", conn)

# Başlık ve Üst Bilgi
st.title("🏭 Factory Decision Intelligence Platform")
st.caption("Talep Tahmini • Hiyerarşik Taktik Planlama • Zaman Fazlı MRP • CP-SAT Çizelgeleme • Enerji & Karbon")

tab_summary, tab_forecast, tab_plan, tab_schedule, tab_sustainability = st.tabs([
    "📊 Yönetici Özeti",
    "📈 Talep Tahmini & Doğrulama",
    "📋 Taktik Planlama & MRP",
    "⏱️ Detaylı Çizelge (Gantt)",
    "🌱 Enerji & Karbon Analitiği"
])

# Veri Setlerini Yükle
e_kpi = get_table("energy_kpis").iloc[0]
c_kpi = get_table("carbon_kpis").iloc[0]
mrp_df = get_table("mrp_plan")
forecast_df = get_table("forecast_demand")
sku_df = get_table("sku_production_plan")
sched_df = get_table("production_schedule")
agg_df = get_table("aggregate_plan")
mach_cap_df = get_table("machine_capacity_plan")

# =============================================================
# TAB 1: YÖNETİCİ ÖZETİ
# =============================================================
with tab_summary:
    st.subheader("Bütünleşik Karar Akışı Göstergeleri")

    total_gross_demand = int(forecast_df["forecast_demand"].sum())
    w1_planned_units = int(sku_df[sku_df["period_week"] == 1]["planned_units"].sum())

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "1. Hafta Net Üretim Hedefi",
        f"{w1_planned_units:,} Adet",
        help="LP Modeli tarafından 1. hafta için optimize edilen net üretim miktarı"
    )
    overtime_hrs = max(0.0, e_kpi['makespan_hours'] - float(WEEKLY_HOURS_PER_MACHINE))
    col2.metric(
        "Çizelge Makespan",
        f"{e_kpi['makespan_hours']:.1f} Saat",
        delta=f"+{overtime_hrs:.1f} sa (Kapasite Aşımı)" if overtime_hrs > 0 else "Kapasite İçi",
        delta_color="inverse",
        help=f"CP-SAT tarafından bulunan toplam parti tamamlanma süresi (Standart kapasite: {WEEKLY_HOURS_PER_MACHINE} saat)"
    )
    col3.metric(
        "Toplam Enerji Tüketimi",
        f"{e_kpi['grand_total_kwh']:,.1f} kWh",
        delta=f"{e_kpi['kwh_per_unit']:.3f} kWh/adet",
        help="1. hafta çizelgesindeki 3 tezgâhın toplam işlem, hazırlık ve boşta bekleme enerjisi"
    )
    col4.metric(
        "Toplam Karbon Ayak İzi",
        f"{c_kpi['total_tco2e']:.3f} tCO₂e",
        delta=f"{c_kpi['kgco2e_per_unit']:.3f} kgCO₂e/adet",
        help="Kapsam 1 (Forklift dizel) ve Kapsam 2 (Şebeke elektriği) toplam emisyonu"
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
        past_due_count = len(mrp_df[mrp_df["action_message"].str.contains("EXPEDITE", na=False)])
        st.info(
            f"**Tedarik Zinciri:** Zaman fazlı MRP-I, 4 hammadde için net ihtiyaçları belirledi; "
            f"temin süresi kısıtı nedeniyle **{past_due_count} sipariş için acil tedarik (EXPEDITE)** uyarısı üretildi."
        )
    with q_col2:
        st.info(
            f"**Kısıt Bağlantısı (MRP → CP-SAT):** Tedarik riski taşıyan hammaddeye sahip lotların ilk operasyonu "
            f"480 dk serbest bırakma (release time) kısıtına bağlandı; operasyonlar malzeme tesliminden önce başlatılmadı."
        )
       # En yüksek iş yüküne sahip darboğaz tezgahı dinamik tespit et
        mach_workload = sched_df.groupby("machine_id")["duration_min"].sum()
        bottleneck_mach = mach_workload.idxmax() if not mach_workload.empty else "M01"
        b_hours = mach_workload.max() / 60.0 if not mach_workload.empty else 0.0
        overrun_hrs = max(0.0, b_hours - 96.0)

        st.info(
            f"**Kapasite & Darboğaz:** LP dual analizi ve çizelgeleme yükü doğrultusunda **{bottleneck_mach}** "
            f"tezgâhı en bağlayıcı darboğaz olarak gerçekleşti. Tezgâh iş yükü ({b_hours:.1f} sa) standart nominal "
            f"96 saati aşarak **+{overrun_hrs:.1f} saat Nominal Kapasite Aşımı (Overrun)** oluşturdu."
        )
        st.info(
            f"**Sürdürülebilirlik:** Tesis tepe yükü **{e_kpi['peak_load_kw']:.1f} kW** olarak fiziksel kuralı doğruladı; "
            f"Dahili Karbon Senaryosu (80 €/tCO₂e) kapsamında karbon maruziyeti **€{c_kpi['total_tco2e'] * 80:,.2f}** seviyesindedir."
        )

# =============================================================
# TAB 2: TALEP TAHMİNİ
# =============================================================
with tab_forecast:
    st.subheader("28 Günlük Tahminler ve Model Kıyaslama (Benchmark)")

    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        st.markdown("**SKU Bazlı Kazanan Tahmin Modelleri:**")
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
                lambda row: ['background-color: rgba(255, 75, 75, 0.2)' if row['is_bottleneck'] == 'YES' else '' for _ in row],
                axis=1
            ),
            use_container_width=True
        )
        st.caption("🔴 Kırmızı vurgulanan satırlar o hafta için bağlayıcı kısıtı (binding bottleneck) ve marjinal gevşeme değerini ($/hour) gösterir.")
    else:
        st.info("Makine kapasite plan verisi bulunamadı.")
    st.markdown("---")
    st.subheader("Zaman Fazlı Malzeme İhtiyaç Planlaması (MRP-I)")

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

    sched_df["start_hour"] = sched_df["start_min"] / 60.0
    sched_df["duration_hour"] = sched_df["duration_min"] / 60.0

    hover_col = "lot_id" if "lot_id" in sched_df.columns else "batch_id"

    fig_gantt = px.bar(
        sched_df,
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
    # 480 dakikalık (8. saat) malzeme bekleme penceresini çizgiyle göster
    fig_gantt.add_vline(
        x=8.0,
        line_dash="dot",
        line_color="orange",
        annotation_text="Synthetic Expedite Release (8. sa)",
        annotation_position="top right"
    )
    fig_gantt.update_layout(xaxis_title="Simülasyon Zamanı (Saat)", yaxis_title="Tezgâh")
    fig_gantt.update_yaxes(autorange="reversed")
    st.plotly_chart(fig_gantt, use_container_width=True)

    sched_cols = [c for c in [hover_col, "machine_id", "setup_before_min", "start_min", "end_min", "duration_min", "batch_qty", "lot_qty"] if c in sched_df.columns]
    st.dataframe(sched_df[sched_cols], use_container_width=True)

# =============================================================
# TAB 5: ENERJİ & KARBON
# =============================================================
with tab_sustainability:
    st.subheader("15 Dakikalık Tesis Yük Profili & GHG Karbon Analitiği")
    prof_df = get_table("energy_profile_15min")
    scen_df = get_table("carbon_price_scenarios")
    mach_carb_df = get_table("carbon_machine_kpis")

    col_s1, col_s2 = st.columns([2, 1])
    with col_s1:
        fig_load = px.line(
            prof_df, x="time_hour", y="total_load_kw",
            title=f"Tesis Güç Çekiş Profili (Tepe Yük: {e_kpi['peak_load_kw']:.1f} kW | Ortalama: {e_kpi['avg_load_kw']:.1f} kW)",
            labels={"time_hour": "Zaman (Saat)", "total_load_kw": "Toplam Güç (kW)"}
        )
        fig_load.add_hline(
            y=e_kpi["peak_load_kw"], line_dash="dash", line_color="red",
            annotation_text=f"Peak: {e_kpi['peak_load_kw']:.1f} kW"
        )
        fig_load.add_hline(
            y=e_kpi["avg_load_kw"], line_dash="dot", line_color="green",
            annotation_text=f"Avg: {e_kpi['avg_load_kw']:.1f} kW"
        )
        st.plotly_chart(fig_load, use_container_width=True)

        st.markdown("**Tezgâh Bazlı Kapsam 2 Emisyon Payı:**")
        fig_pie = px.pie(
            mach_carb_df, names="machine_id", values="scope_2_tco2e",
            title="Makine Bazlı Karbon Salımı Dağılımı",
            hole=0.4
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_s2:
        st.markdown("### 💶 Dahili Karbon Fiyat Simülatörü")
        user_c_price = st.slider(
            "İçsel Karbon Fiyat Senaryosu (€/tCO₂e):",
            min_value=0, max_value=200, value=80, step=10
        )
        sim_exposure = c_kpi["total_tco2e"] * user_c_price
        st.metric("Hesaplanan Toplam Karbon Maliyeti", f"€{sim_exposure:,.2f}")
        st.metric(
            "Birim Ürün Karbon Maliyeti",
            f"€{sim_exposure / e_kpi['total_units_produced']:.4f} / adet"
        )

        st.markdown("---")
        st.markdown("**İçsel Karbon Fiyatlandırma Senaryo Tablosu (Internal Carbon Pricing):**")
        st.dataframe(scen_df, use_container_width=True)
        