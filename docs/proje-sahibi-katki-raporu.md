# FDI proje sahibi için katkı ve karar raporu

**Tarih:** 8 Ekim 2026
**Dayanak:** `FDI_Nihai_Birlesik_Yol_Haritasi.pdf` v1.1 (SHA-256 `21bc94922174c9f8d72e5d26aab23373009d3474781f7f72727556b38c2b865a`) ve `FDI_Saha_Erisimi_Bilimsel_Degerlendirme.pdf` v1.0 (SHA-256 `0e5f974d2b9c214cfcf7f4ff02db39c31de345041c24aee69e7289d6a5065a58`). Bu rapor [G0–G13 uygulama kaydını](fdi-roadmap-execution.md) kullanıcı açısından somutlaştırır; yeni bir kapsam veya kabul kararı oluşturmaz.

## Kısa durum

[PR #2](https://github.com/AliUmutKazak/factory-decision-intelligence/pull/2) ve [PR #3](https://github.com/AliUmutKazak/factory-decision-intelligence/pull/3) `main` dalına birleşti. Referans veri ve sentetik pilot paketi, bağımsız çizelge denetimi, sabit makineli dış benchmark, açık ambalaj verisi profili ve çevrimdışı yedek/geri yükleme provaları var. Bunlar **laboratuvar teknik kanıtlarıdır**. G0 sürüm kabulü; G1 gerçek pilot sözleşmesi; G4–G8 saha kabulü ve G9–G11 gerçek uygulama/fayda ölçümü henüz tamamlanmadı.

Proje **fabrika beklerken durmuyor**. Kod, test, veri sözleşmesi, güvenlik sınırı, işletim gözlemi ve kontrollü açık veri kıyasları ilerleyebilir. Fabrika/veri sahibi olmadan gerçek plan karşılaştırması, ERP/MES uyumu, operatör kabulü ve gerçekleşmiş tasarruf kanıtı üretilemez.

**Terimler:** *Kapı (G0–G13)*, geçişi kanıt ve sorumlu kabulüyle yapılan aşamadır; `-T` yalnız teknik/laboratuvar hazırlığıdır. *Mevcut plan (baseline)* fabrikanın o anda kullandığı çizelgedir. *Actuals* üretimde gerçekten başlayan, biten ve değişen işlerdir. *Gölge pilot* FDI önerilerinin incelendiği, üretim sistemine otomatik talimat gönderilmeyen dönemdir.

## Şimdi: fabrika olmadan yapılacaklar

**Benim işim:** Paylaşılabilir teknik POC için temiz kurulum, CI ve Docker kanıtı, mühürlü demo, bağımsız kıyas, güvenlik sınırı, açık veri/sentetik veri etiketleri ve sürüm açıklığını geliştirmek. Bunlar gerçek fabrika verisi gerektirmez; tamamlanan her sonucu commit ve çalıştırılabilir kanıtla ilişkilendireceğim.

**Senden şu an beklenen saha işi yok:** Fabrika bulman, üretim dosyası toplaman, ERP/MES erişimi ayarlaman, pilot KPI eşiği belirlemen veya aşağıdaki görüşme şablonunu doldurman gerekmiyor. Dilersen paylaşım metninin hedef kitleye açık gelip gelmediğini değerlendirebilirsin; bu teknik ilerlemenin ön koşulu değildir.

## Ancak ilgilenen bir tesis olduğunda: saha görüşmesi işleri

**8 Ekim 2026 kararı:** Şu anda fabrika bağlantısı yok. Öncelik, [paylaşım kartındaki](paylasim-hazirlik-karti.md) teknik POC'yi dürüst ve tekrar üretilebilir biçimde yayımlamaktır. Aşağıdaki tablo bugünün görev listesi değil, ilgi geldikten sonraki görüşme sırasıdır.

| Görüşme aşaması | Senden yararlı olacak bilgi/karar | Çıktı | Neden gerekli? |
|---|---|---|---|
| **1 — Paylaşım sonrası ilgi gelirse** | Pilot için konuşabileceğimiz bir tesis veya üretim sorumlusu var mı? Varsa **tek hat / tek ürün ailesi** ve planlama sorumlusunu belirle. | Aday tesis, hat/ürün ailesi, ilgili rol, temas ve izin durumu; `bilinmiyor` kabul edilir. | G1 pilot kapsamı ancak adı belli bir fabrika ve karar sahibiyle kurulabilir. |
| **2 — İlk görüşmede** | Mevcut plan nasıl yapılıyor: Excel, ERP, MES veya başka yöntem? Siparişten tamamlanmaya kadar hangi kayıtlar tutuluyor? | Bir sayfalık süreç özeti ve veri sahibi listesi. | FDI önerisini fabrikanın **fiilî planıyla** eşit koşullarda kıyaslamak için başlangıç noktası gerekir. |
| **3 — Veri sahibiyle** | Salt okunur geçmiş dosya paylaşımı mümkün mü? Önce dosya/alan **envanteri** iste; gerçek kayıtları paylaşmadan önce yetki ve aktarım yöntemi netleşsin. | `var / yok / bilinmiyor` tablosu: sipariş/lot, ürün, rota/operasyon, makine, vardiya/duruş, mevcut plan, operasyon gerçekleşmeleri. | İlk dosya pilotu ERP/MES bağlantısına ihtiyaç duymaz; bu kayıtlar G4/G8 için asgari karşılaştırma sınırını kurar. |
| **4 — Planlamacı/proses uzmanıyla** | Bir operasyon birden çok makinede yapılabilir mi? Hazırlık süresi ürün sırasına mı bağlı? Başlamış iş, kesinti, kısmi tamamlama, hurda ve rework nasıl ele alınıyor? | Her kural için kısa açıklama, bir gerçek örnek ve karar sahibi. | Mevcut üretim rotası operasyon başına **tek makine** tutuyor. Alternatif makine yaygınsa bunu açık tasarım işi olarak planlamalıyız; sessizce eşdeğer sayamayız. |
| **5 — Planlamacı ve finansla** | İlk pilotta başarı ne demek? Teslim zamanı, setup, fazla mesai, WIP, plan değişkenliği ve solve süresi için hangi mevcut plan/gerçekleşme kaynağı var? | KPI başına dönem, kapsam, pay/payda, kaynak ve sorumlu; sayısal hedef daha sonra ortak kararla. | Gösterim raporundaki maliyet ve ROI sayıları müşteri kazanımı değildir. G8/G11 için gerçek baseline ve actuals gerekir. |
| **6 — IT/veri sahibiyle** | Paylaşım izni, anonimleştirme, saklama/silme süresi, kimlik ve rol sahipleri, yedek/kurtarma sorumlusu kim? ERP/MES test erişimi daha sonra açılabilir mi? | Yetki ve veri aktarım kararı; vendor/sürüm ve test ortamı durumu. | G2/G3/G5 saha kabulü ve gerçek veri kullanımı için gerekir; **ilk keşif görüşmesinin ön şartı değildir**. |

Bu satırlarda bütün cevapların bir anda hazır olması beklenmiyor. Her bilinmeyeni açık bırakmak, varsayımla doldurmaktan daha yararlı. Şu an senden fabrika adayı listesi beklenmiyor; ilgi geldiğinde görüşme kapsamını birlikte daraltırız.

**İlgi geldikten sonra araştırma yolu:** İlgilenen ayrık üretim tesisi veya üretim danışmanıyla planlamacı/üretim yöneticisi üzerinden kısa görüşme olasılığını araştır. İlk görüşmede üç şeyi öğrenmek yeterli: plan hangi araçla hazırlanıyor, aynı iş için alternatif makineler var mı, geçmiş plan ve gerçekleşme kayıtları tutuluyor mu? Teknik çözüm veya veri aktarımı sözü vermene gerek yok; çıkan belirsizlikleri bana iletmen tasarımı yönlendirecek.

## Tesis dosya incelemesini kabul ederse: sorulacak veri listesi

| Öncelik | Alanlar | Olmazsa sonuç |
|---|---|---|
| Asgari planlama girdisi | Sipariş/lot kimliği, ürün, miktar ve birim, giriş ve teslim zamanı/saat dilimi; operasyon sırası, süre ve uygun makine; vardiya ve bilinen duruş | Fiziksel çizelge ve teslim değerlendirmesi kurulamaz |
| Adil karşılaştırma | Aynı karar anında mevcut fabrika planı ve o anda bilinen sipariş/kaynak durumu | FDI planına karşı gerçek baseline olmaz |
| Gerçekleşme | Operasyon başlangıç/bitiş, üretilen miktar, kesinti, hurda/rework ve uygulanmış plan | Gölge pilot ve gerçekleşmiş fayda iddiası yapılamaz |
| Kapsama bağlı | BOM, stok, tedarik ve lead time; yeterli tarihsel talep; enerji sayaç ve finans tarifeleri | Eksik ilgili modülün performansı veya nakit etkisi iddia edilmez |

Her dosya için kaynak sahibi, alan açıklaması, kimlik eşlemesi, ölçü birimi, zaman dilimi, tarih aralığı ve paylaşım izni kaydedilir. İlk örnek **salt okunur** incelenir; üretim sistemine plan yazılmaz. Mevcut [kanonik CSV ön kontrol örneği](../examples/pilot-package/README.md) hangi dosyaları isteyeceğimizi somutlaştırır; müşteri Excel'i veya vendor şemasını henüz otomatik kabul etmiyor.

## Benim şimdi ilerleteceğim teknik işler

| Yol haritası | Sorumluluğum | Saha geldiğinde ayrıca gereken |
|---|---|---|
| G0/G2 | Birleşme sonrası CI kanıtı, sürüm açıkları, kritik API için kimlik/rol sınırı ve negatif yetki testleri | Kimlik sağlayıcı, ağ ve rol sahiplerinin IT onayı |
| G3 | Run izolasyonu, mühürlü paket ve geri yükleme doğrulaması; repository/eşzamanlılık sınırlarını geliştirme | Canlı yedek, ACTIVE geri dönüşü, RTO/RPO ve IT tatbikatı |
| G4-T/G5-T | Kaynak/hesaplanan/varsayım etiketli veri eşleme, açık ret nedenleri, yerel dosya/mesaj provası | Yetkili gerçek veri, alan anlamı ve vendor test ortamı |
| G6-T/G7 | Kısmi üretim ve olay semantiği için küçük doğrulanabilir örnekler; solver timeout, ACTIVE yaşı ve veri gecikmesi görünürlüğü | Proses kuralı ve işletim hedeflerinin fabrika kabulü |
| G8-T | Bağımsız fiziksel denetim ve eşit kısıtlı dış benchmark'ları genişletme | Fiilî fabrika planı, actuals, KPI ve finans mutabakatı |

Kod tarafında bir özelliği gerçek fabrikanın desteklediği varsayılmayacak. Özellikle alternatif makine seçimi, hızdan türetilen işlem süresi ve gerçek maliyet, gözlenen veri veya açıkça onaylı kural olmadan ürün kabiliyeti/ROI olarak sunulmayacak.

## İlgilenen bir tesis olduğunda kısa görüşme şablonu

```
1. Olası fabrika veya sektör (yoksa "henüz yok"):
2. Görüşebileceğin rol/kişi (planlama, üretim, IT/MES):
3. İlk pilot için olası tek hat ve ürün ailesi:
4. Mevcut planlama aracı (Excel/ERP/MES/bilinmiyor):
5. Sipariş, rota, makine, vardiya, mevcut plan, actuals dosyaları var mı? (her biri var/yok/bilinmiyor):
6. Alternatif makine veya sıra bağımlı setup var mı? (var/yok/bilinmiyor):
7. Veriyi inceleme izni ve olası paylaşım yöntemi:
8. Başarıyı hangi karar veya ölçüyle görmek isterler?:
```

**En küçük yararlı yanıt:** İlk üç madde. Bugün bunları doldurmana gerek yok; geri kalanı henüz bilinmiyorsa teknik hazırlığa devam edilir. Gerçek müşteri dosyası veya erişim bilgisi için önce veri sahibinin izni ve paylaşım yöntemi belirlenir.

İlk temasta şu kısa çerçeveyi kullanabilirsin: “Üretim planlamasına yönelik bir karar destek prototipi geliştiriyoruz. Tek bir hat veya ürün ailesi için mevcut planlama sürecini ve hangi geçmiş dosyaların bulunduğunu anlamak istiyoruz. İlk görüşmede canlı sistem erişimi veya veri aktarımı istemiyoruz; olası salt okunur değerlendirme ancak sizin kapsam ve paylaşım onayınızla yapılır.”
