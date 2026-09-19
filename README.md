# 🏭 Factory Decision Intelligence Platform
### Bütünleşik Hiyerarşik Üretim Planlama, Matematiksel Çizelgeleme ve Karbon Muhasebesi

[![Fabrika Karar Zekası CI](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/workflows/ci.yml)
![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)
![Optimization](https://img.shields.io/badge/OR--Tools-CP--SAT-orange.svg)
![LP](https://img.shields.io/badge/PuLP-Linear%20Programming-green.svg)
![ML](https://img.shields.io/badge/LightGBM-Forecasting-yellow.svg)

Endüstriyel bir disk üretim tesisinin operasyonel kararlarını optimize eden, tekil gerçeklik kaynağına (SSOT) bağlı karar zekâsı platformu. Sistem; talep tahmini, Hax & Meal hiyerarşik agrega planlama, Google OR-Tools CP-SAT ile sıra bağımlı tezgâh çizelgeleme, zaman fazlı MRP-I, 15 dakikalık yük analitiği ve GHG Kapsam 1-2 karbon fiyatlandırma simülasyonunu tek bir boru hattında birleştirir.

---

## 📊 Güncel Model Metrikleri ve Doğrulama (CI/CD Çıktıları)

| Modül / Metrik | Yöntem / Araç | Değer | Operasyonel Açıklama |
|---|---|---|---|
| **Çizelgeleme Statüsü** | Google OR-Tools CP-SAT | **FEASIBLE** | 20 sn zaman kısıtında uygulanabilir tamsayılı çizelge bulundu. |
| **Makespan ($C_{\max}$)** | CP-SAT vs. FCFS Taban Çizgisi | **8,599 dk (143.32 sa)** | Sezgisel taban çizgiye (9,718 dk) kıyasla **%11.5 tasarruf/iyileştirme**. |
| **Optimality Gap** | CP-SAT Dual Bound | **%36.11** (Bound: 5,494 dk) | Kesin optimum yerine hızlı uygulanabilir saha çizelgesi üretildi. |
| **Kritik Makine (M01)** | Kapasite Analitiği | **139.0 sa İş Yükü** | Standart 96 sa kapasiteyi **43.0 sa** aşarak fazla mesai ihtiyacını işaret etti. |
| **Talep Tahmini** | Recursive LightGBM / Holt-Winters | **WAPE: %6.12 – %10.41** | 28 günlük tarihsel simülasyon (holdout) testinde en düşük hata. |
| **Enerji & Pik Yük** | 15 Dk Yük Profili Modeli | **21,282.5 kWh / 248.22 kW** | Ortalama yük 148.5 kW, yük faktörü 0.598 olarak gerçekleşti. |
| **Karbon Muhasebesi** | GHG Protocol Kapsam 1 & 2 | **9.592 tCO₂e** | Birim emisyon yoğunluğu: 1.139 kgCO₂e / adet. |

---

## 🏛️ Karar Hiyerarşisi ve Sistem Mimarisi

Sistem, Hax & Meal hiyerarşik planlama mimarisini modern veri mühendisliği ve yöneylem araştırması yaklaşımlarıyla ölçekler:
'''text

[ Ham Sipariş Verisi / ERP ]
                               │
                               ▼
      ┌──────────────────────────────────────────────────┐
      │  1. TALEP TAHMİNLEME (LightGBM vs Holt-Winters)   │
      │     - 28 Günlük Tarihsel Ufuk (Holdout Simülasyon)│
      │     - WAPE Bazlı Model Seçimi ve Rekürsif Çıkarım│
      └────────────────────────┬─────────────────────────┘
                               │ Günlük SKU Talebi
                               ▼
      ┌──────────────────────────────────────────────────┐
      │  2. TAKTİK PLANLAMA (PuLP - Lineer Programlama)  │
      │     - 4 Haftalık Ufuk, Çok Makineli Kapasite LP  │
      │     - Dinamik Makine Gölge Fiyatı (Dual Analysis)│
      └────────────────────────┬─────────────────────────┘
                               │ 1. Hafta Aile Üretim Hedefleri
                               ▼
      ┌──────────────────────────────────────────────────┐
      │  3. AYRIŞTIRMA (Largest Remainder) & MRP-I       │
      │     - Tam Sayı SKU Ayrıştırma (Parti: 25 Adet)   │
      │     - Dinamik Emniyet Stoku & Net İhtiyaç Hesabı │
      └────────────────────────┬─────────────────────────┘
                               │ Net Üretim Hedefleri
                               ▼
      ┌──────────────────────────────────────────────────┐
      │  4. DETAYLI ÇİZELGELEME (Google OR-Tools CP-SAT) │
      │     - Sıra Bağımlı Hazırlık Matrisi (Setup)      │
      │     - Rota Öncelikleri & Tezgâh Çakışma Önleme   │
      └────────────────────────┬─────────────────────────┘
                               │ Dakika Bazlı Zaman Çizelgesi
                               ▼
      ┌──────────────────────────────────────────────────┐
      │  5. ENERJİ & GHG KAPSAM 1-2 KARBON ANALİTİĞİ     │
      │     - 15 Dakikalık Yük Profili & Pik Güç Takibi  │
      │     - Dahili Karbon Fiyatlama Senaryoları (€/ton)│
      └──────────────────────────────────────────────────┘
'''
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

* **Dinamik Gölge Fiyatlar (Dual Values):** M01 tezgahının kapasite kısıtının marjinal gevşeme değeri Hafta 1 için **-9,021.92 $/saat**, Hafta 2 için **-9,080.36 $/saat** seviyesindedir. Bu değer doğrudan mesai maliyeti değil; darboğaz olan M01 tezgahının kapasitesinin 1 birim artırılmasının toplam sistem maliyetindeki potansiyel marjinal düşüşünü ifade eder.

---

### 2. Detaylı Çizelgeleme (Google OR-Tools CP-SAT)

Operasyonel düzeyde, 1. hafta SKU üretim partilerinin tezgâhlar üzerindeki operasyonları sıra bağımlı hazırlık süreleriyle modellenir.

#### Amaç Fonksiyonu:
$$\min C_{\max}$$

#### Kısıtlar:
1. **Tezgâh Ayrıklığı (Disjunctive / No-Overlap):**
   $$\text{IntervalVar}(o_{i,m}) \cap \text{IntervalVar}(o_{j,m}) = \emptyset \quad \forall i \neq j, \forall m$$
2. **Sıra Bağımlı Hazırlık Süresi (Sequence-Dependent Setup):**
   $$\text{Start}(o_{j,m}) \ge \text{End}(o_{i,m}) + S_{i,j,m}$$
3. **Rota Öncelik Kısıtı (Precedence):**
   $$\text{Start}(o_{b, m+1}) \ge \text{End}(o_{b, m}) \quad \forall b \in B$$

* **Çizelgeleme Bulgusu:** Model, M01 (CNC Kesme/İşleme) tezgâhını birincil darboğaz olarak belirlemiş; FCFS taban çizgisi sezgisel sıralamasına (9,718 dk / 161.97 sa) kıyasla toplam akış süresinde **%11.5 zaman tasarrufu** sağlayarak iş akışını **8,599 dakikada (143.32 sa)** tamamlamıştır (20 saniyelik çözücü süresiyle FEASIBLE statüsü, %36.11 optimality gap).
* **Kapasite Değerlendirmesi:** M01 tezgâhı standart 96 saatlik 2 vardiya kapasitesini 43.0 saat aşarak haftalık net fazla mesai / ek vardiya gereksinimini açıkça ortaya koymuştur.

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

* **Tedarik Eylem Mesajları:** Temin süresi geriye ötelendiğinde cari periyodun gerisine düşen ($t - L \le 0$) siparişler otomatik olarak **`EXPEDITE (Past Due)`** mesajı üretir (Örn. RAW_ALLOY_ROD 1. ve 2. hafta siparişleri). Gelecek dönemler ise **`RELEASE ORDER`** olarak planlanır.

---

## ⚡ Enerji Analitiği ve GHG Karbon Muhasebesi

### 15-Dakikalık Tesis Yük Profili
$$P_{\text{tesis}}(t) = \sum_{m \in M} \left( P_{m}^{\text{proc}}(t) + P_{m}^{\text{setup}}(t) + P_{m}^{\text{idle}}(t) \right)$$

* **Tepe Yük (Peak Load):** $248.22\text{ kW}$
* **Ortalama Yük (Avg Load):** $148.5\text{ kW}$
* **Yük Faktörü (Load Factor):** $0.598$
* **Toplam Enerji Tüketimi:** $21,282.5\text{ kWh}$ (%99.3 İşleme, %0.1 Setup, %0.7 Bekleme)
* **Birim Tüketim:** $2.526\text{ kWh / bitmiş ürün}$

### Sera Gazı Emisyonları (GHG Protocol Scope 1 & 2)
1. **Kapsam 1 (Doğrudan):** Forklift dizel tüketimi (85 L $\times$ 2.68 kg CO₂e/L = 0.228 tCO₂e)
2. **Kapsam 2 (Dolaylı):** Şebeke elektrik tüketimi ($0.440\text{ kg CO}_2\text{e/kWh}$ şebeke emisyon faktörüyle 9.364 tCO₂e)
3. **Toplam Karbon Ayak İzi:** **9.592 tCO₂e** (Birim yoğunluk: 1.139 kgCO₂e / adet)

#### Dahili Karbon Fiyatlama (Internal Carbon Pricing) Senaryoları
| Karbon Fiyatı (€/tCO₂e) | Toplam Karbon Maruziyeti (€) | Birim Ürün Başı Ek Karbon Maliyeti (€/adet) |
|:---:|:---:|:---:|
| **0** | 0.00 | 0.0000 |
| **50** | 479.61 | 0.0569 |
| **80** | 767.37 | 0.0911 |
| **100** | 959.21 | 0.1139 |
| **120** | 1,151.05 | 0.1366 |

---

## 📂 Proje Dizin Yapısı

```text
├── data/
│   ├── raw/                 # Ham sipariş verisi (train.csv)
│   ├── processed/           # Boru hattı çıktı CSV dosyaları
│   └── factory.db           # SQLite tekil gerçeklik kaynağı (SSOT)
├── src/
│   ├── config.py            # Parametreler, yollar ve varsayılan sabitler
│   ├── data/
│   │   ├── preprocessing.py # Ham talep konsolidasyonu
│   │   └── build_database_and_eda.py # SQLite master-data yükleme ve EDA
│   ├── forecasting/
│   │   └── train_forecast.py # Recursive LightGBM & Holt-Winters motoru
│   ├── planning/
│   │   └── aggregate_planning.py # Hax & Meal Seviye 1 LP ve Seviye 2 Ayrıştırma
│   ├── inventory/
│   │   └── bom_mrp.py       # Zaman fazlı MRP-I motoru
│   ├── scheduling/
│   │   └── schedule_cpsat.py# OR-Tools CP-SAT detaylı çizelgeleme
│   ├── energy/
│   │   └── energy_analytics.py # 15 dk yük profili ve tepe yük analitiği
│   └── carbon/
│       └── carbon_analytics.py # GHG Kapsam 1-2 ve dahili karbon simülasyonu
├── tests/
│   └── test_integration.py  # pytest matematiksel & operasyonel OR test paketi
├── main.py                  # Uçtan uca boru hattı orkestrasyonu
├── requirements.txt         # Kütüphane bağımlılıkları
└── README.md

# Depoyu klonlayın
git clone [https://github.com/AliUmutKazak/factory-decision-intelligence.git](https://github.com/AliUmutKazak/factory-decision-intelligence.git)
cd factory-decision-intelligence

# Sanal ortamı oluşturun ve aktif edin
python -m venv factory-env
factory-env\Scripts\activate      # Windows
# source factory-env/bin/activate # Linux/macOS

# Bağımlılıkları yükleyin
pip install -r requirements.txt

python main.py

pytest -v