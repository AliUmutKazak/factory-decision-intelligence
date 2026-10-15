# 15 Ekim 2026: uluslararası ürün ve bilimsel yöntem denetimi

## Kapsam ve kanıt kuralı

FDI'nin karşılaştırılan sürümü, tek sunuculu ve sentetik/açık verili karar destek POC'sidir. Bu inceleme bütün dünya ürünlerinin veya makalelerinin eksiksiz taraması değildir. Üretici belgeleri **beyan edilen işlevi**, özgün yayınlar **çalışmanın kendi deneyini**, FDI deposu ise **bizim laboratuvar kanıtımızı** gösterir. Eş veri, kısıt, donanım, süre ve saha kabulü olmadan ürün üstünlüğü veya müşteri getirisi sıralanmaz. Önceki geniş [Türkiye/dünya taraması](tr-global-science-market-audit-2026-10-11.md) tarihsel bağlamdır.

## Benzer uygulamalarla eş kapsamlı karşılaştırma

| Birincil ürün/araç kaynağı | Kaynakta belgelenen özellik | FDI'deki gerçek durum ve karar |
|---|---|---|
| [Siemens Opcenter Scheduling](https://www.siemens.com/en-us/products/opcenter/advanced-planning-scheduling-aps/advanced-scheduling-software/) | Alternatif kaynak hızı, sıra bağımlı değişim, malzeme kuralları ve planlanan/gerçekleşen zamanları izleme | FDI sabit rotalı çizelgeleme ve dar dosya profiliyle çalışır. Alternatif makine veya canlı actuals kuralı fabrika olmadan türetilmez. |
| [Oracle Fusion Production Scheduling](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/fapsu/index.html) ve [üretim çizelgesi onay/yayım rehberi](https://docs.oracle.com/cd/E18727_01/doc.121/e27241/T581889T582279.htm) | Kurumsal çizelge iş akışı; onay ile yayım ayrı adımlardır | FDI laboratuvar `reschedule` çağrısı başarılı adayı doğrudan ACTIVE yapar; ayrı planlamacı kabulü yoktur. Bu davranış açıkça gösterilir, G9/G10 için insan karar kapısı saha işi kalır. |
| [Timefold score analysis](https://docs.timefold.ai/job-scheduling/latest/user-guide/score-analysis) | Kısıt katkısı, nesne gerekçesi ve harici planı aynı modelde değerlendirme | FDI çözücü durumu/amaç/bound/gap ve bazı bileşen metriklerini gösterir; iş bazlı nedensel gerekçe üretmez. Modelde olmayan kısıt için açıklama uydurulmaz. |
| [PyJobShop esnek job shop örneği](https://pyjobshop.org/latest/examples/flexible_job_shop.html) | Her operasyon uygun makineler arasından seçilebilir | FDI'nin sabit makineli açık JSP kıyası genel FJSP kanıtı değildir. Fabrika uygunluk matrisi olmadan genelleştirilmez. |

Bu ürün belgeleri bağımsız eş koşullu deney değil; FDI'nin maliyet, çözüm kalitesi, hız veya saha başarısı hakkında üstünlük kanıtı vermez.

## Bilimsel kaynaklar ve uygulanan bulgu

| Özgün/otoritatif kaynak | Doğrudan çıkarım | FDI kararı |
|---|---|---|
| [Hyndman & Athanasopoulos, *Forecasting: Principles and Practice*, eğitim/test değerlendirmesi](https://otexts.robjhyndman.com/fpp3/training-test.html) ve [rolling-origin doğrulama](https://otexts.robjhyndman.com/fpp3/tscv.html) | Gelecek ufukta gerçek tahmin hatası, tahmin anında mevcut bilgiye göre ölçülür | Dört ileri zamanlı pencereden ilk üçü model seçimine, son 28 günlük pencere dokunulmamış değerlendirmeye ayrıldı. Seçilen model daha sonra bütün geçmişte yeniden eğitilerek geleceğe uygulanır. |
| [scikit-learn veri sızıntısı ve model seçimi rehberi](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage) | Test verisini model seçiminde kullanmak hata tahminini iyimserleştirebilir | Eski `test_score_rmse`, seçimde kullanılan aynı dört foldun ortalamasıydı; artık son seçilmemiş pencerenin RMSE'sidir. Seçim ve değerlendirme tarihleri/rolleri lineage'da ayrı tutulur. |
| [Hyndman & Koehler, tahmin doğruluğu ölçüleri](https://robjhyndman.com/publications/another-look-at-measures-of-forecast-accuracy/) | Sıfır ve seyrek talepte yüzde ölçekli hata dikkat ister | WAPE sıfır talep ufkunda `NULL` kalır; seçim pencerelerinde tanımsızsa RMSE kullanılır. Holdout WAPE ayrı ve gerekirse `NULL` yazılır. |
| [Sachs & Minner, 2014, sansürlenmiş talep gözlemleri](https://www.sciencedirect.com/science/article/pii/S092552731300203X) | Stok tükenmesi sırasında gözlenen satış, karşılanamayan talebi gizleyebilir | Demo `sales` alanı yalnız talep vekili olarak kullanılır. Gerçek veride stok bulunurluğu, stok tükenmesi ve mümkünse sipariş/kaçan satış kayıtları olmadan satıştan sınırsız talep ya da stok politikası başarısı iddia edilmez. |
| [Dinamik yeniden çizelgelemede verimlilik/kararlılık özgün makalesi](https://www.sciencedirect.com/science/article/pii/S0360835203000950) | Başlangıç planından değişim ile verimlilik birlikte incelenir; makaledeki sonuç simüle atölye içindir | FDI'nin freeze ve nervousness metrikleri korunur. Bu makaleden FDI için sayısal kazanım aktarılmaz. |
| [NIST, üretim dijital ikizinin güvenilirliği](https://www.nist.gov/publications/credibility-consideration-digital-twins-manufacturing) | Doğrulama, geçerleme ve belirsizlik değerlendirmesi kullanım amacına bağlıdır | FDI, saha senkronizasyonu ve gerçek veri geçerlemesi olmadan “doğrulanmış dijital ikiz” diye sunulmaz. |

## Kod ve iddia düzeltmesi

Önceki dört foldun tamamı model seçiminde kullanılıyor, `test_score_rmse` de aynı foldların ortalamasından dolduruluyordu. Bu ayrı test değildi. Güncel protokol **üç seçim fold'u + bir kronolojik holdout fold'u** uygular. `backtest_*` ve `validation_score_wape` seçim foldlarını; `test_score_rmse` yalnız holdout'u temsil eder. `competing_models` her foldun rolünü ve ayrı holdout metriklerini saklar. `forecast_model_metadata.json` değerlendirme tarihlerini taşır. Ayrıca Holt-Winters fit hatasında veya LightGBM için yeterli geçmiş olmadığında sessizce ortalama tahminini o modelin sonucu diye sayma kaldırıldı; adayın başarısızlık nedeni ve seçim dışı durumu kaydedilir. Seçilmiş model holdout'ta değerlendirilemiyorsa pipeline kabul edilmez. Normal-RMSE tabanlı P10/P90 hâlâ **kalibre edilmemiş sezgiseldir**; tek sentetik holdout, nominal kapsama veya müşteri doğruluğu kanıtı değildir. [Regresyon testleri](../tests/test_forecast_zero_demand_contract.py) son pencere rakip lehine olsa da model seçiminin değişmediğini ve kısa geçmişte LightGBM'nin dışlandığını doğrular.

Yerel ve izole 15 Ekim provası, `RUN-20261015-441a7f` kimliğiyle 137,65 saniyede, LF-normalize SHA-256 değeri `1df96565675322d028f505beb048ee124c9e52685a96c041fed97b235e625000` olan [sentetik talep fixture'ında](../data/fixtures/demand_fixture.csv) uçtan uca tamamlandı. Holdout 4–31 Aralık 2017 dönemidir. Aşağıdaki RMSE değerleri aynı ürün miktar birimindedir; seçim ortalaması ile tek holdout penceresi farklı örneklemlerdir.

| Ürün | İlk üç foldla seçilen model | Seçim RMSE ortalaması | Holdout RMSE |
|---|---|---:|---:|
| P01 | Holt-Winters | 8,75 | 7,74 |
| P02 | Holt-Winters | 9,15 | 6,77 |
| P03 | Holt-Winters | 7,67 | 8,32 |
| P04 | Moving Average | 8,09 | 15,44 |
| P05 | Naive | 7,68 | 10,25 |

Koşumun `ACTIVE` veritabanı, fizik çizelgesi, lineage ve mühürlü bundle'ı bağımsız `verify_active_run.py` denetiminden geçti. Bu bir **yerel laboratuvar provasıdır**; aynı kaynak commit'i için [ayrı temiz Windows klon provası](clean-demo-v018-2026-10-15.md) da yapıldı. Paylaşılabilir sürüm kimliği için aynı commit'in CI, artifact ve etiketi [kanıt envanterinde](evidence-register.json) izlenir. Holdout farklarından müşteri faydası veya yöntem üstünlüğü çıkarılmaz.

Kanıt doğrulayıcıda ayrıca bir tarih ayrımı düzeltildi: 12 Ekim tarihli JSP ve tahmin raporlarının kod hash'leri daha önce **bugünkü** çalışma ağacına karşı denetleniyordu. Yeni kaynak kodu geliştikçe bu, tarihsel kanıtı yanlışlıkla geçersiz sayıyordu. [Kanıt envanteri](evidence-register.json) bu raporları `631719c0a24e724a552ae716e4d6c08d09a6d9f9` kaynak commit'ine bağlar; doğrulayıcı rapor hash'ini o commit'teki dosyalarla karşılaştırır. Raporun sayısal sonucunu yeni modele taşımıyor ve eski kanıtı yeniden yazmıyoruz.

Karar: fabrika bağımsız bilimsel açık bu sınırlı değişiklikle giderilir. Genel FJSP, vendor entegrasyonu, canlı onay/yayım ve ekonomik etki için yeterli veri veya kabul yoktur; bunlar [saha kapılarında](fdi-roadmap-execution.md) açık kalır.
