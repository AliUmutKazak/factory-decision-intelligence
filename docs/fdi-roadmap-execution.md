# FDI birleşik yol haritası: uygulama ve kanıt kaydı

Kaynak: `FDI_Nihai_Birlesik_Yol_Haritasi.pdf`, v1.1, 7 Ekim 2026 (13 sayfa; SHA-256 `21bc94922174c9f8d72e5d26aab23373009d3474781f7f72727556b38c2b865a`). Bu dosya PDF'deki G0-G13 kapılarının ve fabrika anlaşması gerektirmeyen G1-T/G4-T/G5-T/G6-T/G8-T teknik hazırlık kolunun yaşayan uygulama kaydıdır. PDF'deki öneriler, müşteri veya vendor kabulü yerine geçmez. Kapı durumu yalnız kanıt ve yetkili kabul ile değişir.

8 Ekim 2026 tarihli saha erişimi araştırması [ayrı karar kaydında](saha-erisim-raporu-degerlendirmesi.md) değerlendirildi. Dış FJSP örneği ve bağımsız çizelge denetimi G8-T'ye yardımcı teknik işlerdir; birleşik yol haritasının saha kapılarını kapatmaz.

## Durum dili ve yürütme kuralı

- **Bekliyor:** işe başlanmadı veya gerekli dış girdi yok.
- **Çalışılıyor:** uygulama ya da ölçüm sürüyor.
- **Kanıt hazır:** tanımlı kontrollerin kanıtı toplandı, yetkili kabulü bekliyor.
- **Kabul edildi:** adı belli sorumlu, kapsamı ve kanıtı onayladı.

Her kayıt için kapı/görev kimliği, sorumlu, commit/run/dataset kimliği, ölçüm tarihi, kapsam, sonuç, açık risk, artifact bağlantısı ve kabul veren rol tutulur. Kaynak kod, veri, vendor profili veya ölçüm kapsamı değişirse etkilenen kanıt yeniden değerlendirilir. Takvim dolması kapıyı geçirmez.

Fabrika bulunana kadarki teknik sıra: **G0 sürüm → G1-T referans profil → G2 güvenlik ve G3 veri platformu → G4-T veri hazırlığı ve G5-T mesajlaşma → G6-T üretim semantiği ve G7 işletim → G8-T bağımsız kıyas → dar kapsamlı dosya pilotu teklifi**. Fabrika anlaşmasından sonra G1, G4-G8 saha kabulü, G9 gölge pilot, G10 kontrollü üretim, G11 ekonomik kabul ve G12 ikinci tesis kurulumu izlenir. G13 ayrı yatırım kararıdır. Bağımsız tasarım işleri uygun bağımlılıklar altında paralel ilerleyebilir.

## Güncel teknik dayanak (7 Ekim 2026)

