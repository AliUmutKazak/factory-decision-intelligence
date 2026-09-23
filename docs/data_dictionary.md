
## 4. MRP Modulu Mimari Kapsami ve Konumlandirma (MRP-I Scope vs ERP Execution)

Bu platformdaki Malzeme Ihtiyac Planlamasi modulu, **MRP-I Analitik Planlama Motoru (Analytical Planning Engine)** olarak konumlandirilmistir.

### Kapsam Dahilinde Olan Analitik Unsurlar (Current Analytical Scope):
- Hiyerarsik taktik plan ciktilarindan (SKU Disaggregation) uretilen haftalik brut ihtiyaclar (Gross Requirements).
- Cok seviyeli urun agaci patlatma (BOM Explosion).
- Guvenlik stogu (Safety Stock) esikleri ve baslangic stok projeksiyonu (Projected Available Balance).
- Asgari siparis partisi (MOQ / Lot Sizing) optimizasyonu.
- Temin suresi faz kaydirmasi (Lead Time Offsetting) ve geciken siparisler icin acil tedarik uyarilari (EXPEDITE flags).

### Kapsam Disi / Canli ERP Entegrasyonu Gerektiren Unsurlar (ERP Execution Boundary):
- Tedarikci anlik uretim kapasitesi ve tedarikci calisma takvimleri.
- Canli satinalma siparisi statuleri (Purchase Order Tracking / Open POs).
- Ambara fiili mal kabul ve kalite kontrol kabul zaman damgalari (Material Availability Timestamps).
- Gercek zamanli stok hareketleri ve depo hucre yonetimi (WMS / Goods Receipt).

**Sonuc:** Platform, canli bir kurumsal ERP (ornegin IFS ERP, SAP) yerine gecme amaci tasimaz; bu sistemlerle cift yonlu entegre calisacak sekilde kurgulanmis **Ileri Planlama ve Analitik Karar Destek (Advanced Planning & Decision Intelligence)** katmanidir.


## 5. Veritabani Mimarisi ve Olceklenebilirlik Vizyonu (Database Architecture & Roadmap)

Projede `data/factory.db` uzerinde kosan SQLite veritabani:

> **"SQLite is the local analytical reference implementation."**

### Mimari Rol ve Konumlandirma:
- **Mevcut Kapsam (Local Analytical Engine):** Deterministik boru hatti (pipeline) yurutumu, CI/CD test kosumlari, sifir bagimlilikli yerel gelistirme ve tek kullanicili taktik/operasyonel karar destek senaryolari icin Single Source of Truth (SSOT) olarak gorev yapar.
- **Kurumsal Olceklenebilirlik Siniri (Enterprise Production Target):**
  - Coklu planlamaci (Multi-planner concurrency) ve eszamanli senaryo calistirma,
  - Canli ERP (IFS, SAP) ve MES sistemlerinden gercek zamanli veri akisi,
  - Cok kullanicili eszamanli web paneli sorgulari.
  Bu operasyonel hedefler icin veri erisim katmani (Repository Pattern / SQLAlchemy / Database Connector), baglanti dizesi (Connection String) degisikligi ile **PostgreSQL** veya **Microsoft SQL Server** gibi ACID uyumlu merkezi bir RDBMS'e gecise hazir soyutlama standartlarinda tasarlanmalidir.
