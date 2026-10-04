# Factory Decision Intelligence Engine

> "An open, Python-based, transparent APS / Decision Intelligence research-to-production architecture. It implements a closed-loop production decision-support system that transforms demand signals into capacity-aware production plans, material requirements and finite machine schedules, then feeds execution deviations back into dynamic replanning while accounting for service level, manufacturing cost, energy and carbon."

---

## 1. System Architecture & Decision Flow

Platform, standartta ayrı bir "Level" olarak yer almayan bağımsız bir katman değil; **ISA-95 Level 3 (MOM/MES) ile Level 4 (Kurumsal/ERP) arayüzü çevresinde konumlanan bir İleri Planlama ve Karar Zekası Katmanıdır (APS / Decision Intelligence Layer)**.

Sistem, çift yönlü fiziksel varlık kontrolü gerektiren tam bir "Digital Twin" yerine; sahadan gelen telemetri ve MES geri bildirimlerini işleyen kapalı çevrim bir **"Decision-Support System" (Digital Shadow benzeri operasyonel katman)** olarak konumlandırılmıştır. Bilgi değişimi ve karar döngüsü kapalı çevrim olarak şu akışla işler:

```text
ERP (Level 4 Enterprise Boundary)
 │
 ▼
Demand Forecasting (LightGBM)
 │
 ▼
Tactical Planning (HPP / LP Multi-Period)
 │
 ▼
Material Requirements Planning (BOM / MRP)
 │
 ▼
Finite Capacity Scheduling (OR-Tools CP-SAT)
 │
 ├──► Energy & Carbon Accounting (GHG Scope 2)
 │
 ▼
MES / Shopfloor Execution (Level 3 Operations)
 │
 ▼
Actuals & Execution Deviations (Work Responses / Events)
 │
 ▼
Dynamic Replanning (Two-Tier Repair / CP-SAT Re-optimization)
```

Bu kapalı çevrim akış; **Cost**, **Service Level**, **Energy**, **Carbon**, **Scenario Simulation** ve **Data Lineage** boyutlarını tek bir bütünleşik karar yapısında birleştirir. Mimari, güncel literatürdeki *closed-loop decision intelligence* ve *agentic APS* araştırma eksenleriyle doğrudan uyumludur[cite: 4].

---

## 2. Core Pillars & Capabilities

### A. Hierarchical Production Planning & Scheduling
- **Taktik Katman (HPP LP):** Kapasite darbogazlarini, fazla mesai maliyetlerini ve stok dengelerini optimize eden dogrusal programlama modeli.
- **Operasyonel Cizelgeleme (CP-SAT):** Tezgah kisitlari, hazirlik (setup) matrisleri, oncelik zincirleri ve cok amacli hedef politikalari (`ObjectivePolicy`: `BALANCED`, `THROUGHPUT_MAX`, `SERVICE_LEVEL_FIRST`).

### B. Scenario Engine & Sensitivity Analysis (What-If)
- **Kapsam:** Talep soku (+%20), kapasite kisiti (-%10), enerji dalgalanmasi (+%25), karbon vergisi artisi (+50 EUR/tCO2), makine arizasi ve hammadde gecikmesi.
- **Izole Calisma (Isolated Sandbox):** Canli veritabanini kirletmeden secili asamalari gecici izole ortamda kosturur.
- **KPI Reconciliation:** Makespan, servis seviyesi (OT%), stok maliyeti, backlog, enerji tuketimi (kWh) ve net karbon ayak izi (tCO2e) uzerinde delta mutabakati uretir.

### C. Closed-Loop Execution & Dynamic Replanning
- **Two-Tier Rescheduling:** Fast Local Repair (minor dalgalanmalar) ve CP-SAT Re-optimization (major arizalar).
- **Frozen Horizon Prensipleri:** COMPLETED (dokunulmaz), RUNNING (baslangic kilitli), SCHEDULED (esnek/kaydirilabilir).

### D. ISA-95 Entegrasyon Sınırları & Adapter Kontratları (Madde 26)
Sistem, MESA International B2MML ve ANSI/ISA-95 standartları ile semantik olarak hizalanmış Canonical Contract mimarisi kullanır:

```text
Internal Canonical Contract (Pydantic v2)
         │
         ▼
ISA-95 Semantic Alignment (ANSI/ISA-95 Part 2 & Part 3)
         │
         ├──► JSON API Adapter (Modern Cloud / REST)
         ├──► B2MML / XML Adapter (MESA Standard Integration)
         └──► Vendor-Specific Adapters (SAP S/4HANA, IFS, Siemens Opcenter)

---

## 3. Verification & Quality Gates

```bash
# Statik Kod Kalitesi ve Bicipelendirme
python -m ruff check scripts/ src/ tests/
python -m ruff format --check scripts/ src/ tests/

# Butunlesik Test Suiti (90+ Test)
python -m pytest -q
```
