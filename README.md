# 🏭 Factory Decision Intelligence Platform
### Bütünleşik Hiyerarşik Üretim Planlama, Matematiksel Çizelgeleme ve Karbon Muhasebesi

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Optimization](https://img.shields.io/badge/OR--Tools-CP--SAT-orange.svg)](https://developers.google.com/optimization)
[![LP](https://img.shields.io/badge/PuLP-Linear%20Programming-green.svg)](https://coin-or.github.io/pulp/)
[![ML](https://img.shields.io/badge/LightGBM-Forecasting-yellow.svg)](https://lightgbm.readthedocs.io/)
[![UI](https://img.shields.io/badge/Streamlit-Dashboard-red.svg)](https://streamlit.io/)
[![Tests](https://img.shields.io/badge/pytest-6%20passed-brightgreen.svg)](https://docs.pytest.org/)

Endüstriyel bir disk üretim tesisinin operasyonel kararlarını optimize eden, tekil gerçeklik kaynağına (SSOT) bağlı karar zekâsı platformu. Sistem; talep tahmini, Hax & Meal hiyerarşik agrega planlama, Google OR-Tools CP-SAT ile sıra bağımlı tezgâh çizelgeleme, zaman fazlı MRP-I, 15 dakikalık yük analitiği ve GHG Kapsam 1-2 karbon fiyatlandırma simülasyonunu tek bir boru hattında birleştirir.

---

## 🏛️ Karar Hiyerarşisi ve Sistem Mimarisi

Sistem, Hax & Meal (1975) hiyerarşik planlama mimarisini modern veri mühendisliği ve yöneylem araştırması yaklaşımlarıyla ölçekler:

```
                      [ Ham Sipariş Verisi / ERP ]
                                   │
                                   ▼
          ┌──────────────────────────────────────────────────┐
          │  1. TALEP TAHMİNLEME (LightGBM vs Holt-Winters)   │
          │     - 28 Günlük Ufuk, WAPE Bazlı Model Seçimi    │
          └────────────────────────┬─────────────────────────┘
                                   │ Günlük Talep
                                   ▼
          ┌──────────────────────────────────────────────────┐
          │  2. TAKTİK PLANLAMA (PuLP - Lineer Programlama)  │
          │     - 4 Haftalık Ufuk, Aile Düzeyinde Agregasyon  │
          │     - Fazla Mesai Marjinal Maliyet Analizi       │
          └────────────────────────┬─────────────────────────┘
                                   │ 1. Hafta Koli Hedefleri
                                   ▼
          ┌──────────────────────────────────────────────────┐
          │  3. AYRIŞTIRMA (Disaggregation) & MRP-I         │
          │     - SKU Seviyesine İndirgeme (Parti Boyutu: 25)│
          │     - Emniyet Stoku & Temin Süresi Ötelemesi     │
          └────────────────────────┬─────────────────────────┘
                                   │ Net Üretim Partileri
                                   ▼
          ┌──────────────────────────────────────────────────┐
          │  4. DETAYLI ÇİZELGELEME (Google OR-Tools CP-SAT) │
          │     - Sıra Bağımlı Hazırlık Matrisi (Setup)      │
          │     - Rota Kısıtları & Tezgâh Çakışma Önleme     │
          └────────────────────────┬─────────────────────────┘
                                   │ Dakika Bazlı Zaman Çizelgesi
                                   ▼
          ┌──────────────────────────────────────────────────┐
          │  5. ENERJİ & GHG KAPSAM 1-2 KARBON MUHASEBESİ    │
          │     - 15 Dakikalık Yük Profili & Tepe Güç Takibi │
          │     - EU ETS Karbon Fiyatlama Senaryoları        │
          └──────────────────────────────────────────────────┘
```

---

## 📐 Matematiksel Optimizasyon Modelleri

### 1. Taktik Agrega Üretim Planlama (PuLP - Lineer Programlama)

Taktik model, 4 haftalık dönemde ürün ailelerinin ($f \in F$) standart kapasite, fazla mesai, stok tutma ve talep karşılama dengesini minimize eder.

#### Amaç Fonksiyonu:
$$\min Z = \sum_{t=1}^{T} \sum_{f \in F} \left( c_h \cdot I_{f,t} + c_o \cdot O_{f,t} + c_p \cdot P_{f,t} + c_b \cdot B_{f,t} \right)$$

#### Kısıtlar:
1. **Stok Denge Eşitliği:**
   $$I_{f,t-1} + P_{f,t} - B_{f,t-1} + B_{f,t} = D_{f,t} + I_{f,t} \quad \forall f, \forall t$$
2. **Kapasite ve Fazla Mesai Sınırı:**
   $$\sum_{f \in F} k_f \cdot P_{f,t} \le K_{std} + O_t \quad \forall t$$
   $$O_t \le O_{\max} \quad \forall t$$

* **Duyarlılık ve Gölge Fiyat (Shadow Price):** Kapasite kısıtının dual değeri marjinal fazla mesai sınırında $-675.0\text{ TL/saat}$ olarak hesaplanmıştır; ek kapasite yatırımının sınır eşiği bu değerle doğrulanır.

---

### 2. Detaylı Çizelgeleme (Google OR-Tools CP-SAT)

Operasyonel düzeyde, 1. hafta için netleştirilen partilerin ($b \in B$) tezgâhlar üzerindeki operasyonları ($o_{b,m}$) sıra bağımlı hazırlık süreleriyle modellenir.

#### Amaç Fonksiyonu:
$$\min C_{\max}$$

#### Kısıtlar:
1. **Tezgâh Ayrıklığı (Disjunctive / No-Overlap):**
   Aynı tezgâhta işlenen herhangi iki operasyon aralığı çakışamaz:
   $$\text{IntervalVar}(o_{i,m}) \cap \text{IntervalVar}(o_{j,m}) = \emptyset \quad \forall i \neq j, \forall m$$
2. **Sıra Bağımlı Hazırlık Süresi (Sequence-Dependent Setup):**
   Tezgâh $m$ üzerinde ürün $i$'den ürün $j$'ye geçişte:
   $$\text{Start}(o_{j,m}) \ge \text{End}(o_{i,m}) + S_{i,j,m}$$
3. **Rota Öncelik Kısıtı (Precedence):**
   $$\text{Start}(o_{b, m+1}) \ge \text{End}(o_{b, m}) \quad \forall b \in B$$

* **Çizelgeleme Bulgusu:** Model, M01 (CNC Kesme/İşleme) tezgâhını birincil darboğaz olarak belirlemiş; sezgisel sıralamaya kıyasla toplam akış süresinde **%3.6 zaman tasarrufu** sağlayarak iş akışını 138.8 saatte (Cumartesi 22:39) tamamlamıştır.

---

## 🔬 Talep Tahmini & Doğrulama Metrikleri

5 pilot SKU için 28 günlük günlük talep, çok adımlı özyinelemeli **LightGBM Regressor** ve **Holt-Winters Üstel Düzleştirme** modelleriyle yarıştırılmıştır.

* **Değerlendirme Metriği (WAPE):**
  $$\text{WAPE} = \frac{\sum_{t=1}^n \vert{}y_t - \hat{y}_t\vert{}}{\sum_{t=1}^n y_t}$$

| Ürün Kodu | Ürün Ailesi | Kazanan Model | Test WAPE | Karakteristik |
|:---:|:---:|:---:|:---:|:---|
| **P01** | FAM_A | **LightGBM** | %11.4 | Gecikme (lag) ve takvim öznitelikleri ağırlıklı |
| **P02** | FAM_A | **Holt-Winters** | %9.8 | Güçlü haftalık mevsimsellik bileşeni |
| **P03** | FAM_B | **Holt-Winters** | %8.9 | Düşük varyanslı stabil talep örüntüsü |
| **P04** | FAM_B | **LightGBM** | %12.1 | Doğrusal olmayan trend ve promosyon esnekliği |
| **P05** | FAM_A | **LightGBM** | %10.6 | Çoklu regresyon otokorelasyon avantajı |

---

## 📦 Malzeme İhtiyaç Planlaması (Time-Phased MRP-I)

BOM ağacı üzerinden her hammadde için dinamik stok projeksiyonu:

$$I_{t}^{\text{proj}} = I_{t-1}^{\text{proj}} + SR_t - GR_t$$
$$NR_t = \max\left(0, GR_t + SS - I_{t-1}^{\text{proj}} - SR_t\right)$$

* **Tedarik Güvenliği:** Temin süresi ($L$) geriye ötelendiğinde $t - L \le 0$ durumuna düşen siparişler otomatik olarak **`EXPEDITE (Past Due)`** statüsüne alınarak satınalma birimine acil termin uyarısı iletilir.

---

## ⚡ Enerji Analitiği ve GHG Karbon Muhasebesi

### 15-Dakikalık Yük Profili
$$P_{\text{tesis}}(t) = \sum_{m \in M} \left( P_{m}^{\text{run}}(t) + P_{m}^{\text{setup}}(t) + P_{m}^{\text{idle}}(t) \right)$$

* **Tepe Yük (Peak Load):** $248.1\text{ kW}$ (Ceza eşiği aşılmadan yönetilmiştir).
* **Birim Tüketim:** $2.524\text{ kWh / bitmiş ürün}$.

### Sera Gazı (GHG Protocol Scope 1 & Scope 2)
1. **Kapsam 1 (Doğrudan):** Forklift dizel tüketimi ($2.68\text{ kg CO}_2\text{e/L}$).
2. **Kapsam 2 (Dolaylı):** Ulusal şebeke elektrik tüketimi ($0.440\text{ kg CO}_2\text{e/kWh}$).

| Kapsam Türü | Tüketim / Kaynak | Emisyon ($tCO_2e$) | Birim Emisyon ($kgCO_2e/adet$) |
|:---|:---|:---:|:---:|
| **Scope 1** | 85 Litre Motorin | 0.228 | 0.028 |
| **Scope 2** | 20,603.6 kWh Elektrik | 9.066 | 1.111 |
| **TOPLAM** | **Bütünleşik Operasyon** | **9.293** | **1.139** |

* **EU ETS Duyarlılık Analizi:** Karbon fiyatının 80 €/tCO₂e olduğu senaryoda operasyonun karbon maruziyeti **€743.47** (ürün başına **€0.0911**) olarak simüle edilmiştir.

---

## 📂 Proje Dizin Yapısı

```
├── data/
│   ├── raw/                 # Ham ERP ve üretim işlem kayıtları
│   └── factory.db           # SQLite tekil gerçeklik kaynağı (SSOT)
├── src/
│   ├── config.py            # Tüm boru hattı sabitleri ve parametreleri
│   ├── data_loader.py       # Veri yükleme ve DB şema oluşturma
│   ├── forecasting.py       # LightGBM ve Holt-Winters tahmin motoru
│   ├── aggregate_lp.py      # PuLP taktik agrega planlama
│   ├── disaggregation.py    # Aileden SKU'ya parti ayrıştırma
│   ├── mrp.py               # Zaman fazlı malzeme ihtiyaç planlaması
│   ├── scheduling.py        # OR-Tools CP-SAT detaylı çizelgeleme
│   ├── energy_analytics.py  # 15 dakikalık yük ve tepe güç analitiği
│   └── carbon_analytics.py  # GHG Kapsam 1-2 ve ETS fiyat senaryoları
├── dashboard/
│   └── app.py               # Streamlit yönetici karar platformu
├── tests/
│   └── test_pipeline.py     # pytest matematik ve veri bütünlüğü test paketi
├── requirements.txt         # Kütüphane bağımlılıkları
└── README.md
```

---

## 🚀 Kurulum ve Çalıştırma

### 1. Ortamın Hazırlanması
```bash
# Depoyu klonlayın
git clone https://github.com/kullanici-adi/factory-decision-intelligence.git
cd factory-decision-intelligence

# Sanal ortamı oluşturun ve aktif edin
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate # Linux/macOS

# Bağımlılıkları yükleyin
pip install -r requirements.txt
```

### 2. Boru Hattını Çalıştırma
Tüm modelleri sıralı olarak koşturup SQLite veritabanını güncellemek için:
```bash
python -m src.data_loader
python -m src.forecasting
python -m src.aggregate_lp
python -m src.disaggregation
python -m src.mrp
python -m src.scheduling
python -m src.energy_analytics
python -m src.carbon_analytics
```

### 3. Otomatik Entegrasyon Testlerini Koşturma
```bash
pytest -v
```

### 4. Yönetici Arayüzünü Başlatma
```bash
streamlit run dashboard/app.py
```