- Proje sahibi 7 Ekim 2026'da henüz pilot fabrika, temsilî müşteri verisi ve ERP/MES test erişimi bulunmadığını bildirdi. Bu nedenle saha kabulü gerektiren kapılar için kanıt toplama başlamadı; teknik hazırlık sentetik/veri-sözleşmesi düzeyinde yürütülür.
- PR [#1](https://github.com/AliUmutKazak/factory-decision-intelligence/pull/1) birleşti: PR head `665b14995b9824e99e6d890a7c1e5a0832410fbd`, birleşme commit'i `a938aaaf5a328f42cf9fb00bfb104f210803794b`. PDF'deki "PR açık" gözlemi tarihsel durumdur.
- Birleşme commit'inin [main CI koşumu 37639606808](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/37639606808) başarılıdır. Kalite/entegrasyon/test ve temiz Docker başlangıcı/yeniden başlatma işleri ayrı ayrı başarılıdır. Görünen uyarılar GitHub Actions Node 20 kullanımı ve yaklaşan `ubuntu-latest` geçişi hakkındadır.
- Depoda henüz Git sürüm etiketi yoktur. CI yayımlanmış bir image veya indirilebilir release artifact üretmiyor; dolayısıyla image digest'i mevcut kanıt olarak gösterilemez.
- Kanonik referans `RUN-20261006-00a0d3`, kaynak commit `63d33899b13894c7b0f963d5e97721d6fd6afa36` üzerinde üretilmiştir. Depodaki ham referans manifest SHA-256: `6c6a61358608d12d3d374428446621b8dda0156cd20bc0a449dd732d96ecaf6e`. Bu kaynak, birleşme commit'iyle aynıymış gibi sunulmaz.
- `artifacts/demo/benchmark.json` ham SHA-256: `268e14b2d35e5b5919a7603f5097aa321e6600ef8f28c29a51e27b9d4d124803`. Bu demo sentetik/modele dayalıdır; gerçekleşmiş müşteri ROI'si değildir.
- Temiz Python 3.11 ortamında Ruff kontrolü ve biçim denetimi geçmiştir. Windows Türkçe konsol kodlamasında ilk pipeline denemesi `✓` karakterini basarken durdu; CLI UTF-8 çıkışa geçirildi. Varsayılan Windows konsolunda `RUN-20261007-255265` uçtan uca başarıyla ACTIVE yayımlandı; `verify_active_run.py` veritabanı, fiziksel kontrol, lineage ve bundle hash doğrulamasını geçti.
- Windows `core.autocrlf=true` referans/demo artifact'larının ve resmî B2MML şemalarının satır sonlarını değiştirip SHA-256 doğrulamasını bozdu. `.gitattributes` ile bu dosyalarda dönüşüm kapatıldı; ham Git blob'larıyla referans ve şema bütünlük kontrolleri geçti. Windows dosya kilitleri için SQLite bağlantıları açıkça kapatıldı.
- İlk tam pytest koşumunda **214/215 geçti**; son hot-order senaryosu varsayılan 30 sn CP-SAT sınırında `UNKNOWN` döndü. Sabit referanslı doğruluk testi 90 sn bütçeyle geçti; 30 sn hizmet performansı G7 riski olarak açık kaldı. Ortak rapor dizini ve arıza etkisi hakkında sabit takvim varsayımlarına bağlı testler düzeltildi. 8 Ekim'de **222 test tek kesintisiz koşumda geçti** (1222,49 sn). Sonradan eklenen FJSP/JSP ayrıştırıcı, bağımsız denetim, `ft06` bellek içi aktarım ve alternatif makine reddi testleri için **18 hedefli test** geçti. Yeni testlerin tamamını içeren tek tam koşum henüz yapılmadı. Docker bu Windows ortamında kurulu değil; yerel Docker yeniden başlatma kanıtı yok.

## G0-G13 kapı matrisi

| Kapı | Durum | Bu depoda mevcut dayanak | Geçiş için eksik kanıt / karar |
|---|---|---|---|
| G0 Sürüm | Çalışılıyor | PR birleşti; aynı merge commit'inde main CI ve Docker restart başarılı; referans manifest var | Yerel tam test sonucu ve Windows kurulum düzeltmesi; release adayı/etiket kararı; release artifact ve image digest politikası; P0 kusur incelemesi ve teknik lider kabulü |
| G1 Pilot sözleşmesi | Bekliyor | `docs/pilot-charter.md` karar ve kabul şablonu hazır; G1-T referans profili müşteri sözleşmesinden ayrı tutuluyor | Tesis/hat/ürün ailesi, pilot sahibi, planlamacı ve IT/MES onayı; planlama ufku, KPI eşikleri, veri/erişim, karar-onay rolleri ve actuals akışı |
| G2 Güvenlik | Çalışılıyor | `docs/security-boundary.md` uç/yetki envanteri ve audit kayıtları var; Docker portları yalnız `127.0.0.1` adresine bağlandı; API'de kimlik doğrulama ve rol politikası görünmüyor | Kimlik sağlayıcı, issuer/audience doğrulaması, ayrı mutation yetkileri, TLS/ağ sınırı, secrets/container sertleştirme, negatif yetki testleri ve güvenlik CI |
| G3 Veri platformu | Bekliyor | SQLite run izolasyonu, atomik ACTIVE yayın ve immutable bundle var | Repository sınırı, PostgreSQL migration/transaction tasarımı, eşzamanlı onay testleri, gerçek veri öncesi backup-restore provası; eski run korunumu |
| G4 Müşteri verisi | Bekliyor | `CustomerFileAdapter` ve açık ID/alan eşlemeleri var | Gerçek veri sahibi, profil ve canonical mapping, birim/zaman dilimi kontrolü, reject kayıtları, onaylı veri seti; sessiz sentetik ikame yok |
| G5 Entegrasyon | Bekliyor | B2MML 0701 doğrulanan fabrika profili ve dosya adaptörü var | ERP/MES vendor, test tenant ve sözleşme; gerçek plan/actuals round-trip, retry/idempotency, geç/sırasız/bozuk mesaj kanıtı |
| G6 Fabrika kuralları | Bekliyor | Freeze, breakdown, hot order ve yeniden çizelgeleme çekirdeği var | Başlama/kısmi tamamlama/kesinti/devam/hurda/rework semantiği ve proses uzmanı kabulü; fiziksel gerekiyorsa operatör, kalıp/aparat ve WIP kısıtları |
| G7 İşletilebilirlik | Çalışılıyor | `/health`, `/ready`, solver metadata ve Docker smoke var; API solver timeout'u `503/SOLVER_TIMEOUT` olarak ayırır; hot-order senaryosu yerelde 30 sn sınırında `UNKNOWN` üretti | Solve p50/p95, timeout/infeasible/fallback, hata, stale ACTIVE ve actuals gecikmesi metrikleri; alarm/runbook/yük testi; ölçüm gerektirirse iş kuyruğu |
| G8 Çevrimdışı kabul | Bekliyor | Sentetik benchmark ve forecast backtest var; G8-T'de OR-Library `ft06` sabit JSP alt kümesi üretim CP-SAT ile bellekte çözüldü ve bağımsız denetimden geçti; [kapsam/kanıt](external-jsp-benchmark.md) | Daha geniş eşit kısıtlı kıyas; gerçek veriyle rolling-origin tahmin, fabrika planı ve bağımsız maliyet uzlaştırması, G1 KPI kabulü |
| G9 Gölge pilot | Bekliyor | Öneri ve audit altyapısının bir kısmı var | 4-8 haftalık aday gözlem penceresinde veri snapshot'ı → mevcut plan → öneri → insan kararı → uygulanmış plan → actuals zinciri; yeterli temsil edici döngü ve planlamacı kabulü |
| G10 Kontrollü üretim | Bekliyor | Fail-safe ACTIVE koruma ve Docker restart testi var | G9 kabulü, sınırlı hat/ufuk, insan onayı, manuel işletim ve rollback, destek düzeni, ölçülmüş RTO/RPO/DR tatbikatı |
| G11 Ekonomik kabul | Bekliyor | Varsayımsal business-case hesaplayıcısı var; varsayılan gerçekleşme oranı sıfır | Yalnız uygulanmış kararların actuals'ı, finans maliyet mutabakatı, hacim/karma etkisi ve ek işletme/deployment maliyetleri; net gerçekleşmiş fayda |
| G12 Ürünleşme | Bekliyor | Tek tesis POC mimarisi ve kurulum dokümanı var | G10-G11 kabulü, connector/konfigürasyon standardı, upgrade/migration, ikinci tesisin aynı çekirdekle kurulum kanıtı ve destek maliyeti |
| G13 İleri otonomi | Bekliyor | Kapsam dışı tutuluyor | Ayrı iş gerekçesi, risk sınırı, insan müdahalesi, geri dönüş ve fabrika/IT-OT kabulü |

Bu matris teknik uygunluk taramasıdır; tablo satırındaki "mevcut" ifadesi kapı kabulü anlamına gelmez. Pilot verisi ve vendor testleri gelmeden G1, G4, G5, G8, G9 veya G11 kapatılamaz. G1-T/G4-T/G5-T/G6-T/G8-T etiketindeki **T**, yalnız laboratuvar kanıtıdır.

## v1.1 teknik hazırlık kolu ve ilk müşteri yolu

| Paket | Şimdi üretilecek kanıt | Saha kapısından farkı |
|---|---|---|
| G1-T | `docs/reference-pilot-profile.md` içinde belgeli referans üretim profili, veri envanteri, varsayımlar ve kapsam dışı alanlar | Fabrika KPI ve onayı yoktur; G1 geçmez |
| G3 | Repository/migration, eşzamanlı ACTIVE, PostgreSQL ve temel backup/restore testleri | Pilot yükü ve IT kurtarma kabulü daha sonra gerekir |
| G4-T | `pilot_preflight` ve `examples/pilot-package/` ile etiketli sentetik kanonik CSV'de profil, reject ve provenance başlangıcı var. [Açık ambalaj verisinin](open-packaging-data-profile.md) altı Excel dosyası hash/alan/tekrar/zaman ekseni yönünden incelendi; müşteri sütun eşlemesi, kabul edilmiş Excel dönüşümü ve solver aktarımı açık | Gerçek müşteri veri seti yerine geçmez |
| G5-T | Yerel dosya/test servisiyle B2MML mesaj, tekrar, geç ve sırasız olay davranışı | Vendor endpoint business acceptance yerine geçmez |
| G6-T | Küçük elle doğrulanabilir kesinti/devam, kalan miktar, hurda, rework ve freeze örnekleri | Fabrika proses uzmanı onayı yerine geçmez |
| G7 | Referans yükte solve süresi, hata, ACTIVE yaşı ve kurtarma gözlemi | Saha SLO ve operasyon ekibi kabulü ayrıca ölçülür |
| G8-T | OR benchmark, olay replay ve ayrı kaynaklara bağlı maliyet/fizik kıyası | Gerçek planner baseline ve müşteri forecast kabulü yerine geçmez |

İlk müşteri teklifi canlı ERP/MES bağlantısı gerektirmeyen, tek hat/ürün ailesi için **okuma amaçlı CSV/Excel dosya pilotu** olabilir. Minimum girdi: sipariş/lot, miktar, due date, operasyon sırası/süresi, uygun makineler, vardiya/duruş, mevcut plan ve mümkünse actuals. G4-T ön incelemesi kanonik CSV paketinde bu alanları yapısal olarak kontrol eder; müşteri sütun eşlemesi, Excel ve solver'a aktarım henüz yoktur. BOM/stok yoksa MRP; yeterli talep geçmişi yoksa forecast iddiası kapsam dışı kalır. FDI üretim sistemine yazmaz. Bu yol G4/G8 saha kanıtına yardımcı olabilir, G5 vendor kabulünü tek başına sağlamaz.

Veri kaynağı türü her kayıt için **gerçek müşteri / açık benchmark / etiketli sentetik** olarak tutulur; lisans/kullanım koşulu, sürüm, hash, zaman aralığı, alan kapsamı ve dönüşüm varsayımları kaydedilir. OR-Library Job Shop yalnız çizelgeleme örnekleri için, NIST SMS Test Bed üretim/tezgâh olayları için adaydır; hiçbirinden eksiksiz sipariş-BOM-routing-talep veya ROI verisi varsayılmaz. Kaynaklar hayalî tek bir gerçek fabrika olarak birleştirilmez.

## İlk mühendislik dilimleri

1. **G0 kanıt paketi:** merge/CI/artifact soy ağacını sabitle; Windows temiz kurulum kusurunu kapat; aynı commit üzerinde tam test ve restart kanıtını kaydet; release etiketi ve image/artifact üretim kararını ver. Eski test sayıları yeni commit'e taşınmaz.
2. **G1-T referans profil ve G1 karar şablonu:** mevcut etiketli fixture için tek hat/ürün ailesi varsayımları, veri kaynakları, plan ufku ve eksik actuals açıkça kaydedilir. KPI pay/payda/dönem/sahibi, freeze, onay/geri dönüş ve veri saklama alanları fabrika onayı gelene kadar taslak kalır.
3. **G2 güvenlik kabuğu:** kritik API ve dashboard işlemleri envanteri, rol matrisi, kimlik sağlayıcı entegrasyon tasarımı, yetkisiz mutation = 0 negatif testleri, audit bütünlüğü. JWT biçimi tek başına yetki sistemi değildir.
4. **G4-T veri onboarding:** etiketli sentetik ve uygun açık örneklerde sipariş/lot/ürün/makine kimlikleri, BOM/routing, süre/setup, vardiya, stok/tedarik, zaman dilimi ve birim sözleşmesi sınanır. Eksik referans, döngü, duplicate, negatif/nonfinite ve geç olay ayrı reject gerekçesiyle raporlanır; gerçek müşteri G4 kanıtı daha sonra alınır.
5. **G7 asgari gözlem:** health/readiness'e ek olarak solver durumu/süresi, yayınlanan ACTIVE yaşı, veri gecikmesi ve hata nedenini görünür kıl; G1 hedefi gelince alarm eşiği koy.
6. **G3/G5-T/G6-T tasarım:** repository/restore ve eşzamanlı yayın sınırını, yerel mesaj round-trip/duplicate davranışını ve küçük elle doğrulanabilir execution state senaryolarını netleştir. Müşteri süreç ve vendor profili geldiğinde saha uyarlaması yapılır. Celery/Redis, multi-tenancy, Kubernetes ve OT bağlantısı varsayılan zorunluluk değildir.

## Ortak kabul ve ölçüm kuralları

- Her KPI için dönem, kapsam, pay/payda, sorumlu ve kaynak run kimliği kaydedilir. Sayısal eşikler G1'de fabrika ile kararlaştırılır.
- Yetkisiz kritik mutation ve hard-constraint ihlali kabul edilen planlarda sıfır olmalıdır. Solver sonuç bulamazsa doğrulanmamış plan ACTIVE yayımlanmaz; `FEASIBLE`, `OPTIMAL` diye raporlanmaz.
- Forecast, eğitim döneminden sonraki veriyle rolling-origin/out-of-time ölçülür; SKU/aile WAPE ve bias basit baseline ile kıyaslanır. Seyrek/sıfır talepte WAPE sınırı belirtilir.
- Fabrikanın fiilî planı ana çizelgeleme baseline'ıdır. Aynı planlama anındaki bilgi, kaynak, sipariş ve ufuk kullanılır. FIFO/EDD/SPT yardımcı referanstır.
- Gölge modda FDI üretim talimatı göndermez. Kabul/ret/override gerekçesi, uygulanmış plan ve actuals ayrı kaydedilir. Potansiyel fayda ile gerçekleşmiş nakit fayda karışmaz.
- Ekonomik fayda: onaylı gerçekleşen brüt fayda eksi ek uygulama/işletme maliyeti. Fazla mesai, enerji, setup, gecikme, WIP ve karbon etkileri muhasebe/ölçüm kaynağıyla ayrı uzlaştırılır; pozitif ROI varsayılmaz.
- Kısmi üretim, kesinti, devam, hurda ve rework için miktar bir kez sayılır. Başlamış işin taşınması, setup korunumu ve rework rotası fabrika kuralına bağlıdır; yalnız downtime eklemek interruption desteği değildir.
- Gerçek veri kalıcı alınmadan temel backup ve restore çalışmalıdır; kontrollü üretimden önce RTO/RPO ve manuel geri dönüş denenmelidir.

## Değerlendirme için ek öneriler

1. **Kanıt envanterini makinece okunur hale getirme:** G0-G13 ve T paketleri için durum, kaynak hash'i, run/commit, veri türü, tarih, sahibi ve geçersiz kılınma nedenini tek kayıt biçiminde tutmak. Böylece kod veya veri değiştiğinde eski kabulün yanlışlıkla yeni sürüme taşınması önlenir. Mevcut run manifestleriyle ilişkilendirilir; ikinci bir gerçeklik kaynağı oluşturulmaz.
2. **Dosya pilotu için veri paketi:** Örnek sipariş/operasyon/makine/mevcut plan/actuals dosyaları, alan-birim-zaman dilimi sözleşmesi, anonimleştirme ve silme kuralı, kabul/reject raporu birlikte hazırlanır. ERP/MES bağlantısı veya tüm LP-MRP-forecast kapsamı ilk değerlendirmeye zorlanmaz.
3. **G3 sırasını pilot tipine göre ayarlama:** Tek kullanıcılı, çevrimdışı dosya pilotunda önce repository sınırı, yedek/restore ve run izolasyonu; PostgreSQL'e geçişi eşzamanlı kullanım veya pilot IT mimarisiyle somutlaştırma. Bu, PDF v1.1'in G3 teknik hazırlığını kaldırma önerisi değil, tam migration yatırımının zamanını açık bir karar olarak ele alma önerisidir.
4. **G7'de doğruluk ve süreyi ayrı kabul etme:** Hot-order örneği 30 sn sınırında `UNKNOWN`, daha uzun doğruluk testinde çözüm üretebildi. SLO belirlenene kadar timeout/fallback oranı ve yük zarfı ayrıca raporlanır; süreyi artırarak başarısızlık görünmez yapılmaz. Çözüm bulunmazsa önceki ACTIVE korunur.

## Açık dış girdiler ve karar sahipleri

1. Pilot fabrika, hat, ürün ailesi, planlama sahibi ve kabul verecek kişiler (şu anda pilot fabrika yok).
2. ERP/MES vendor'ı, test tenant/endpoint, transport ve actuals kaynağı (şu anda test erişimi yok).
3. Gerçek verinin zaman aralığı, hacmi, kalite sorumlusu, birimler ve kimlik eşlemeleri (şu anda temsilî müşteri verisi yok).
4. Planlama ufku/çevrimi, freeze kuralı, solve hizmet hedefi, vardiya/bakım/ikincil kaynak ve kesinti politikası.
5. Kimlik sağlayıcı, rol atamaları, deployment ağı ve secrets yönetimi.
6. Backup/restore hedefi, saha destek sorumlusu, finans ölçüm dönemi ve maliyet yöntemi.

Bu bilgiler yokken teknik hazırlık yapılır; varsayımla müşteri kabulü yazılmaz. PDF'deki 95-188 mühendis-gün, kaynak rapor satırlarının aritmetik toplamıdır; tam program bütçesi ya da tek kişi için 3-6 aylık taahhüt değildir.
