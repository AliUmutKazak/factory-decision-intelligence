# 🏭 Factory Decision Intelligence System
### Decision Support POC, Hierarchical Optimization (LP & CP-SAT), Green Manufacturing & Dynamic Rescheduling Platform
### Endüstriyel Karar Destek, Hiyerarşik Optimizasyon (LP & CP-SAT), Yeşil İmalat ve Dinamik Yeniden Çizelgeleme Platformu

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io)
[![OR-Tools](https://img.shields.io/badge/Google%20OR--Tools-CP--SAT-EA4335?style=flat&logo=google&logoColor=white)](https://developers.google.com/optimization)
[![PuLP](https://img.shields.io/badge/PuLP-LP%20Optimization-4B8BBE?style=flat)](https://coin-or.github.io/pulp/)
[![CI](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/workflows/ci.yml/badge.svg?event=pull_request)](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/workflows/ci.yml)
[![Code Quality](https://img.shields.io/badge/Linter-Ruff%20Clean-black?style=flat)](https://beta.ruff.rs/docs/)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🌐 Executive Summary / Yönetici Özeti

### [TR] Sistem Özeti
**Factory Decision Intelligence System**, ayrık imalat (discrete manufacturing) tesisleri için operasyonel araştırmalar (Operations Research), malzeme gereksinim planlaması (MRP-I), yeşil imalat (green manufacturing) ve gerçek zamanlı dinamik çizelgelemeyi bir araya getiren ileri düzey bir karar destek prototipidir. Taktiksel düzeydeki çok dönemli kapasite ve emisyon kararlarını, operasyonel düzeyde sıra bağımlı hazırlık sürelerine (SDST) sahip sonlu kapasiteli tezgah çizelgelerine bağlar. Atölye zeminindeki beklenmeyen aksaklıklarda (makine arızaları, acil siparişler) dondurulmuş ufuk (freeze horizon) ve çizelge gerginliği (schedule nervousness) metrikleriyle kararlı yeniden çizelgeleme yürütür.

### [EN] System Overview
The **Factory Decision Intelligence System** is an advanced decision intelligence prototype uniting Operations Research (OR), multi-level Material Requirements Planning (MRP-I), green manufacturing constraints, and dynamic shop-floor rescheduling for discrete manufacturing plants. It bridges aggregate tactical decisions (capacity, energy costs, carbon emission caps) with operational finite-capacity machine scheduling featuring Sequence-Dependent Setup Times (SDST). During stochastic events (breakdowns, hot orders), it executes controlled dynamic rescheduling governed by a freeze horizon and quantitative schedule nervousness metrics.

---

## 📑 İçindekiler / Table of Contents
1. [Sistem Mimarisi ve Karar Akışı / System Architecture](#-sistem-mimarisi-ve-karar-akışı--system-architecture)
2. [Matematiksel Modelleme / Mathematical Formulations](#-matematiksel-modelleme--mathematical-formulations)
   - [Taktiksel Katman: LP, Enerji ve Karbon Kısıtları / Tactical LP & Green Constraints](#1-taktiksel-katman-çok-dönemli-agrega-ve-yeşil-planlama-lp)
   - [Operasyonel Katman: OR-Tools CP-SAT & SDST / Operational CP-SAT Model](#2-operasyonel-katman-kısıt-programlama-ile-çizelgeleme-cp-sat)
3. [Malzeme Gereksinim Planlaması / Material Requirements Planning (MRP-I)](#-malzeme-gereksinim-planlaması-mrp-i)
4. [Dinamik Müdahale & Karar Politikaları / Dynamic Policies & Rescheduling](#-dinamik-müdahale-karar-politikaları-ve-gerginlik-nervousness)
5. [Standart Operasyon Prosedürleri / Standard Operating Procedures (SOPs)](#-standart-operasyon-prosedürleri-sops)
6. [Kriptografik İzlenebilirlik / Lineage & Audit Trail](#-kriptografik-izlenebilirlik-lineage--audit-trail)
7. [Teknoloji Yığını / Technology Stack](#-teknoloji-yığını--technology-stack)
8. [API Servis Katmanı & Sözleşmeler / API Layer & Contracts](#-api-servis-katmanı-ve-uç-noktalar)
9. [Karar Destek Kokpiti / Interactive Cockpit (Streamlit)](#-karar-destek-kokpiti-streamlit)
10. [Kurulum, Test & Çalıştırma / Installation & Verification](#-kurulum-test-ve-çalıştırma-rehberi)
11. [Docker ile Konteyner Dağıtımı / Docker Deployment](#-docker-ile-dağıtım)
12. [Dizin Yapısı / Directory Tree](#-dizin-yapısı--directory-tree)

---

## 🏗️ Sistem Mimarisi ve Karar Akışı / System Architecture

Sistem, endüstriyel karar piramidini hiyerarşik katmanlar halinde modeller:

```mermaid
graph TD
    subgraph Katman 1: Veri Ambarı & ETL / Data Persistence
        A[Staging Veri Ambarı / SQLite3] --> B[Siparişler, Çok Seviyeli BOM, İstasyon Rotaları]
    end

    subgraph Katman 2: Taktiksel Planlama & Yeşil İmalat / Tactical LP Layer
        B --> C[Linear Programming - PuLP / CBC]
        C --> D[Haftalık Lot Büyüklükleri & Güvenlik Stoğu]
        C --> E[Fazla Mesai, Enerji Tüketimi & Karbon Emisyon Kotası]
    end

    subgraph Katman 3: Malzeme İhtiyaç Planlaması / MRP-I Engine
        D --> F[BOM Patlatma & Net İhtiyaç Hesabı]
        F --> G[Tedarikçi Teslim Süresi - Lead Time & MOQ]
        G --> H[Bileşen Kısıtlı İmalat Başlangıç Pencereleri - Release Dates]
    end

    subgraph Katman 4: Operasyonel Çizelgeleme / Operational CP-SAT
        E --> I[Constraint Programming Motoru - OR-Tools]
        H --> I
        I --> J[Sonlu Kapasiteli İş-Makine Eşleme]
        I --> K[Sıra Bağımlı Hazırlık Süresi SDST Minimizasyonu]
        I --> L[Vardiya, Mola ve Takvim Kısıtları]
    end

    subgraph Katman 5: Simülasyon, Yeniden Çizelgeleme & Denetim / Reactive Layer
        J --> M[What-If Motoru: Makine Arızası Simülasyonu]
        J --> N[What-If Motoru: Acil Sipariş / Hot-Order Enjeksiyonu]
        M --> O[Dinamik Rescheduler / Dondurulmuş Ufuk - Freeze Horizon]
        N --> O
        O --> P[Çizelge Gerginliği - Nervousness Metrikleri]
        O --> Q[SHA-256 İmzalı Lineage & Audit Log]
    end

    subgraph Katman 6: Servis & Görsel Kokpit / Presentation & API
        P --> R[FastAPI REST API Servisi - Port 8000]
        Q --> R
        P --> S[Streamlit Karar Kokpiti & Plotly Gantt - Port 8501]
        R --> S
```

---

## 📐 Matematiksel Modelleme / Mathematical Formulations

### 1. Taktiksel Katman: Çok Dönemli Agrega ve Yeşil Planlama (LP)
Model; müşteri taleplerini karşılarken üretim maliyeti, stok tutma maliyeti, fazla mesai maliyeti, gecikme (backlog) cezaları ile birlikte **enerji tüketim giderleri** ve **karbon salımı vergisi/kotalarını** bütüncül olarak minimize eder.

#### İndeksler ve Kümeler (Sets & Indices)
* $p \in P$: Nihai ürün aileleri ($p = 1, \dots, \vert{}P\vert{}$)
* $t \in T$: Planlama dönemleri (Haftalar: $t = 1, \dots, N$)
* $m \in M$: Makine / İstasyon grupları ($m = 1, \dots, \vert{}M\vert{}$)

#### Parametreler (Parameters)
* $D_{p,t}$: $t$ döneminde $p$ ürünü için müşteri talebi (adet)
* $CAP_{m,t}^{reg}$: $m$ istasyonunun $t$ dönemindeki normal çalışma kapasitesi (saat)
* $CAP_{m,t}^{ot\_max}$: $m$ istasyonunun azami fazla mesai limiti (saat)
* $a_{p,m}$: Ürün $p$'nin $m$ istasyonunda birim işlenme süresi (saat/adet)
* $c^p_{prod}$: Birim üretim maliyeti ($/adet)
* $h_p$: Dönem sonu birim stok tutma maliyeti ($/adet/dönem)
* $\pi_p$: Birim gecikmiş talep (backlog) cezası ($/adet)
* $c^m_{ot}$: İstasyon bazlı saatlik fazla mesai ücreti ($/saat)
* $e_p$: Ürün $p$'nin birim üretiminde harcanan enerji (kWh/adet)
* $c_{energy}$: Birim elektrik enerjisi fiyatı ($/kWh)
* $co2_p$: Ürün $p$'nin üretimi kaynaklı karbon salımı ($kg\ CO_2/adet$)
* $c_{carbon}$: Karbon emisyon vergi katsayısı ($/kg\ CO_2$)
* $CO2_{cap,t}$: $t$ döneminde yasal olarak aşılamayacak azami karbon salımı tavanı ($kg$)

#### Karar Değişkenleri (Decision Variables)
* $X_{p,t} \ge 0$: $t$ döneminde üretilecek $p$ ürün hacmi
* $I_{p,t} \ge 0$: $t$ dönemi sonundaki $p$ ürün envanter düzeyi
* $S_{p,t} \ge 0$: $t$ döneminde karşılanamayan gecikmiş talep miktarı (backlog)
* $O_{m,t} \ge 0$: $t$ döneminde $m$ makinesinde uygulanan fazla mesai saati

#### Amaç Fonksiyonu (Objective Function)
$$\min Z = \sum_{t \in T} \Bigg[ \sum_{p \in P} \Big( c^p_{prod} X_{p,t} + h_p I_{p,t} + \pi_p S_{p,t} + \big(e_p \cdot c_{energy} + co2_p \cdot c_{carbon}\big) X_{p,t} \Big) + \sum_{m \in M} c^m_{ot} O_{m,t} \Bigg]$$

#### Kısıtlar (Constraints)
1. **Malzeme Dengesi ve Akış Kısıtı (Inventory Flow Balance):**
   $$I_{p,t-1} + X_{p,t} + S_{p,t} - S_{p,t-1} - I_{p,t} = D_{p,t} \quad \forall p \in P, \forall t \in T$$
2. **Kapasite ve Fazla Mesai Sınırı (Capacity & Overtime Upper Bound):**
   $$\sum_{p \in P} a_{p,m} X_{p,t} \le CAP_{m,t}^{reg} + O_{m,t} \quad \forall m \in M, \forall t \in T$$
   $$O_{m,t} \le CAP_{m,t}^{ot\_max} \quad \forall m \in M, \forall t \in T$$
3. **Yeşil İmalat: Dönemsel Karbon Kotası (Carbon Emission Ceiling):**
   $$\sum_{p \in P} co2_p X_{p,t} \le CO2_{cap,t} \quad \forall t \in T$$
4. **Başlangıç Durumları (Boundary Conditions):**
   $$I_{p,0} = Stok_{p}^{baslangic}, \quad S_{p,0} = 0 \quad \forall p \in P$$

---

### 2. Operasyonel Katman: Kısıt Programlama ile Çizelgeleme (CP-SAT)
Google OR-Tools CP-SAT motoru ile sonlu kapasiteli, sıra bağımlı hazırlık süreli (SDST) operasyonel çizelge oluşturulur.

#### Değişkenler ve Aralıklar (Interval Variables)
Her bir üretim görevi $i \in J$ için çözücü üzerinde aralık değişkeni tanımlanır:
$$Interval_i = [S_i, E_i, D_i] \implies E_i = S_i + D_i$$
* $S_i \in [0, T_{max}]$: Operasyon başlangıç dakikası
* $E_i \in [0, T_{max}]$: Operasyon bitiş dakikası
* $D_i$: İşlem süresi (Processing Duration)

#### Kısıtlar ve Mantıksal Kurallar
1. **Kaynak Çakışmama Kısıtı (Disjunctive Resource / No-Overlap):**
   Aynı tezgaha atanan herhangi iki operasyon $i$ ve $j$ zaman ekseninde örtüşemez:
   $$\text{NoOverlap}\big(\{Interval_i \mid Makine(i) = m\}\big) \implies (E_i \le S_j) \lor (E_j \le S_i)$$
2. **Sıra Bağımlı Hazırlık Süreleri (Sequence-Dependent Setup Times - SDST):**
   $i$ ürün grubundan $j$ ürün grubuna geçişte tezgahta temizlik, kalıp değişimi veya ayar süresi ($\tau_{type(i), type(j)}$) zorunludur:
   $$S_j \ge E_i + \tau_{type(i), type(j)} \quad (\text{eğer } j \text{ operasyonu } i\text{'nin hemen ardılı ise})$$
3. **Teknolojik Öncelik İlişkileri (Routing Precedence Constraints):**
   Aynı işin operasyonları proses sırasına uymak zorundadır:
   $$S_{job, op+1} \ge E_{job, op}$$
4. **Malzeme ve Tedarikçi Hazır Olma Kısıtı (Material Release Date):**
   MRP patlatmasından gelen hammadde ve bileşenler depoya girmeden imalat başlatılamaz:
   $$S_i \ge ReleaseTime_i$$
5. **Amaç Fonksiyonu:**
   Tamamlanma süresini (Makespan - $C_{max}$) ve termin gecikmelerini minimize etme:
   $$\min \left( \alpha \cdot C_{max} + \beta \sum_{i \in J} \max(0, E_i - DueDate_i) \right)$$

---

## 📦 Malzeme Gereksinim Planlaması (MRP-I)

Taktiksel LP planının ürettiği haftalık lot büyüklükleri, operasyonel seviyeye malzeme kısıtları olarak aktarılır:
* **Çok Seviyeli BOM Patlatma (Explosion):** Üst montajdan hammaddeye kadar hiyerarşik çarpan hesabı.
* **Tedarikçi Teslim Süresi Dengesi (Lead-Time Offsetting):** Parça temin süresi ($LT_k$) ve Minimum Sipariş Miktarı ($MOQ_k$) gözetilerek satın alma sipariş tarihleri geriye doğru çizelgelenir.
* **Malzeme Kısıtlı Çizelgeleme (Material-Constrained Scheduling):** Her operasyon için $ReleaseTime_i$ değeri malzeme varış saatine kilitlenerek sahada parça bekleme israfı önlenir.

---

## ⚡ Dinamik Müdahale, Karar Politikaları ve Gerginlik (Nervousness)

Atölye zemininde belirsizlikler gerçekleştiğinde uygulanan dinamik politikalar:

### 1. Dondurulmuş Ufuk Politikası (Freeze Horizon Policy)
Mevcut zamandan ($t_{now}$) itibaren belirlenen dondurma periyodu ($H_{freeze}$) içindeki operasyonlar sahada hazırlığı tamamlanmış veya işlem görmekte kabul edilir:
$$S_i = S_i^{orijinal}, \quad Makine_i = Makine_i^{orijinal} \quad \forall i \text{ where } S_i \le t_{now} + H_{freeze}$$
Bu operasyonların sırası ve makine atamaları yeniden çizelgelemede **değiştirilemez**.

Duruş, etkilenen tezgâhtaki dondurulmuş görevlerden sonra uygulanır; başlamış operasyonu kesip devam ettirme modellenmez. Ayrıntılar: [Run isolation and rescheduling](docs/run-isolation-and-rescheduling.md).

`OPERATIONAL_BALANCED` politikası makespan, setup ve tardiness sürelerini dengeler. Eski `COST_OPTIMIZED` adı kaldırılmıştır: CP-SAT parasal toplam üretim maliyetini optimize ettiği iddiasında bulunmaz. Ekonomik senaryo raporları `EconomicConfig` EUR parametreleriyle ayrı hesaplanır.

### 2. Çizelge Gerginliği Metrikleri (Schedule Nervousness Metrics)
Yeniden optimizasyonun sahada yaratacağı operasyonel kaosu sınırlamak için iki metrik ölçülür:
* **Başlangıç Zamanı Sapması (Start Time Displacement):**
  $$\Delta S = \frac{1}{\vert{}J'\vert{}} \sum_{i \in J'} \vert{}S_i^{yeni} - S_i^{eski}\vert{}$$
* **Sıra Değişimi Adedi (Sequence Inversion Count):**
  Tezgahlardaki iş sıralamasının yer değiştirme sayısı.

---

## 📋 Standart Operasyon Prosedürleri (SOPs)

### SOP-01: Rutin Haftalık Planlama Çevrimi (Weekly Planning Routine)
1. **Veri Çekme:** Staging veritabanından güncel talep tahminleri ve envanter seviyeleri yüklenir.
2. **LP Çalıştırma:** PuLP modeli koşturularak haftalık agrega üretim hacimleri, fazla mesailer ve karbon bütçesi hesaplanır.
3. **MRP Patlatma:** Reçeteler (BOM) taranarak malzeme teslim tarihleri ve serbest bırakma saatleri ($ReleaseTime_i$) oluşturulur.
4. **CP-SAT Çizelgeleme:** OR-Tools motoru haftalık sonlu kapasiteli çizelgeyi üretir.
5. **Yayınlama:** Çizelge SQLite'a işlenir ve FastAPI/Streamlit üzerinden dağıtılır.

### SOP-02: Makine Arızası Müdahale Prosedürü (Breakdown Response)
1. **Arıza Girişi:** Arızalanan makine ID'si, arıza anı ($t_{breakdown}$) ve tahmini tamir süresi ($T_{repair}$) girilir.
2. **Dondurma Uygulama:** $t_{breakdown} + H_{freeze}$ penceresindeki işler kilitlenir.
3. **What-If Simülasyonu:** `/api/v1/schedule/what-if/breakdown` çağrılarak termin gecikmeleri simüle edilir.
4. **Onay & Reschedule:** Kabul edilebilir senaryo seçilerek `/api/v1/schedule/reschedule` ile yeni çizelge yürürlüğe alınır.

### SOP-03: Acil Sipariş Enjeksiyon Prosedürü (Hot-Order Injection)
1. **Öncelik Tanımlama:** Acil sipariş yüksek öncelik bayrağı ve teslim tarihi ile sisteme verilir.
2. **Çatışma Analizi:** `/api/v1/schedule/what-if/hot-order` çağrısı ile mevcut müşteri siparişlerinde oluşacak gecikmeler listelenir.
3. **Kapasite Tahsisi:** Mümkünse mesai artışı, değilse düşük öncelikli işlerin ötelenmesiyle acil sipariş hatta enjekte edilir.

---

## 🛡️ Kriptografik İzlenebilirlik (Lineage & Audit Trail)

Yayınlanan yeniden çizelgeleme kararları audit tablosuna ve karar kütüğüne kaydedilir; bundle dosyalarının SHA-256 özetleri değişiklikleri tespit eder. Sandbox what-if işlemleri runtime verisini değiştirmez:
* **Olay Kaydı:** Tetikleyici olay tipi (`BREAKDOWN`, `HOT_ORDER`, `PERIODIC`).
* **Veri Özeti (Cryptographic Hash):** Girdi ve çıktı çizelgeleri **SHA-256** özeti alınarak mühürlenir.
* **Denetim Tablosu:** SQLite `reschedule_audit_log` tablosunda saklanır ve `/api/v1/schedule/audit-log` üzerinden denetlenebilir.

---

## 🧰 Teknoloji Yığını / Technology Stack

| Alan / Layer | Teknoloji / Kütüphane | Versiyon / Standart | Açıklama |
|---|---|---|---|
| **Matematiksel Modelleme** | Google OR-Tools (CP-SAT), PuLP | Python Library | Ayrık kısıt programlama ve lineer programlama çözücüleri |
| **Backend & REST Servis** | FastAPI, Uvicorn | 0.110+ | Asenkron, OpenAPI/Swagger destekli servis mimarisi |
| **Veri Şeması & Doğrulama** | Pydantic | v2.x | Tip güvenliği ve veri sözleşmeleri (Contracts) |
| **Karar Kokpiti & UI** | Streamlit, Plotly Express | 1.32+ | İnteraktif Gantt şeması, senaryo kıyası ve yönetici kokpiti |
| **Veri Tabanı & Analitik** | SQLite3, Pandas, NumPy | Python Builtin / 2.x | Veri ambarı, staging hatları ve denetim logları |
| **Test & Kalite Güvencesi**| Pytest, Ruff, GitHub Actions | CI quality gates | Birim, regresyon, entegrasyon ve Docker başlangıç testleri |
| **Konteynerizasyon** | Docker, Docker Compose | Python 3.11-slim | Pipeline hazırlığı, ACTIVE doğrulaması ve servis başlangıcı |

---

## 🔌 API Servis Katmanı ve Uç Noktalar

FastAPI backend servisi `http://localhost:8000` portunda yayın yapar. İnteraktif Swagger arayüzüne `http://localhost:8000/docs` adresinden erişilebilir:

| Metot | Uç Nokta (Endpoint) | Parametre / Gövde (Payload) | Açıklama |
|---|---|---|---|
| `GET` | `/health` | - | Servis canlılığı |
| `GET` | `/ready` | - | ACTIVE sürüm ve solver metadata kontrolü; run_id döndürür |
| `GET` | `/api/v1/schedule/current` | - | SQLite üzerindeki aktif operasyonel çizelgeyi döndürür |
| `POST` | `/api/v1/schedule/what-if/breakdown` | `{"machine_id": "M01", "start_min": 480, "duration_min": 60}` | Makine duruşunu simüle eder; gecikme ve sapma analizi sunar |
| `POST` | `/api/v1/schedule/what-if/hot-order` | `{"order_id": "HOT_01", "product_id": "P01", "quantity": 25, "due_date_min": 2880, "priority_weight": 10}` | Acil siparişin mevcut çizelge üzerindeki etkisini hesaplar |
| `POST` | `/api/v1/schedule/reschedule` | `{"trigger": {"event_id": "EVT-01", "current_time_min": 480, "freeze_horizon_min": 60, "delay_machine_id": "M01", "delay_duration_min": 60}}` | Dondurulmuş ufuk kurallarıyla yeni çizelgeyi üretir ve kaydeder |
| `GET` | `/api/v1/schedule/audit-log` | `?limit=50` | SHA-256 imzalı geçmiş simülasyon ve plan denetim loglarını listeler |

---

## 📊 Karar Destek Kokpiti (Streamlit)

Streamlit karar paneli (`http://localhost:8501`), karar vericilere interaktif yetenekler sunar:
* **Gantt Çizelgesi Görselleştirme:** Makine, ürün grubu ve SDST hazırlık sürelerinin zaman çizelgesindeki renkli dağılımı.
* **Darboğaz & Kapasite Paneli:** İstasyon doluluk oranları, bekleme süreleri ve fazla mesai analizleri.
* **What-If Simülatörü:** Web arayüzünden arıza veya acil sipariş tetikleyerek çizelgeleri yan yana karşılaştırma.
* **Lineage & Audit Gezgini:** Sistem kararlarının ve kriptografik özetlerin denetim dökümü.

---

## 🚀 Kurulum, Test ve Çalıştırma Rehberi

### 1. Yerel Python Ortamı Kurulumu

```bash
# 1. Depoyu klonlayın
git clone https://github.com/AliUmutKazak/factory-decision-intelligence.git
cd factory-decision-intelligence

# 2. Sanal ortamı oluşturun ve aktifleştirin
python -m venv factory-env
# Windows:
factory-env\Scripts\activate
# Linux/macOS:
source factory-env/bin/activate

# 3. Bağımlılıkları yükleyin
pip install -r requirements.txt
```

### 2. Pipeline, doğrulama ve testler

Servislerden ve entegrasyon testlerinden önce doğrulanmış bir ACTIVE plan oluşturun:

```bash
python main.py
python scripts/verify_active_run.py
python -m pytest tests/ -v
```

### 3. FastAPI Servisini Başlatma

```bash
uvicorn src.api.server:app --reload --port 8000
```
* **Swagger Arayüzü:** `http://localhost:8000/docs`
* **Health Check:** `http://localhost:8000/health`

### 4. Karar Destek Kokpitini Başlatma (Streamlit)

Ayrı bir terminalde:
```bash
streamlit run dashboard/app.py
```
* **Kullanıcı Paneli:** `http://localhost:8501`

---

## 🐳 Docker ile Dağıtım

Docker Compose ilk başlangıçta pipeline çalıştırır, bundle ve ACTIVE run doğrulamasından sonra API ve dashboard servislerini açar. Sonraki başlangıçlarda doğrulanmış mevcut ACTIVE sürümü kullanır:

```bash
# Servisleri derleyin ve başlatın
export FACTORY_BUILD_GIT_SHA=$(git rev-parse HEAD)
docker compose up --build -d --wait --wait-timeout 240 api dashboard
```

* **FastAPI Backend:** `http://localhost:8000/docs`
* **Streamlit Dashboard:** `http://localhost:8501`
* **Hazır olma kontrolü:** `http://localhost:8000/ready`
* **Durdurmak için:** `docker compose down`

`data/`, `reports/` ve `artifacts/runs/` kalıcı ve servisler arasında paylaşılan dizinlerdir. Mevcut ACTIVE bundle doğrulanamazsa başlangıç durur. Bilinçli yeni plan üretimi için `docker compose run --rm pipeline python scripts/bootstrap_runtime.py --refresh` çalıştırın. Temiz Docker başlangıcı ve yeniden başlatma CI içinde sınanır. Bu dağıtım tek sunuculu demo/POC içindir; üretim SaaS hazır olduğu iddia edilmez.

---

## 📂 Dizin Yapısı / Directory Tree

```text
factory-decision-intelligence/
├── data/                       # Üretim veritabanı (factory.db) ve staging tabloları
├── dashboard/                  # Streamlit karar destek arayüzü
│   └── app.py                  # Karar kokpiti, Gantt grafikleri ve senaryo paneli
├── src/
│   ├── api/                    # FastAPI REST servis mimarisi
│   │   └── server.py           # Endpoint tanımları ve HTTP işleyicileri
│   ├── contracts/              # Pydantic veri sözleşmeleri ve şemaları
│   ├── planning/               # Kademe 1: Taktiksel LP Planlama (PuLP / CBC)
│   ├── mrp/                    # Kademe 2: MRP-I, BOM patlatma ve lead-time dengeleme
│   ├── scheduling/             # Kademe 3 & 5: CP-SAT Çizelgeleme ve What-If motoru
│   │   ├── schedule_cpsat.py   # OR-Tools sonlu kapasite çizelgeleyicisi
│   │   ├── what_if.py          # Arıza ve acil sipariş simülatörü
│   │   └── rescheduler.py      # Freeze Horizon & Dinamik Rescheduler
│   └── config.py               # Konfigürasyon, yollar ve ortam değişkenleri
├── tests/                      # Birim, entegrasyon ve regresyon testleri
├── Dockerfile                  # Python 3.11-slim Docker imaj reçetesi
├── docker-compose.yml          # FastAPI ve Streamlit mikroservis orkestrasyonu
├── .dockerignore               # Docker imaj filtreleme kuralları
├── requirements.txt            # Python bağımlılık listesi
└── README.md                   # Kapsamlı sistem ve mimari dokümantasyonu
```

---

## 📜 Lisans & Geliştirici / License & Author

* **Geliştirici / Author:** Ali Umut Kazak — Endüstri Mühendisi / Karar Zekası & Optimizasyon
* **Lisans / License:** MIT Lisansı — Detaylar için `LICENSE` dosyasına bakınız.
