import sqlite3
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_PATH = "data/factory.db"

st.set_page_config(
    page_title="Factory Decision Intelligence Platform",
    page_icon="🏭",
    layout="wide"
)

@st.cache_data
def get_table(table_name):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
    conn.close()
    return df

st.title("🏭 Factory Decision Intelligence Platform")
st.caption("Talep Tahmini • Hiyerarşik Planlama • MRP • CP-SAT Çizelgeleme • Enerji & Karbon")

tab_summary, tab_forecast, tab_plan, tab_schedule, tab_sustainability = st.tabs([
    "📊 Yönetici Özeti",
    "📈 Talep Tahmini & Doğrulama",
    "📋 Taktik Planlama & MRP",
    "⏱️ Detaylı Çizelge (Gantt)",
    "🌱 Enerji & Karbon Analitiği"
])

# -------------------------------------------------------------
# TAB 1: YÖNETİCİ ÖZETİ
# -------------------------------------------------------------
with tab_summary:
    st.subheader("Bütünleşik Karar Akışı Göstergeleri")
    
    e_kpi = get_table("energy_kpis").iloc[0]
    c_kpi = get_table("carbon_kpis").iloc[0]
    mrp_df = get_table("mrp_plan")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("1. Hafta Üretim Hedefi", f"{int(e_kpi['total_units_produced']):,} Adet")
    col2.metric("Toplam Çizelge Süresi", f"{e_kpi['makespan_hours']} Saat")
    col3.metric("Toplam Enerji Tüketimi", f"{e_kpi['grand_total_kwh']:,.1f} kWh")
    col4.metric("Toplam Karbon Ayak İzi", f"{c_kpi['total_tco2e']:.3f} tCO₂e")
    
    st.markdown("---")
    st.subheader("Temel Fabrika Soruları & Model Yanıtları")
    
    q_col1, q_col2 = st.columns(2)
    with q_col1:
        st.info(f"**Talep:** 4 haftalık dönemde 5 SKU için toplam **37,631 adet** brüt talep öngörüldü.")
        st.info(f"**Üretim:** Saf LP modeli 1. hafta için net **{int(e_kpi['total_units_produced']):,} adet** üretim hedefi koydu.")
        st.info(f"**Malzeme:** MRP, acil tedarik gerektiren alaşımlı mil dahil **4 hammadde** için net siparişleri çıkardı.")
    with q_col2:
        st.info(f"**Çizelgeleme:** CP-SAT, M01 darboğazında sezgisel yaklaşıma karşı **%3.6 zaman tasarrufu** sağladı.")
        st.info(f"**Enerji:** Birim ürün başına **{e_kpi['kwh_per_unit']} kWh** tüketim ve **{e_kpi['peak_load_kw']} kW** tepe yük gerçekleşti.")
        st.info(f"**Karbon:** Ürün başına **{c_kpi['kgco2e_per_unit']} kgCO₂e** emisyon oluştu (%97.6 Kapsam 2).")

# -------------------------------------------------------------
# TAB 2: TALEP TAHMİNİ
# -------------------------------------------------------------
with tab_forecast:
    st.subheader("28 Günlük Tahminler ve Model Doğrulama")
    forecast_df = get_table("forecast_demand")
    
    col_f1, col_f2 = st.columns([1, 2])
    with col_f1:
        st.markdown("**Seçilen En İyi Modeller:**")
        model_counts = forecast_df.groupby(["product_id", "model_used"]).size().reset_index(name="gun_sayisi")
        st.dataframe(model_counts[["product_id", "model_used"]], use_container_width=True)
        st.caption("P02'de Holt-Winters, diğer tüm SKU'larda öznitelik türetimli LightGBM en düşük WAPE değerini vermiştir.")
    
    with col_f2:
        fig_fc = px.line(
            forecast_df, x="forecast_date", y="forecast_demand", color="product_id",
            markers=True, title="Ürün Bazlı Günlük Fabrika Çekme Talebi Tahmini"
        )
        st.plotly_chart(fig_fc, use_container_width=True)

