# Acil sipariş: aday bulma süresi ve plan kararlılığı

**25 Ekim 2026 — keşif amaçlı laboratuvar deneyi.** Kaynak, mühürlü sentetik `RUN-20261006-00a0d3` çizelgesidir. Kod commit'i `ebc48d65c6a023b6297bb4c2985f559f3be419e1`; altı [önceden tanımlı vaka](../examples/g7-hot-order-expanded-cases.json), tek worker ve her yöntem için aynı çözücü sınırı kullanıldı. 2 saniyelik [180 denemenin ham kaydı](../artifacts/research/g7-hot-order-stability-2026-10-25.json) beş tohumu; 10 saniyelik [108 denemenin ham kaydı](../artifacts/research/g7-hot-order-stability-10s-2026-10-25.json) ilk üç tohumu içerir. Her denemede vaka, tohum, yöntem, bağımsız fizik denetimi ve hata; rapor üst bilgisinde kaynak ve kod hash'leri bulunur. Süreler Windows Python 3.14.7 ve OR-Tools 9.15.6755 ortamında ölçüldü.

Bu kodda transfer alt lotlarının FIFO öncüllüğü yalnız **aynı ana siparişe** uygulanır. Önceki ürün-geneli kural, ayrı acil siparişi eski siparişin alt lot zincirine bağlayabiliyordu. Dolayısıyla [23 Ekim matrisindeki](decision-review-and-expanded-benchmark-2026-10-23.md) sayılar farklı bir modelin tarihsel sonucudur; aşağıdaki rakamlarla doğrudan yöntem kazanımı olarak çıkarılmaz.

| Çözücü sınırı | Yöntem | Geçerli/deneme | Kabul edilenlerde ortanca ağırlıklı gecikme (dk) | Ortanca değişen eski iş | Tüm denemelerde uçtan uca p95 (sn) |
|---|---|---:|---:|---:|---:|
| 2 sn | FULL | 0/30 | — | — | 2,245 |
| 2 sn | FIFO | 30/30 | 63.944 | 31 | 0,447 |
| 2 sn | EDD | 30/30 | 6.169 | 31 | 0,521 |
| 2 sn | SPT | 30/30 | 12.420 | 31 | 0,477 |
| 2 sn | APPEND | 30/30 | 102.099 | 0 | 0,432 |
| 2 sn | INSERT | 30/30 | 38.296,5 | 6 | 2,256 |
| 10 sn | FULL | 16/18 | 67.736 | 31 | 10,255 |
| 10 sn | FIFO | 18/18 | 63.944 | 31 | 0,490 |
| 10 sn | EDD | 18/18 | 6.169 | 31 | 0,376 |
| 10 sn | SPT | 18/18 | 12.420 | 31 | 0,394 |
| 10 sn | APPEND | 18/18 | 102.099 | 0 | 0,347 |
| 10 sn | INSERT | 18/18 | 59.452,5 | 6,5 | 2,671 |

`APPEND` eski makine sırasının arkasına yeni işleri koyar ve eski başlangıç kaymasına 1000 ağırlık verir. `INSERT` eski işlerin kendi makine sırasını korurken yeni işleri araya alabilir; kayma ağırlığı 100'dür. Bu ağırlıklar fabrika maliyeti değil, araştırma tercihidir. İki yöntem yalnız yalıtılmış BALANCED what-if denemelerinde kullanılabilir; ACTIVE yayımlamaz. EDD/FIFO/SPT ise sabit dispatch sırası altında aynı fiziksel CP-SAT modelini çözer. `OPTIMAL`, yalnız seçilen sıra ve amaç için optimumdur; tüm serbest çizelgelerin optimumu değildir.

**Karar:** Kısa bütçede geçerli, daha az oynayan aday üretmek mümkün; `INSERT` 30/30 kabul ve ortanca 6 değişen iş gösterdi. Fakat EDD'nin teslim gecikmesi çoğu vakada belirgin biçimde daha düşüktür. 2 saniyelik eşlenik 30 denemenin yalnız 5'inde INSERT gecikmesi EDD'den iyi veya eşitti; bunların hepsi `SMALL_P02` vakasındaydı. APPEND'in sıfır hareketi yüksek gecikme pahasına geldi. Bu yüzden bu deney tek bir yöntemi otomatik varsayılan olarak seçtirmez. Müşteriyle hizmet sınırı ve plan değişim maliyeti kararlaştırılana kadar adaylar karşılaştırma olarak kalır.

Başarı sayısı tüm denemeleri içerir; başarısız FULL koşularına gecikme veya kararlılık değeri atanmaz. 2 ve 10 saniyelik satırların tohum kümeleri farklıdır; iki bütçenin ortancaları doğrudan hız/kalite etkisi olarak yorumlanmaz. Çözücü sınırı toplam istek süresi değildir; p95 model kurma, kopyalama ve bağımsız denetimi de içerir. Tohumlar bağımsız fabrika örnekleri değildir, ağırlıklar ilk pilot ölçümünden sonra seçildi ve bu deney ayrı bir doğrulama kümesi değildir. Saha yanıt süresi, termin başarısı, müşteri kabulü ve parasal fayda kanıtlanmış değildir.
