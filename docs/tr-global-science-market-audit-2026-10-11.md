# FDI: Türkiye ve dünya bilim, standart ve benzer çözüm denetimi

**Tarih:** 11 Ekim 2026. **Kapsam:** Fabrika sunumundan önce, elimizdeki tek sunuculu laboratuvar POC'sinin bilimsel ve ürünsel sınırlarını denetlemek. Bu kayıt bir sistematik literatür incelemesi veya dünyadaki bütün yayın/ürünlerin eksiksiz dizini değildir. Standart yayımlanmış olması FDI'nin o standarda uygunluk sertifikası aldığı anlamına gelmez; makale yayımlanmış olması FDI yönteminin sahada doğrulandığı anlamına gelmez.

## Tarama ve kanıt kuralı

- Türkiye: Bakanlık ve TÜBİTAK birincil yayınları, üniversite/dergi özgün makaleleri, Türkiye'de geliştirilen ürünlerin kendi teknik sayfaları.
- Dünya: ISO/NIST/GHG Protocol gibi standart sahibi kurumlar, araştırmacıların özgün yayınları, çözücü dokümantasyonu ve üreticilerin kendi özellik sayfaları.
- Ürün özellikleri **üretici beyanı**, akademik sonuçlar **çalışmanın kendi veri/problem kapsamı**, FDI sonucu **deponun test/CI kanıtı** olarak tutulur. Pazarlama yüzdeleri ve örnek vaka tasarrufları FDI'ye taşınmaz.
- Seçim ölçüsü: FDI'nin talep tahmini, kapasite/MRP, sabit makineli çizelgeleme, yeniden çizelgeleme, enerji/karbon, veri sınırı, karar izlenebilirliği veya ilk dosya pilotuyla doğrudan ilişkili olmak. İlk bağlantıya kadar gerçek ERP/MES ve proses kuralları gerektiren özellikler kapsam dışı kalır.

## Standartlar ve kurumsal kaynaklar