# -------------------------------------------------------------
# TAB 3: TAKTİK PLANLAMA & MRP
# -------------------------------------------------------------
with tab_plan:
    st.subheader("Hax & Meal Aile LP Planı ve Malzeme İhtiyaçları")
    agg_df = get_table("aggregate_plan")
    sku_df = get_table("sku_production_plan")
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("**Haftalık Aile Taktik Planı (Koliler - Batches):**")
        st.dataframe(agg_df, use_container_width=True)
    with col_p2:
        st.markdown("**1. Hafta SKU Ayrıştırma (Disaggregation):**")
        st.dataframe(sku_df[sku_df["period_week"] == 1][["product_id", "planned_batches", "planned_units"]], use_container_width=True)
        
    st.markdown("---")
    st.subheader("Zaman Fazlı Malzeme İhtiyaç Planlaması (MRP-I)")
    st.dataframe(mrp_df, use_container_width=True)

# -------------------------------------------------------------
# TAB 4: ÇİZELGELEME GANTT
# -------------------------------------------------------------
with tab_schedule:
    st.subheader("OR-Tools CP-SAT Üretim Çizelgesi & Operasyon Akışı")
    sched_df = get_table("production_schedule")
    
    # Dakikaları görselleştirme için tarih formatına dönüştür
    base_time = pd.Timestamp("2026-01-05 08:00:00")
    sched_df["start_dt"] = sched_df["start_min"].apply(lambda m: base_time + pd.Timedelta(minutes=m))
    sched_df["end_dt"] = sched_df["end_min"].apply(lambda m: base_time + pd.Timedelta(minutes=m))
    
    fig_gantt = px.timeline(
        sched_df, x_start="start_dt", x_end="end_dt", y="machine_id",
        color="product_id", hover_name="batch_id",
        title="Tezgah Bazlı Operasyon Çizelgesi (Sıra Bağımlı Setup Entegreli)"
    )
    fig_gantt.update_yaxes(autorange="reversed")
    st.plotly_chart(fig_gantt, use_container_width=True)
    
    st.dataframe(sched_df[["batch_id", "machine_id", "start_min", "end_min", "duration_min", "batch_qty"]], use_container_width=True)

# -------------------------------------------------------------
# TAB 5: ENERJİ & KARBON
# -------------------------------------------------------------
with tab_sustainability:
    st.subheader("15 Dakikalık Yük Profili & Karbon Senaryoları")
    prof_df = get_table("energy_profile_15min")
    scen_df = get_table("carbon_price_scenarios")
    
    col_s1, col_s2 = st.columns([2, 1])
    with col_s1:
        fig_load = px.line(
            prof_df, x="time_hour", y="total_load_kw",
            title="Tesis Güç Çekiş Profili (15-dk Çözünürlük)",
            labels={"time_hour": "Zaman (Saat)", "total_load_kw": "Toplam Güç (kW)"}
        )
        fig_load.add_hline(y=15.7, line_dash="dash", line_color="red", annotation_text="Peak Power (15.7 kW)")
        st.plotly_chart(fig_load, use_container_width=True)
        
    with col_s2:
        st.markdown("**Dahili Karbon Fiyatlandırma Simülatörü:**")
        user_c_price = st.slider("EU ETS Karbon Fiyatı (€/tCO₂e):", min_value=0, max_value=200, value=80, step=10)
        sim_exposure = c_kpi["total_tco2e"] * user_c_price
        st.metric("Hesaplanan Karbon Maruziyeti", f"€{sim_exposure:,.2f}")
        st.metric("Birim Ürün Karbon Maliyeti", f"€{sim_exposure / e_kpi['total_units_produced']:.4f} / adet")
        
        st.markdown("---")
        st.dataframe(scen_df, use_container_width=True)