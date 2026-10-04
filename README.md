# Factory Decision Intelligence Engine

> "An open, Python-based, transparent APS / Decision Intelligence research-to-production architecture. It implements a closed-loop production decision-support system that transforms demand signals into capacity-aware production plans, material requirements and finite machine schedules, then feeds execution deviations back into dynamic replanning while accounting for service level, manufacturing cost, energy and carbon."

---

## 1. System Architecture & Decision Flow

Platform, standartta ayrı bir "Level" olarak yer almayan bağımsız bir katman değil; **ISA-95 Level 3 (MOM/MES) ile Level 4 (Kurumsal/ERP) arayüzü çevresinde konumlanan bir İleri Planlama ve Karar Zekası Katmanıdır (APS / Decision Intelligence Layer)**.

Sistem, çift yönlü fiziksel varlık kontrolü gerektiren tam bir "Digital Twin" yerine; sahadan gelen telemetri ve MES geri bildirimlerini işleyen kapalı çevrim bir **"Decision-Support System" (Digital Shadow benzeri operasyonel katman)** olarak konumlandırılmıştır. Bilgi değişimi ve karar döngüsü kapalı çevrim olarak şu akışla işler:

```text
┌────────────────────────────────────────────────────────┐
│ ERP / Business Systems                                 │
│ Orders • BOM • Inventory                               │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Demand Intelligence                                    │
│ Forecast / Backtest / Lineage                          │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Tactical Planning                                      │
│ Hax & Meal / LP / Capacity                             │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Analytical MRP-I                                       │
│ BOM / Lead Time / Availability                         │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Finite Scheduling                                      │
│ CP-SAT / Setup / Maintenance / Service Level / Cost    │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ MES Dispatch / Execution                               │
└───────────────────────────┬────────────────────────────┘
                            │
                      Actuals / Events
                            ▼
┌────────────────────────────────────────────────────────┐
│ Closed Loop                                            │
│ Variance / Freeze / Replan                             │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Decision Intelligence Crosscut                         │
│ Cost • Service • Energy • Carbon • Scenario • Lineage  │
│ Decision Ledger • Governance                           │
└────────────────────────────────────────────────────────┘
```

Bu kapalı çevrim akış; **Cost**, **Service Level**, **Energy**, **Carbon**, **Scenario Simulation** ve **Data Lineage** boyutlarını tek bir bütünleşik karar yapısında birleştirir. Mimari, güncel literatürdeki *closed-loop decision intelligence* ve *agentic APS* araştırma eksenleriyle doğrudan uyumludur[cite: 4].

---
### Explicit Scope Boundaries & Non-Goals (Madde 36)

Sistemin matematiksel titizliğini ve doğrulanabilirliğini korumak amacıyla aşağıdaki bileşenler bilinçli olarak kapsam dışında bırakılmıştır:

- **Predictive Maintenance ML:** Kestirimci bakım arıza tahminleri yerine kesin bakım pencereleri ve duruş rezervasyonları üzerinden deterministik çizelgeleme yapılır.
- **Direct ERP/SAP Live Connectors:** Ağır ve kırılgan canlı ERP konnektörleri yerine ISA-95 Level 4 adapter sözleşmeleri ve staging veri modelleri kullanılır.
- **SCADA/PLC Hardware Protocols:** Saha seviyesi (Level 1-2) sinyal işleme yerine MES (Level 3) iş emri ve duruş olayları işlenir.
- **Distributed Microservices / K8s:** Erken dağıtık mimari karmaşıklığından kaçınılarak modüler, deterministik çekirdek kütüphane yapısı korunur.
- **Unbounded 4-Week Horizon CP-SAT:** NP-hard çizelgeleme ufku pratik operasyonel sınırda tutulur; uzun vade taktiksel LP (Hax & Candea) modeline delege edilir.
- **Full Bidirectional Digital Twin:** Çift yönlü fiziksel aktüasyon yerine telemetri ve MES olaylarını işleyen karar destek katmanı (Digital Shadow) hedeflenir.
- **LLM as Optimizer:** Dil modelleri optimizasyon veya çizelgeleme çözücüsü yerine konulmaz; yalnızca Karar Defteri (Decision Ledger) üzerinden açıklanabilirlik ve karar gerekçelendirmesi sağlar.


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

---

## 4. Future Roadmap: Agentic AI & Planner Copilot (Madde 31)

Sistem mimarisinde Üretici Yapay Zeka (LLM), doğrudan çizelge üreten bir kara kutu olarak **konumlandırılmaz**. Optimizasyon problemleri deterministik matematiksel modeller (CP-SAT / LP) gerektirir[cite: 6]. LLM/Agent mimarisi, deterministik motorun üzerinde bir **"Planner Copilot"** olarak kurgulanmıştır[cite: 6]:

```text
LLM / Agent
    │  (Doğal dil senaryo talebi: "M01 tezgahı 6 saat durursa ne olur?")
    ▼
Validated Tools & Scenario Engine
    │  (Doğrulanmış parametreler ve kısıtlar)
    ▼
OR-Tools CP-SAT Solver
    │  (Deterministik matematiksel çözüm)
    ▼
Decision Result & Multi-Criteria Impact
    │  (Cost, Service Level, Energy, Carbon)
    ▼
Human Approval & Lineage Audit
