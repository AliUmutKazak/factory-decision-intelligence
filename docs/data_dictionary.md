
## 4. MRP Modulu Mimari Kapsami ve Konumlandirma (MRP-I Scope vs ERP Execution)

Bu platformdaki Malzeme Ihtiyac Planlamasi modulu, **MRP-I Analitik Planlama Motoru (Analytical Planning Engine)** olarak konumlandirilmistir.

### Kapsam Dahilinde Olan Analitik Unsurlar (Current Analytical Scope):
- Hiyerarsik taktik plan ciktilarindan (SKU Disaggregation) uretilen haftalik brut ihtiyaclar (Gross Requirements).
- Cok seviyeli urun agaci patlatma (BOM Explosion).
- Planli haftalik brut ihtiyacin 4 haftalik dagilimi ve tedarik suresiyle hesaplanan **kalibre edilmemis malzeme tamponu** (`safety_stock`, `safety_stock_method`) ve baslangic stok projeksiyonu. Bu hesap tahmin hatasina dayanmaz; %95 servis seviyesi kaniti degildir.
- Asgari siparis partisi (MOQ / Lot Sizing) optimizasyonu.
- Temin suresi faz kaydirmasi (Lead Time Offsetting) ve geciken siparisler icin acil tedarik uyarilari (EXPEDITE flags).

### Kapsam Disi / Canli ERP Entegrasyonu Gerektiren Unsurlar (ERP Execution Boundary):
- Tedarikci anlik uretim kapasitesi ve tedarikci calisma takvimleri.
- Canli satinalma siparisi statuleri (Purchase Order Tracking / Open POs).
- Ambara fiili mal kabul ve kalite kontrol kabul zaman damgalari (Material Availability Timestamps).
- Gercek zamanli stok hareketleri ve depo hucre yonetimi (WMS / Goods Receipt).

**Sonuc:** Platform, canli bir kurumsal ERP (ornegin IFS ERP, SAP) yerine gecme amaci tasimaz; bu sistemlerle cift yonlu entegre calisacak sekilde kurgulanmis **Ileri Planlama ve Analitik Karar Destek (Advanced Planning & Decision Intelligence)** katmanidir.


## 5. Veritabanı Mimarisi ve Ölçeklenebilirlik Vizyonu (Database Architecture & Roadmap)

Projede `data/factory.db` üzerinde koşan SQLite veritabanı:

> **"SQLite is the local analytical reference implementation."**

### Mimari Rol ve Mevcut Durum (Current Implementation):
- **Local Analytical Engine:** Deterministik boru hattı (pipeline) yürütümü, CI/CD test koşumları, sıfır bağımlılıklı yerel geliştirme ve tek kullanıcılı analitik karar destek senaryoları için Single Source of Truth (SSOT) olarak görev yapar.
- **Mevcut Veri Erişim Katmanı:** Kod tabanında veri erişimi doğrudan standart `sqlite3` sürücüsü (`sqlite3.connect`) üzerinden sağlanmaktadır. Projede mevcut durumda soyutlanmış bir ORM katmanı (SQLAlchemy) veya Repository Pattern mimarisi bulunmamaktadır.

### Kurumsal Geçiş Yol Haritası (Enterprise Migration Roadmap):
Üretim ortamına (Production) geçişte çoklu kullanıcı ve canlı fabrika entegrasyonu gereksinimleri doğduğunda izlenecek yol haritası:
1. **Concurrency & Real-Time Entegrasyon:**
   - Çoklu planlamacı eşzamanlılığı (Multi-planner concurrency) ve canlı ERP (IFS, SAP)/MES sistemlerinden asenkron veri beslemeleri için **PostgreSQL** veya **Microsoft SQL Server** gibi merkezi bir RDBMS hedeflenmektedir.
2. **Mimari Refactoring Hedefi (Geçiş Aşaması):**
   - Kod tabanındaki doğrudan `sqlite3.connect` çağrılarının, veritabanı motorundan bağımsız bir Veri Erişim Katmanına (Repository Pattern / Database Connector / SQLAlchemy Engine) taşınması planlanmıştır.
   - Bu soyutlama sağlandığında ortam değişkenleri (`DATABASE_URL`) üzerinden PostgreSQL/SQL Server bağlantısı dinamik hale getirilecektir.


## 6. Veri Semantigi: Parti Boyutlandirma (Batch vs. Lot Sizing)

Endustriyel planlama ve cizelgeleme asamalarinda olusan kavram karmasasini onlemek amaciyla veri semantigi su sekilde sabitlenmistir:

