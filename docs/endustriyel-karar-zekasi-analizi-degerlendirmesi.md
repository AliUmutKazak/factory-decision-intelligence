# Endüstriyel karar zekâsı araştırması: FDI için karar kaydı

Kaynak: `Endüstriyel Karar Zekası Analizi.pdf`, 13 sayfa; SHA-256 `9b5274aa8a41ba59e41e7224ad03a94587f525a356b5f5fa0d747c40c687c7f8`. Değerlendirme: 8 Ekim 2026. Bu araştırma [birleşik yol haritasına](fdi-roadmap-execution.md) yardımcı fikirler sunar; PDF'deki öneriler G0-G13 kapılarını değiştiren talimat veya fabrika kabulü değildir.

## Karar

**Seçerek kullanalım.** En güçlü katkı, fabrika erişimi gelmeden çeşitli ve kaynak kimliği belli sentetik olaylarla planlama kararlarını zorlamak; sonucu bağımsız uygunluk kontrolüyle ve açık kapsam etiketiyle kaydetmektir. Bu, mevcut G7/G8-T teknik hazırlığına doğrudan uyar. İlk uygulama [G7 sentetik acil sipariş matrisi](g7-hot-order-stress-matrix.md) oldu.

Raporun canlı OT/UNS omurgası, OEE, aktif-periyot darboğazı, Kingman VUT, nedensel kök neden analizi ve dijital ikiz önerileri **bugünkü FDI yetenekleri değildir**. Mevcut çekirdek tahmin → LP → MRP → sabit makineli CP-SAT → insan denetimli senaryo/yeniden çizelgeleme zinciridir. LP'nin bağlayıcı kapasite kısıtı ve gölge fiyatı, akış hattının gerçek zamanlı debi darboğazıyla aynı ölçü değildir. Veri ve süreç varsayımları oluşmadan bu yöntemleri ürün özelliği gibi eklemek projenin amacını bulanıklaştırır.

## İddia ve kaynak denetimi

