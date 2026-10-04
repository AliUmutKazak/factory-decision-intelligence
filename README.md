# Factory Decision Intelligence Engine

> "I designed an end-to-end manufacturing decision-support layer that transforms demand signals into capacity-aware production plans, material requirements and finite machine schedules, then feeds execution deviations back into dynamic replanning while accounting for service level, manufacturing cost, energy and carbon."

---

## 1. System Architecture & Decision Flow

Sistem, monolitik bir simulasyon yerine ISA-95 standartlarina dayali hiyerarsik bir karar destek mimarisi sunar:

```text
[ Demand Signals / LightGBM ]
             |
             v
[ Hierarchical Production Planning (HPP / LP) ]
             |
             v
[ Material Requirements Planning (BOM / MRP) ]
             |
             v
[ Finite Capacity Scheduling (OR-Tools CP-SAT) ]
             |
             +---> [ Energy & Carbon Accounting (GHG Scope 2) ]
             |
             +---> [ Execution Tracking & Dynamic Replanning (MES Feedback) ]
```

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