| Birincil kaynak | Bu çalışma için anlamı | FDI kararı |
|---|---|---|
| [ISO 22400-2:2014 KPI tanımları](https://www.iso.org/standard/54497.html) | Üretim KPI'sında formül, unsur, zaman davranışı ve birim birlikte tanımlanır; kaynak sayfası revizyon beklendiğini de belirtir. | Demo KPI'sı ile saha KPI'sı ayrılır. Sunumda pay, payda, birim, dönem ve veri kökeni belirtilir; ISO 22400 uygunluğu iddia edilmez. |
| [ISO 23247-1 dijital ikiz çerçevesi](https://www.iso.org/standard/75066.html) ve [NIST doğrulama yaklaşımı](https://www.nist.gov/programs-projects/digital-twins-advanced-manufacturing) | Dijital ikiz, veri senkronizasyonu ve model doğrulaması gerektiren bir çerçevedir. NIST belirsizlik nicelleştirme ve doğrulamayı vurgular. | FDI sentetik simülasyon/karar destek POC'sidir; sahaya bağlı ve doğrulanmış “dijital ikiz” olarak sunulmaz. |
| [ISA-95 genel bakış](https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard) | ERP ile üretim operasyonları arasındaki bilgi alışverişi için ortak terim ve sınır sağlar. | Yerel B2MML/olay sözleşmesi, belirli satıcının ERP/MES birlikte çalışabilirliğini kanıtlamaz. |
| [NIST OT SP 800-82 Rev. 3](https://csrc.nist.gov/pubs/sp/800/82/r3/final) | OT güvenliğine özgü ağ, değişiklik ve işletim sınırları vardır. | Yerel kapalı demo internete/OT ağına açılmaz; canlı bağlantı G2/G5 saha işidir. |
| [GHG Protocol Scope 2 Guidance](https://ghgprotocol.org/sites/default/files/GHG%20Protocol%20Scope%202%20Guidance.pdf) | Şebeke ortalaması esaslı ve sözleşmesel piyasa esaslı muhasebe birbirinden ayrılır. | FDI'nin tek şebeke katsayısı ile hesapladığı Scope 2, **model senaryosu**dur; doğrulanmış kurumsal sera gazı envanteri veya market-based sonuç değildir. CLI etiketi buna göre düzeltildi. |
| [ISO 50001 enerji yönetimi](https://www.iso.org/standard/69426.html) | Enerji performansının sürekli iyileştirilmesi için yönetim sistemi çerçevesidir. | Enerji simülasyonu bu sertifikayı veya fiilî enerji tasarrufunu göstermez. |
| [T.C. Sanayi ve Teknoloji Bakanlığı Model Fabrikalar](https://www.sanayi.gov.tr/merkez-birimi/92d9c73bddbb/model-fabrika/b81236) ve [Öğren-Dönüş çerçevesi](https://www.sanayi.gov.tr/assets/pdf/birimler/SAVGMMFOgrenDonusCerceveDokumani.pdf) | Türkiye'de deneyimsel öğrenme, yalın dönüşüm ve ölçülebilir verimlilik yaklaşımı için kurumsal zemin. | FDI demosunda kullanıcıya “mevcut plan → öneri → insan kararı → gerçekleşme” akışı gösterilir. Model Fabrika programına katılım/akreditasyon iddia edilmez. |
| [TÜBİTAK TEYDEB başarı hikâyeleri](https://www.tubitak.gov.tr/sites/default/files/teydeb_basari_hikayeleri_kitabi.pdf) | Türkiye'de APS geliştiren Yalınas Extended örneği belgelenmiş. | Türkiye'de benzer çözüm yok iddiası yapılmaz; bu tarihsel proje mevcut ürün performans kanıtı olarak da kullanılmaz. |

## Uzmanların yayımladığı yöntemler: bize uygulanabilir karar

Kişilere atfedilen görüşler yalnız aşağıdaki yayınlarda ifade edilen çalışma sonucudur; proje için kişisel onay veya danışmanlık beyanı değildir.

| Araştırmacı/ekip ve özgün kaynak | Yöntem/çıkarım | FDI'ye çeviri |
|---|---|---|
| [Meral Azizoğlu ve Oğuzhan Alagöz, ODTÜ çizelgeleme çalışması](https://avesis.metu.edu.tr/yonetilen-tez/237b889c-015c-420e-808d-310bc0aad932/rescheduling-under-machine-disraptions); [özgün makale](https://www.sciencedirect.com/science/article/pii/S037722170200499X) | Makine arızasından sonra verimlilik ve çizelge kararlılığı birlikte incelenir; uygun makine kümesi önemli kısıttır. | FDI'nin freeze/nervousness ölçümü korunur. Alternatif makine seçimi için açık fabrika kuralı ve veri gerekir; tek makine rotası esnek atölye diye sunulmaz. |
| [Emine Akyol Özer, Sevcan Dincer, Hüseyin Tamer](https://dergipark.org.tr/tr/pub/ogummf/article/763363) | Conta fabrikasında enerji ve ağırlıklı tamamlanma zamanını birlikte ele alan, uygun makine ve yeniden dolaşım içeren iki amaçlı model. | Enerji hedefi tek başına makespan sonucu değildir; FDI'nin enerji katsayıları ve proses rotası müşteri verisi olmadan tasarruf kanıtı olamaz. |
| [Aysel Koçak ve Aytaç Yıldız](https://dergipark.org.tr/tr/pub/gujsc/article/1170021) | Tekstil uygulamasında önce süreç verisi ve işlem süresi tahmini oluşturulup sonra çizelgeleme tasarlanır. | Pilot verisi geldiğinde standart süreyi otomatik doğru kabul etmek yerine ölçüm, dönem ve hataya göre doğrulama gerekir. |
| [Sena Aydoğan Baş ve Şafak Kocakalay](https://dergipark.org.tr/tr/pub/gazimmfd/article/1825212) | Bakım, yeni iş ve termin değişikliği ile yeniden çizelgeleme birlikte modellenir. | FDI'nin sentetik olay matrisi yararlıdır; fakat saha bakım takvimi ve gerçek müdahale süresi olmadan kabul edilmiş çizelge değildir. |
| [Michael L. Pinedo](https://archive.nyu.edu/handle/2451/14183); [ders kitabı](https://link.springer.com/book/10.1007/978-3-031-05921-6) | Çizelgeleme modelini, algoritmaları, sistem tasarımını ve kullanıcı arayüzünü ayrı düşünür. | Çözücü kalitesi, sistem güvenilirliği ve planlamacı kararı ayrı kanıtlanır; tek benchmark tüm ürünün kalitesi değildir. |
| [Jeffrey W. Herrmann](https://isr.umd.edu/Labs/CIM/projects/mista2005/mista2005.html) | Üretim çizelgelemesi bilgi toplama, insan kararı ve yayım işidir; araçlar karar vericinin yerini otomatik almaz. | Sunumun merkezinde denetlenebilir öneri, neden, kabul/ret ve insan onayı bulunur. |
| [Rob J. Hyndman ve Anne B. Koehler](https://otext.robjhyndman.com/publications/another-look-at-measures-of-forecast-accuracy/); [rolling-origin yöntemi](https://otexts.robjhyndman.com/fpp3/tscv.html) | Tahmin hatası metriği sıfır/seyrek talepte dikkatle seçilir; eğitim verisinden sonraki ufuklarla test yapılır. | FDI sıfır talep ufkunda WAPE'yi artık sıfır başarı diye yazmaz; RMSE ile seçim yapar. Çok adımlı rolling-origin korunur. Gerçek veriyle dış test hâlâ açık. |
| [Global yeniden çizelgeleme özgün çalışması](https://www.sciencedirect.com/science/article/pii/S0360835203000950) | Verimlilik ile başlangıç zamanı değişimi/kararlılık beraber ele alınır. | FDI'de yalnız daha kısa makespan değil, mevcut plana etkisi de gösterilir. Ağırlıklar fabrika ile belirlenir. |

## Benzer çözümler: gerçek kapsam ve FDI boşluğu

Bu tablo fonksiyon ve kanıt farkını gösterir; lisans, fiyat, hız, ürün kalitesi veya müşteri faydası sıralaması değildir. Satıcı sayfaları bağımsız deney değildir.

| Çözüm ve üretici kanıtı | Belgelenen yetenek | FDI konumu / alınacak ders |
|---|---|---|
| [Logo Netsis 3 Enterprise APS](https://cdn.logo.com.tr/files/logocomtr/Uploads/Documents/logo-netsis-3-enterprise-tan%C4%B1t%C4%B1m-bro%C5%9F%C3%BCr%C3%BC-tr.pdf) | Alternatif rota, operasyon/makine ve kaynak kuralları, setup, Gantt, plan sabitleyip yeniden çizelgeleme. | Türkiye'deki doğrudan APS örneği. FDI'nin sabit rotası ve dar dosya pilotu açıkça belirtilmeli. |
| [Arge Bilişim AI-APS](https://argebilisim.com/yapay-zeka-ileri-planlama-cizelgeleme) | Ürün-hat uygunluğu, gerçekleşen performans/kalite, setup ve olay sonrası yeniden optimizasyon beyanı. | Gerçekleşen saha verisiyle öğrenme FDI'de bugün yok; sentetik veride buna denk iddia kurmuyoruz. |
| [TÜBİTAK kaydındaki Yalınas Extended](https://www.tubitak.gov.tr/sites/default/files/teydeb_basari_hikayeleri_kitabi.pdf) | Yerli ileri planlama/çizelgeleme Ar-Ge örneği. | Önceki teknik çalışma olarak anılır; güncel pazar payı/performans çıkarımı yapılmaz. |
| [Siemens Opcenter APS](https://www.siemens.com/en-us/products/opcenter/advanced-planning-scheduling-aps/advanced-scheduling-software/) | Çok kısıtlı sonlu kapasite, alternatif kaynak hızı, sıra bağımlı setup, malzeme ve plan/gerçekleşme görüntüleme. | FDI bunun kurumsal kapsamını taşımıyor. Öncelik, desteklediğimiz dar kısıtı doğru ispatlamak ve farkı görünür kılmak. |
| [Dassault DELMIA Ortems](https://www.3ds.com/products/delmia/ortems) | Talep, malzeme, iş gücü ve ERP/MES ile geniş planlama; vendor bunu “virtual twin” olarak tanımlar. | Veri senkronizasyonu ve dijital ikiz iddiası FDI için erken. |
| [Asprova APS Türkiye temsilcisi](https://www.teknosol-aps.com/) | Geniş modelleme, hızlı çizelgeleme ve entegrasyon beyanları. | Sayfadaki süre/ölçek sayılarını FDI benchmark'ına karşı koymak adil değil; aynı problem/veri/kısıt yok. |
| [PyJobShop](https://pyjobshop.org/stable/) | Açık kaynak çizelgeleme kitaplığı, FJSP ve çoklu kaynak ortamları. | FDI'nin tek makine rotası genel FJSP değildir. Paylaşımda teknik kapsam farkı yazılır. |
| [Timefold Task Scheduling](https://docs.timefold.ai/job-scheduling/latest/user-guide/use-cases) | Makine/operatör, değişim süresi, ortak takım ve olayda yeniden planlama dokümantasyonu. | FDI'de bu kısıtların hepsi yok; ileride saha kuralı gerektiren ihtiyaç havuzu olarak tutulur. |

## Açıklar, bu turdaki değişiklik ve karar

| Öncelik | Bulgu | Yapılan / yapılacak karar | Kapı |
|---|---|---|---|
| P0 | Sıfır gerçekleşen talep ufkunda WAPE=0 gösterilmesi yalancı başarıydı. | `train_forecast.py`: WAPE tanımsız (`NULL`) tutulur, böyle bir fold varsa model seçimi tüm foldların RMSE'siyle yapılır; çok kısa seri açıkça reddedilir. Sentetik regresyon testi eklendi. | G8-T |
| P0 | P10/P90 ve safety stock, CV RMSE × normal katsayı ile üretiliyor; ufuk bazlı dağılım ve kapsam/kalibrasyon kanıtı yok. [Tahmin aralığı yöntemi](https://otexts.robjhyndman.com/fpp3/prediction-intervals.html) ve [aralık doğruluğu](https://otexts.robjhyndman.com/fpp3/distaccuracy.html) ayrı değerlendirme ister. | Mevcut alanlar geriye uyumluluk için kaldı; lineage/metadata `normal_rmse_heuristic_uncalibrated` yazar. Sunumda olasılık kapsamı veya servis seviyesi garantisi olarak kullanılmaz. Gerçek veri gelince ampirik coverage ve işletme servis maliyeti doğrulanır. | G8 saha |
| P0 | Karbon CLI'si “kurumsal GHG Protocol” diyordu; Scope 1 forklift tüketimi sentetik varsayım, Scope 2 tek grid katsayısı. | CLI model tabanlı senaryo diye etiketlendi. Ürün demosunda “doğrulanmış karbon envanteri/azaltım” iddiası kaldırılır; dual Scope 2 ve gerçek sayaç/yakıt verisi saha işi. | G4/G11 |
| P1 | KPI tanımında zaman penceresi, pay/payda ve gerçek/baz senaryo bağlamı kolay kaybolur. | [Sunum kanıt paketi](factory-presentation-evidence-pack.md) her gösterilecek sayıya veri sınıfı ve hesap/kabul sınırı koyar. | G1-T/G8-T |
| P1 | Türkiye rakipleri ve yerel özgün araştırma önceki karşılaştırmada yoktu. | Bu tablo ve uzman yöntemi kaydı eklendi; “Türkiye'de ilk/tek”, “rakiplerden iyi” iddiaları kullanılmaz. | Paylaşım |
| P1 | Alternatif makine/operatör/takım ve gerçek süre dağılımı büyük APS'lerde mevcut, FDI'de sınırlı. | Tahminle genel FJSP eklenmez. İlk dosya pilotunun sabit makine/tam sipariş/tek ortak vardiya sınırı korunur; pilot kuralı geldiğinde veri profiline göre seçilir. | G6 saha |
| P2 | ISO 23247 anlamında güncel fiziksel varlığa senkron dijital ikiz yok. | “Dijital ikiz” pazarlama iddiası yerine “laboratuvar karar desteği ve what-if” kullanılır. | Paylaşım |

## Sunum öncesi bitiş ölçüsü

Fabrika olmadan ulaşılabilecek sürüm: aynı commit üzerinde CI/test, tekrar üretilebilir sentetik/açık benchmark, kaynaklı yetenek ve kapsam beyanı, güvenli yerel demo, dosya pilotu için açık kabul/ret kuralı. [Sunum kanıt paketi](factory-presentation-evidence-pack.md) bunu tek görüşmede kullanılacak dile çevirir. Saha kapıları G1, G4–G11 fabrika/veri/yetki olmadan kapatılmaz; bunların açık olması POC'nin paylaşımını durdurmaz.
