# G4-T: açık esnek ambalaj veri kümesi profili

## Kaynak ve denetim sınırı

[Mendeley Data, *Data for Flexible Packaging Scheduling*, sürüm 1](https://data.mendeley.com/datasets/h66hb89k6z/1), DOI `10.17632/h66hb89k6z.1`, CC BY 4.0. Altı özgün `.xlsx` dosyası 8 Ekim 2026'da yayıncının `public-api/datasets/h66hb89k6z/files?folder_id=root&version=1` listelemesindeki bağlantılardan geçici alana indirildi. İndirilen her dosyanın SHA-256 değeri, aynı API'nin bildirdiği değerle eşleşti. Dosyalar depoya alınmadı; aşağıdaki sayılar yalnız **açık veri profilidir**, müşteri verisi veya fabrika kabul kanıtı değildir.

| Dosya | SHA-256 | Asıl sayfadaki veri satırı |
|---|---|---:|
| `1-Machine.xlsx` | `04a8da3eb1f141d79ef47255e61c6b7b1d5eb332f75c697c9251fa8ac495fd21` | 15 |
| `2-Process.xlsx` | `f8a245e79e08972ced47945083ed54fd042dc4ab866603cd471b70630a59fd65` | 6 |
| `3-Routing.xlsx` | `6a35e5542d33291ef4ce3ad3888302494db50991fc46e91cd5d824cec6e8466b` | 7 |
| `4-Width.xlsx` | `da5f863ea3d67123df380c7771cc0392cf3593e466cb1254dbf26435e6b8bbbe` | 7 (`4-Width` sayfası) |
| `5-Product Type.xlsx` | `4b5605688d6f3f95126095469e947fa834c90a257ac043810a91fda8830ab9fd` | 26 |
| `6-Data Order.xlsx` | `2014698a7cf567f24fb630bd8e23dab30c92b586dee1ff65803d7473a0f9420b` | 59 |

`4-Width.xlsx` içinde diğer beş dosyanın aynı adlı sayfaları da var. Bu beş sayfanın **hücre değerleri** ayrı dosyalarındaki sayfalarla aynı çıktı; `4-Width` asıl sayfası yedi genişlik kaydı içeriyor. İçe aktarımda altı dosyadaki tüm sayfaları birleştirmek 15 makineyi, 59 siparişi vb. iki kere sayar. Her tablo yalnız kendi adlı asıl sayfasından okunmalı; gömülü kopyalar ayrıca doğrulama amacıyla kullanılabilir.

## Alan anlamı ve bağlantılar

| Kaynak alanı | Doğrulanan anlam / güvenli dönüşüm | Açık karar |
|---|---|---|
| `Machine.Code` (`M1`–`M15`) | Makine kimliği; `MinSpeed`, `Ratio Speed`, `SetupTime`, ilk üç makinede `Color` var | Hızın ve setup süresinin birimi, setup'ın ürün/makine geçiş kuralı, renk kapasitesi doğrulanmalı |
| `Process.Code`, `Routing.Routing` | `P1`, `P2`, `P2b`, `P3`, `P4`, `P5` kodlarından sıralı rota dizisi | Proses → uygun makine eşlemesi açık bir tabloda verilmemiş; makine adından sessiz eşleme yapılmaz |
| `Width.No`, `Width.Lebar Bahan` | 1–7 genişlik kodu fiziksel 1000–1210 değerlerine bağlanıyor; ürün tipindeki `Lebar Bahan` alanı bu **koda** işaret ediyor | Fiziksel genişliğin birimi ve makine uyumluluğu kuralı doğrulanmalı |
| `Product Type.No`, `Routing`, `Jumlah Warna` | 26 ürün tipi rota ve genişlik kodlarına bağlı | Ürün rengi ile makine `Color` alanının karşılaştırma kuralı doğrulanmalı |
| `Data Order.No`, `Tipe Produk`, `Running Meter`, `Prioritas` | 59 siparişin ürün tipi referansları mevcut; miktar koşullu olarak running metre cinsinden okunabilir | Öncelik sırası/yüksek değerin anlamı ve miktar birimi sahibiyle doğrulanmalı |
| `InDate`, `Deadline`, `Day`, `Due Dates` | 59/59 satırda `Day = Deadline − InDate` takvim günü ve `Due Dates = Day × 1440`; tarih hücreleri saat 00:00, saat dilimi yok | `Due Dates` **siparişe göre göreli süre**, ortak zaman ekseninde mutlak teslim dakikası değil. Ortak başlangıç, saat dilimi ve release zamanı seçilmeden doğrudan solver'a verilmez |

Tüm 59 sipariş ürün tipi kimlikleri mevcut 26 ürün tipinde, ürünlerin rota kimlikleri yedi rotada, genişlik kimlikleri yedi genişlik kodunda bulundu. İncelenen sekiz sipariş sütununda boş hücre yok. Bu **referans bütünlüğü** kontrolüdür; gerçek üretilebilirlik veya plan kalitesi doğrulaması değildir. `Due Dates` sütunundaki değerler Excel formülü değil, saklı sayılardır; eşitlik ayrıca yeniden hesaplanarak denetlendi.

## FDI'ye alma kararı

Bu kaynak, G4-T'de **alan sözlüğü ve kontrollü dönüşüm provası** için uygundur. Şu an üretim CP-SAT motoruna tüm veri kümesini özgün esnek iş çizelgeleme problemi olarak vermek uygun değildir: FDI rotası her ürün/operasyon için tek `machine_id` gerektiriyor, kaynak ise prose açık makine seçeneklerini ve hız temelli süreleri tekil görev süresi olarak sağlamıyor. Alternatif makine seçimini veya birim/süre kuralını tahmin edip ardından çözüm üretmek, veri kaynağının tanımlamadığı farklı bir problem olur.

Kaynakta fabrika vardiyası, duruşlar, malzeme/BOM ve stok, uygulanmış mevcut plan, operasyon actuals, gerçekleşmiş maliyet veya finans mutabakatı yok. Bu nedenle 59 sipariş için FDI'nin teslim başarısı, tasarruf veya ROI iddiası üretilemez. Veri kümesinin açıklaması dinamik çizelgeleme araştırması için kullanım önerir; mevcut dosyaları incelemek tek başına olay geçmişi veya sahadaki dinamik davranışın gözlendiğini kanıtlamaz.

Sonraki teknik adım, bu alanlar için **kaynak / hesaplanmış / varsayım** etiketi taşıyan ve açık eşleme olmadan eksik alanı reddeden salt okunur dönüşüm taslağıdır. Önce proses-makine uyumluluğu, hız ve setup birimi, zaman ekseni ve ürün genişliği/renk kısıtları tanımlanmalıdır. Sabit makineye önceden atama yapılırsa çıktı ayrı bir *projeksiyon* olarak adlandırılmalı; özgün esnek problemle veya müşteri performansıyla eşdeğer gösterilmemelidir.