| Rapordaki öneri / ifade | Değerlendirme | FDI kararı |
|---|---|---|
| Sentetik hat ve arıza verileriyle fabrika öncesi geliştirme | Uygun. [NIST'in araştırması](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=921398) sentetik veriyi durum ve hata sınaması için yararlı bulur; gerçek dünyaya uygulanabilirliğin gerçek üretim verisiyle ayrıca gösterilmesini ister. [Lopes ve ark. (2024)](https://doi.org/10.1080/0951192X.2024.2322981) parametrik yapay üretim hatlarıyla yöntem araştırır. | Etiketli küçük stres matrisi, kaynak/parametre/hash/solver durumu/bağımsız denetim kanıtı. Gerçek saha doğrulaması, SLO veya ROI iddiası yok. |
| Little Yasası ve Kingman VUT | Little Yasası ancak kapsam ve kararlı dönem tanımlandığında ölçüleri ilişkilendirir. Rapordaki Kingman ifadesinde `u/(1-u)` terimi `u→1` yakınında **hiperbolik** büyür; "üstel patlama" doğru matematiksel adlandırma değildir. VUT, durağan tek istasyon kuyruğu için yaklaşımdır; geliş/işlem değişkenliği ölçülmeden FDI çizelgesinden güvenilir WIP reçetesi çıkarılamaz. | Gelecekte ölçüm/simülasyon tanısı olabilir; mevcut LP/CP-SAT karar motoruna doğrudan hedef fonksiyonu olarak eklenmez. |
| Roser aktif periyot, Li dönüm noktası ve benzeri darboğaz yöntemleri | [Su ve ark. (2022)](https://doi.org/10.3390/app12094195) ince taneli makine durumları ve tamponları kullanır. Yöntemler makine aktif/bloke/aç durumlarının zaman serisini veya seri hat varsayımını ister. FDI'nin sentetik, çok operasyonlu sabit makineli örneği bu telemetriyi sağlamıyor. | G5/G6 actuals ve durum semantiği gelince ayrı laboratuvar karşılaştırması; bugün mevcut "dinamik darboğaz" özelliği diye sunulmaz. |
| DoWhy/SCM ile nedensel kök neden | Müdahale, sonuç, karıştırıcılar ve alan bilgisi olmadan korelasyondan nedensel etki çıkmaz. Raporun önerdiği sıcaklık/arıza türü veri ve müdahale geçmişi projede yok. | G13'ün ayrı yatırım/kanıt kararı; şimdilik kapsam dışı. |
| SimPy dijital ikiz ve "sim-to-real garantisi" | Simülasyon, kural ve uç durumları sınar; gerçek tesis davranışına geçişi garanti etmez. [Lopes ve ark.](https://doi.org/10.1080/0951192X.2024.2322981) de sentetik veriyle araştırmayı ve gerçek veriyle model kalibrasyonunu ayrı anlatır. | İhtiyaç doğarsa dar kapsamlı olay simülasyonu; canlı fabrika ikizi veya otomatik karar uygulaması iddiası yok. |
| ODCS, OpenLineage, Great Expectations/Pandera zorunluluğu | [ODCS](https://bitol-io.github.io/open-data-contract-standard/v3.0.1/) ve [OpenLineage](https://openlineage.io/docs/spec/object-model/) yararlı değişim biçimleri sunar. Her aracı kurmak güvenilirlik garantisi vermez. FDI'de kaynak etiketi, hash, run soyağacı, CSV ön kontrolü ve B2MML profili zaten vardır; saha entegrasyon ihtiyacı ayrıca belirlenir. | Önce mevcut kanıt alanlarını eksiksiz tut; dış tüketici varsa standart eşlemesini incele. Yeni servis/bağımlılık varsayılan değil. |
| UMH / Factory+ karşısında kanıtlanmış üstünlük | [Factory+](https://factoryplus.app.amrc.co.uk/docs/overview) öncelikle bağlantı/normalleştirme çerçevesini, [UMH](https://www.umh.app/) veri bağlantısı ve dağıtımını anlatır; FDI'nin odak farkı planlama/karar katmanıdır. Belgelenmiş ortak veri, metrik ve kabul olmadan performans ya da ticari üstünlük karşılaştırması yapılamaz. | Konumlandırmada amaç ve kapsam farkını anlat; "kanıtlanmış üstünlük" veya rakipte özellik yok iddiası kullanma. |

Raporun kaynak listesi hakemli çalışmalar, resmî standartlar, bloglar, pazarlama ve üçüncü taraf yorumları karıştırıyor. Özellikle "10.000 sanal vardiya", "anlık ve hatasız darboğaz", "sıfır kirli veri" ve "sim-to-real garantisi" ifadelerinin FDI için ölçümü yoktur. Sentetik örnekler bu ifadeleri doğrulamış sayılmaz.

## Yol haritasına bağlanan işler

1. **Şimdi — G7/G8-T:** Tek acil siparişin beş tekrarını farklı miktar/ürün/termin örneklerine genişlet. Her adayın solver sonucunu bağımsız çekirdek fizik denetimiyle eşleştir; başarısızlıkları ve kaynak hash'ini koru. Ayrı [ölçüm kaydı](g7-hot-order-stress-matrix.md) kapsamı gösterir.
2. **Sonraki veri işi — G4-T/G5-T:** Mevcut dosya pilotu manifestindeki kaynak türü, birim, zaman başlangıcı, sahip ve hash alanlarını koru. ODCS alan eşlemesini ancak müşteri/veri sağlayıcı arayüzü somutlaştığında yap. Eksik/sırasız olay reddini yerel testte genişlet.
3. **Saha verisi gerektiğinde — G6/G8:** Makine durumları ve actuals elde edilirse aktif-periyot darboğazı ile mevcut LP kapasite sinyalini farklı amaçları koruyarak kıyasla. Kingman için gözlenen geliş/işlem değişkenliği, kararlı dönem ve kullanım koşulunu açıkla.
4. **Ayrı karar — G13:** Nedensel müdahale modelleri, tam dijital ikiz, otomatik OT komutu veya mikroservis/UNS altyapısı mevcut teknik POC'nin ön koşulu değildir.

Fabrika bağlantısının son aşama olması kararı korunur. Sentetik teknik kanıt, gerçek müşteri verisi, planlamacı kabulü ve gerçekleşmiş ekonomik fayda yerine geçmez.