- **`planned_units` (Net Uretim Adedi):** Taktik LP ve SKU Disaggregation tarafindan belirlenen, donem icinde uretilmesi gereken brüt/net toplam parca sayisidir.
- **`batch_qty` / `sub_batch_qty` (Operasyonel Cizelgeleme Partisi):** CP-SAT detayli cizelgeleme motoruna aktarilan is parcalarinin fiziksel transfer veya operasyonel partilenme buyuklugudur (ornek: 25 veya 50 adetlik kasalar/paletler). Agrega seviyedeki toplam talep parcalanarak tezgahlar arasinda bu alt partiler halinde akar.
- **`batch_id`:** Belirli bir `product_id` icin cizelgelenen tekil operasyonel parti kimligidir.

## 7. Talep Tahmini Mimarisi: Backtest vs. Production Forecast

Sistemin uretim gercekciligi icin modelleme iki ayrik ufuk (horizon) uzerinde kurgulanmistir:

1. **Model Secimi & Dokunulmamis Son Pencere (Evaluation Horizon):**
   - 28'er gunluk dort ileri zamanli pencerenin ilk ucu model secimi, sonuncusu secime katilmayan holdout degerlendirmesidir.
   - Modeller (Naive, Seasonal Naive, Moving Average, Holt-Winters, LightGBM) ilk uc pencerede WAPE, RMSE ve bias ile karsilastirilir. WAPE tanimsizsa secim RMSE ile yapilir.
   - Son pencerenin sonucu kazanan modeli yeniden secmez; raporlanan `test_score_rmse` o pencereye aittir.
2. **Ileriye Donuk Uretim Ufku (Production Forecast Horizon):**
   - Kazanan model, verinin son gununden itibaren ileriye dogru 28 gunluk operasyonel talep projeksiyonunu uretir.
   - Taktik agregasyon (LP) ve malzeme planlamasi (MRP) yalnizca bu ileri projeksiyon serisi uzerinden calisir; backtest tahminleri uretim planina karistirilmaz.
   - `demand_p10/p90` gunluk secim RMSE'sinden turetilmis kalibre edilmemis gosterim araliklaridir; her satir `interval_method` ve `interval_calibrated=false` tasir. Bunlardan servis hedefi veya malzeme guvenlik stogu cikarilmaz. Yeni kosumlarda `recommended_safety_stock` uretilmez; eski muhurlu artefaktlar tarihsel semalarinda kalir.

## 8. Sürdürülebilirlik & Sera Gazı Modelleme Sınırları (GHG Scope 1 & 2 System Boundaries)

Platformdaki karbon emisyon hesabı, tüm fabrikanın toplam kurumsal ayak izini değil, **operasyonel üretim hücresi sınırlarını** temsil eder:

- **Kapsam İçi (Modeled Production-System Boundary):**
  - **Scope 1 (Doğrudan):** Yalnızca tezgâhlar ve hatlar arası malzeme transferinde tüketilen iç lojistik dizel miktarı (Forklift operasyonu).
  - **Scope 2 (Dolaylı):** Çizelgelenen tezgâhların (M01, M02, M03) işleme, hazırlık (setup) ve rölanti durumlarında tükettiği elektrik enerjisi[cite: 3].
- **Kapsam Dışı Unsurlar (Excluded Facility Loads):**
  - Tesis genel aydınlatması, HVAC (iklimlendirme/havalandırma), merkezi kompresör hattı kayıpları, idari bina tüketimleri ve yardımcı işletmeler (utilities)[cite: 3].
- **Emisyon Hesaplama Yaklaşımı:**
  - Scope 2 elektrik tüketimi **Grid Location-Based** (şebeke ortalama faktörü: $0.440\text{ kg CO}_2\text{e/kWh}$) esasına göre hesaplanmaktadır[cite: 3]. İlerleyen fazlarda yeşil enerji tedariki (I-REC / PPA) senaryoları için **Market-Based** ayrıştırmasına uygun parametrik mimari hedeflenmektedir[cite: 3].   

## 9. Run Lineage ve Yonetisim Semasi (Data Governance)

Her analitik kosumun tekrarlanabilirligi ve izlenebilirligi icin merkezi yonetisim su alanlarla denetlenir:

- **`run_id`**: Her pipeline kosumu icin uretilen benzersiz UUID veya zaman damgasi.
- **`git_sha`**: Kodun calistirildigi commit hash degeri.
- **`config_hash`**: Model ve solver hiperparametrelerinin MD5 ozeti.
- **`data_source`**: Calistirilan veri kaynagi veya test fixture adi (orn: fixture_normal.csv).
- **`forecast_origin`**: Tahminin basladigi referans tarihi (T_0).
- **`solver_status` & `gap`**: CP-SAT çözücünün ulaştığı durum (OPTIMAL / FEASIBLE) ve bileşik amaç fonksiyonuna (Makespan + Setup + Weighted Tardiness) ait bağıl optimality gap yüzdesi (`composite_optimality_gap`). Dual bound saf makespan'i değil, çok amaçlı skalarizasyonun alt sınırını temsil eder.
- **`timestamps`**: Baslangic ve bitis zaman damgalari.
