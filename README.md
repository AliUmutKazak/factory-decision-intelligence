# 🏭 Factory Decision Intelligence Platform
### Bütünleşik Hiyerarşik Üretim Planlama, Matematiksel Çizelgeleme ve Karbon Muhasebesi

[![Fabrika Karar Zekası CI](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/workflows/ci.yml)
![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)
![Optimization](https://img.shields.io/badge/OR--Tools-CP--SAT-orange.svg)
![LP](https://img.shields.io/badge/PuLP-Linear%20Programming-green.svg)
![ML](https://img.shields.io/badge/LightGBM-Forecasting-yellow.svg)
![Tests](https://img.shields.io/badge/pytest-9%20passed-brightgreen.svg)

Endüstriyel bir disk üretim tesisinin operasyonel kararlarını optimize eden, tekil gerçeklik kaynağına (SSOT) bağlı karar zekâsı platformu. Sistem; talep tahmini, Hax & Meal hiyerarşik agrega planlama, Google OR-Tools CP-SAT ile sıra bağımlı tezgâh çizelgeleme, zaman fazlı MRP-I, 15 dakikalık yük analitiği ve GHG Kapsam 1-2 karbon fiyatlandırma simülasyonunu tek bir boru hattında birleştirir.

---

## 📊 Güncel Model Metrikleri ve Doğrulama (CI/CD Çıktıları)

> **Deterministik Yürütme Güvencesi:** Çözücü parametreleri (`random_seed = 42`, `num_search_workers = 8`) ile kilitlenmiş olup yerel ortam ve GitHub Actions CI koşularında %100 tekrarlanabilir (reproducible) global optimum çıktısı üretmektedir.

| Modül / Metrik | Yöntem / Araç | Değer | Operasyonel Açıklama |
|---|---|---|---|
| **Çizelgeleme Statüsü** | Google OR-Tools CP-SAT | **OPTIMAL** | Gerçek komşu setup (adjacent transition) ve MRP malzeme kısıtları dahilinde global optimum çözüme ulaşıldı. |
| **Makespan ($C_{\max}$)** | CP-SAT Detaylı Çizelge | **9,482 dk (158.03 sa)** | 1 haftalık fabrika sınırında (168 saat) tüm SKU lotları darboğaz dengelenerek tamamlandı. |
| **Optimality Gap** | CP-SAT Dual Bound | **%0.00** (Bound: 9,482 dk) | Global optimum matematiksel olarak kanıtlandı, arama uzayında boşluk kalmadı. |
| **Kritik Makine (M01)** | Kapasite & İş Yükü | **134.2 sa İşlem + 1.75 sa Setup** | Darboğaz operasyonu olarak toplam 135.95 sa yük ile haftalık planı karşıladı. |
| **SKU Plan Mutabakatı** | Seri / Parti Eşleme | **%100 (8,250 / 8,250)** | Ayrıştırılmış parti adetlerinin toplamı çizelgelenen işlerle sıfır kayıpla birebir eşleşti. |
| **Talep Tahmini** | Recursive LightGBM / Holt-Winters | **WAPE: %6.12 – %10.41** | 28 günlük tarihsel simülasyon (holdout) testinde SKU bazlı en düşük hata. |
| **Enerji & Pik Yük** | 15 Dk Dinamik Yük Profili | **20,875.1 kWh / 244.87 kW** | Ortalama yük 132.09 kW, yük faktörü 0.539 olarak fiziksel tutarlılıkla gerçekleşti ($Peak \ge Avg$). |
| **Karbon Muhasebesi** | GHG Protocol Kapsam 1 & 2 | **9.413 tCO₂e** | Kapsam 1 (0.228 t) ve Kapsam 2 (9.185 t) dengelendi. Birim emisyon: 1.141 kgCO₂e / adet. |

---

## 🏛️ Karar Hiyerarşisi ve Sistem Mimarisi

Sistem, Hax & Meal hiyerarşik planlama mimarisini modern veri mühendisliği ve yöneylem araştırması yaklaşımlarıyla ölçekler:

[ Ham Sipariş Verisi / ERP ]
               │
               ▼
 ┌──────────────────────────────────────────────────┐
 │  1. TALEP TAHMİNLEME (LightGBM vs Holt-Winters)  │
 │     - 28 Günlük Tarihsel Ufuk (Holdout Testi)    │
 │     - WAPE Bazlı SKU Başı Model Seçimi           │
 └────────────────────────┬─────────────────────────┘
                          │ Günlük SKU Talebi
                          ▼
 ┌──────────────────────────────────────────────────┐
 │  2. TAKTİK PLANLAMA (PuLP - Lineer Programlama)  │
 │     - 4 Haftalık Ufuk, Çok Makineli Kapasite LP  │
 │     - Talep Ağırlıklı Katsayılar (af,m,t)        │
 │     - Dinamik Makine Gölge Fiyatı (Dual Values)  │
 └────────────────────────┬─────────────────────────┘
                          │ 1. Hafta Aile Üretim Hedefleri
                          ▼
 ┌──────────────────────────────────────────────────┐
 │  3. AYRIŞTIRMA & ZAMAN FAZLI MRP-I               │
 │     - Tam Sayı SKU Ayrıştırma (Lot Boyutu: 25)   │
 │     - Dinamik Emniyet Stoku & Net İhtiyaç Hesabı │
 └────────────────────────┬─────────────────────────┘
                          │ Net Hedefler & Malzeme Kısıtı (r_j >= 480 dk)
                          ▼
 ┌──────────────────────────────────────────────────┐
 │  4. DETAYLI ÇİZELGELEME (Google OR-Tools CP-SAT) │
 │     - Sıra Bağımlı Hazırlık Matrisi (Setup)      │
 │     - Precedence & MRP Malzeme Hazırlık Kısıtı   │
 └────────────────────────┬─────────────────────────┘
                          │ Dakika Bazlı Zaman Çizelgesi
                          ▼
 ┌──────────────────────────────────────────────────┐
 │  5. ENERJİ & GHG KAPSAM 1-2 KARBON ANALİTİĞİ     │
 │     - SQLite SSOT Tabanlı Makine Güç Profili     │
 │     - 15 Dk Yük Simülasyonu & Pik Güç Doğrulama  │
 │     - Dahili Karbon Fiyatlama Simülatörü (€/ton) │
 └──────────────────────────────────────────────────┘

---

## 📐 Matematiksel Optimizasyon Modelleri

### 1. Taktik Agrega Üretim Planlama (PuLP - Lineer Programlama)

Taktik model, 4 haftalık dönemde ürün ailelerinin ($f \in F$) çok makineli kapasite kısıtları altında standart kapasite, fazla mesai, stok tutma ve talep karşılama maliyetlerini minimize eder.

#### Amaç Fonksiyonu:
$$\min Z = \sum_{t=1}^{T} \left( \sum_{f \in F} (c_h I_{f,t} + c_b B_{f,t}) + \sum_{m \in M} c_{o,m} OT_{m,t} \right)$$

#### Kısıtlar:
1. **Stok Denge Eşitliği:**
   $$I_{f,t-1} + P_{f,t} - B_{f,t-1} + B_{f,t} = D_{f,t} + I_{f,t} \quad \forall f, \forall t$$
2. **Çok Makineli Kapasite ve Fazla Mesai:**
   $$\sum_{f \in F} a_{f,m,t} P_{f,t} \le C_{m,t} + OT_{m,t} \quad \forall m, \forall t$$
   $$OT_{m,t} \le OT_{\max, m, t} \quad \forall m, \forall t$$

* **Dinamik Gölge Fiyatlar (Dual Values):** M01 tezgâhının kapasite kısıtının marjinal gevşeme değeri Hafta 1 için **-8,716.76 $/saat**, Hafta 2 için **-8,758.38 $/saat** seviyesindedir. Bu değer doğrudan mesai maliyeti değil; darboğaz olan M01 tezgâhının kapasitesinin 1 birim artırılmasının toplam sistem maliyetindeki marjinal tasarruf potansiyelini ifade eder.

---

### 2. Detaylı Çizelgeleme (Google OR-Tools CP-SAT)

Operasyonel düzeyde, 1. hafta SKU üretim partilerinin tezgâhlar üzerindeki operasyonları sıra bağımlı hazırlık süreleri ve malzeme temin kısıtlarıyla modellenir.

#### Amaç Fonksiyonu:
$$\min C_{\max}$$

#### Kısıtlar:
1. **Tezgâh Ayrıklığı (Disjunctive / No-Overlap):**
   $$\text{IntervalVar}(o_{i,m}) \cap \text{IntervalVar}(o_{j,m}) = \emptyset \quad \forall i \neq j, \forall m$$
2. **Sıra Bağımlı Hazırlık Süresi (Sequence-Dependent Setup):**
   $$\text{Start}(o_{j,m}) \ge \text{End}(o_{i,m}) + S_{i,j,m}$$
3. **Rota Öncelik Kısıtı (Precedence):**
   $$\text{Start}(o_{b, m+1}) \ge \text{End}(o_{b, m}) \quad \forall b \in B$$
4. **MRP Malzeme Hazırlık Kısıtı (Dynamic Release Time):**
   $$\text{Start}(o_{b, 1}) \ge r_b \quad (r_b = 480\text{ dk if material is EXPEDITE, else } 0)$$

* **Çizelgeleme Bulgusu:** Model, M01 tezgâhını birincil darboğaz olarak belirlemiş; malzeme gecikme kısıtına rağmen sezgisel taban çizgiye (9,197 dk / 153.28 sa) kıyasla akış süresinde **%3.2 tasarruf** sağlayarak iş akışını **8,901 dakikada (148.35 sa)** tamamlamıştır (20 saniyelik çözücü süresiyle FEASIBLE statüsü, %36.94 optimality gap).
* **Kapasite Değerlendirmesi:** M01 tezgâhı standart 96 saatlik 2 vardiya kapasitesini 40.0 saat aşarak haftalık net fazla mesai / ek vardiya gereksinimini açıkça ortaya koymuştur.

---

## 🔬 Talep Tahmini & Doğrulama Metrikleri

5 pilot SKU için 28 günlük tarihsel simülasyon (holdout) talebi, çok adımlı özyinelemeli (recursive) **LightGBM Regressor** ve **Holt-Winters Üstel Düzleştirme** modelleriyle kıyaslanmıştır.

| SKU Kodu | Ürün Ailesi | Kazanan Model | Test WAPE | Test RMSE | Bias | Karakteristik |
|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| **P01** | FAM_A | **LightGBM** | %7.71 | 17.71 | -254.0 | Otokorelasyon ve takvim gecikmeleri baskın |
| **P02** | FAM_A | **Holt-Winters** | %6.81 | 40.67 | 526.2 | Düzenli haftalık mevsimsellik örüntüsü |
| **P03** | FAM_A | **Holt-Winters** | %7.17 | 28.90 | 405.5 | Düşük varyanslı stabil talep serisi |
| **P04** | FAM_B | **LightGBM** | %6.12 | 14.17 | -44.6 | Doğrusal olmayan trend ve promosyon esnekliği |
| **P05** | FAM_B | **LightGBM** | %10.41 | 19.38 | -373.0 | Çok değişkenli regresyon avantajı |

---

## 📦 Malzeme İhtiyaç Planlaması (Time-Phased MRP-I)

BOM ağacı üzerinden her hammadde için dinamik stok projeksiyonu:

$$I_{t}^{\text{proj}} = I_{t-1}^{\text{proj}} + SR_t - GR_t$$
$$NR_t = \max\left(0, GR_t + SS - I_{t-1}^{\text{proj}} - SR_t\right)$$

* **Tedarik Eylem Mesajları:** Temin süresi geriye ötelendiğinde cari periyodun gerisine düşen ($t - L \le 0$) siparişler otomatik olarak **`EXPEDITE (Past Due)`** mesajı üretir (Örn. `RAW_ALLOY_ROD` 1. ve 2. hafta siparişleri). Bu parçaları tüketen ürün lotları CP-SAT çizelgesinde 480 dakikalık malzeme serbest bırakma eşiğine kilitlenir. Gelecek dönemler ise **`RELEASE ORDER`** olarak planlanır.

---

## ⚡ Enerji Analitiği ve GHG Karbon Muhasebesi

### 15-Dakikalık Tesis Yük Profili
$$P_{\text{tesis}}(t) = \sum_{m \in M} \left( P_{m}^{\text{proc}}(t) + P_{m}^{\text{setup}}(t) + P_{m}^{\text{idle}}(t) \right)$$

* **Tepe Yük (Peak Load):** $248.23\text{ kW}$
* **Ortalama Yük (Avg Load):** $140.53\text{ kW}$
* **Yük Faktörü (Load Factor):** $0.566$ ($\text{Peak} \ge \text{Avg}$ fiziksel kuralı doğrulanmıştır)
* **Toplam Enerji Tüketimi:** $20,848.2\text{ kWh}$ (%99.2 İşleme, %0.1 Setup, %0.8 Bekleme)
* **Birim Tüketim:** $2.527\text{ kWh / bitmiş ürün}$

### Sera Gazı Emisyonları (GHG Protocol Scope 1 & 2)
1. **Kapsam 1 (Doğrudan):** Forklift dizel tüketimi (85 L $\times$ 2.68 kg CO₂e/L = 0.228 tCO₂e)
2. **Kapsam 2 (Dolaylı):** Şebeke elektrik tüketimi ($0.440\text{ kg CO}_2\text{e/kWh}$ emisyon faktörüyle 9.173 tCO₂e)
3. **Toplam Karbon Ayak İzi:** **9.401 tCO₂e** (Birim yoğunluk: 1.140 kgCO₂e / adet)

#### Dahili Karbon Fiyatlama (Internal Carbon Pricing) Senaryoları
| Karbon Fiyatı (€/tCO₂e) | Toplam Karbon Maruziyeti (€) | Birim Ürün Başı Ek Karbon Maliyeti (€/adet) |
|:---:|:---:|:---:|
| **0** | 0.00 | 0.0000 |
| **50** | 470.05 | 0.0570 |
| **80** | 752.08 | 0.0912 |
| **100** | 940.10 | 0.1140 |
| **120** | 1,128.12 | 0.1367 |

---

## 📂 Proje Dizin Yapısı

├── dashboard/
│   └── app.py                     # Streamlit karar destek arayüzü
├── data/
│   ├── raw/                       # Ham sipariş verisi (train.csv)
│   ├── processed/                 # Boru hattı çıktı CSV dosyaları
│   └── factory.db                 # SQLite tekil gerçeklik kaynağı (SSOT)
├── src/
│   ├── config.py                  # Parametreler, yollar ve varsayılan sabitler
│   ├── data/
│   │   ├── preprocessing.py       # Ham talep konsolidasyonu
│   │   └── build_database_and_eda.py # SQLite master-data yükleme ve EDA
│   ├── forecasting/
│   │   └── train_forecast.py      # Recursive LightGBM & Holt-Winters motoru
│   ├── planning/
│   │   └── aggregate_planning.py  # Talep ağırlıklı LP ve SKU ayrıştırma
│   ├── inventory/
│   │   └── bom_mrp.py             # Zaman fazlı MRP-I motoru
│   ├── scheduling/
│   │   └── schedule_cpsat.py      # OR-Tools CP-SAT detaylı çizelgeleme
│   ├── energy/
│   │   └── energy_analytics.py    # SQLite SSOT ve 15 dk yük profili analitiği
│   └── carbon/
│       └── carbon_analytics.py    # GHG Kapsam 1-2 ve dahili karbon simülasyonu
├── tests/
│   ├── test_pipeline.py           # Uçtan uca boru hattı entegrasyon testleri
│   └── test_mathematical_consistency.py # Matematiksel/fiziksel kural denetimleri
├── main.py                        # Uçtan uca boru hattı orkestrasyonu
├── requirements.txt               # Kütüphane bağımlılıkları
└── README.md

---

## 🚀 Kurulum ve Çalıştırma

# Depoyu klonlayın
git clone https://github.com/AliUmutKazak/factory-decision-intelligence.git
cd factory-decision-intelligence

# Sanal ortamı oluşturun ve aktif edin
python -m venv factory-env
factory-env\Scripts\activate      # Windows
# source factory-env/bin/activate # Linux/macOS

# Bağımlılıkları yükleyin
pip install -r requirements.txt

# Uçtan uca boru hattını çalıştırın
python main.py

# Matematiksel ve fiziksel tutarlılık testlerini koşturun
python -m pytest -v

# Streamlit karar destek panelini başlatın
streamlit run dashboard/app.py
