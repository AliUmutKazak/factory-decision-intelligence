# G4-T sentetik dosya pilotu örneği

Bu paket yalnız laboratuvar ön incelemesidir. Gerçek müşteri veya vendor verisi içermez. `manifest.json` kaynağı, zaman başlangıcını ve dosyaları tanımlar. Dakika alanları, zaman dilimi yazılı `origin` anına göredir. Miktar birimi bu örnekte **adet**, işlem süresi **dakika/adet** kabul edilmiştir; gerçek pilotta birim sözleşmesi ayrıca onaylanır.

Proje kökünden çalıştırma:

```powershell
python -m src.integration.pilot_preflight examples/pilot-package/manifest.json
```

Çıktı `ACCEPTED` veya `REJECTED`, dosya SHA-256 özetleri, ayrıştırılan satır sayıları ve hata nedenlerini içerir. İşlem hiçbir dosyayı veya ACTIVE planı değiştirmez. `actuals.csv` isteğe bağlıdır; olmadığı durumda gerçekleşen üretim veya nakit fayda kıyası yapılamaz. Mevcut `actuals.csv` şeması her lot ve operasyon için tek bir toplu kayıt kabul eder; kısmi üretim, kesinti/devam, hurda ve rework olay dizisini temsil etmez. G6-T için [ayrı sentetik olay denetimi](../../docs/g6-synthetic-execution-replay.md) vardır; dosya pilotu adaptörüne bağlı değildir.

`baseline_coverage` her lotun tanımlı rota operasyonları için mevcut planda kaç kayıt bulunduğunu gösterir. `INCOMPLETE` olduğunda paket yapısal olarak `ACCEPTED` olabilir, ancak bu plan tam bir G8 kıyası için kullanılmaz. `COMPLETE` yalnız kapsamı gösterir; fiziksel geçerlilik veya ekonomik kıyas kabulü değildir. Rapor eksik kayıt sayısını ve ilk 20 lot/operasyon örneğini verir. Gerçekleşen sağlam ve hurda miktarlarının aynı operasyonda toplamı sipariş miktarını aşarsa kayıt reddedilir; bu üst sınır, operasyonlar arası WIP veya rework muhasebesi yerine geçmez.

`reported_min`, gerçekleşme kaydının sisteme ulaştığı dakikadır; `actual_end_min` ise fiziksel bitiştir. İkisi de manifestteki `origin` anına göredir. Bu sentetik örnek manifestte `max_actual_reporting_lag_min: 30` ilan eder; ön inceleme sıra, çakışma ve bildirim gecikmesini [ayrı kanıt kaydındaki](../../docs/g4-actuals-timing-preflight.md) gibi ölçer. Gerçek pilot için 30 dakika hedef değildir; sınırı veri sahibi ve operasyon ekibi belirlemelidir. `reported_min` veya ilan edilen eşik yoksa rapor gecikmeyi doğrulanmış saymaz.

Mevcut planın aynı makinedeki çakışan aralıkları, lot içindeki operasyon sıra ihlalleri ve beyan edilmiş vardiyada kesintisiz bulunmayan aralıkları satır numarasıyla reddedilir. İsteğe bağlı `planned_qty` **o operasyonun planlanan miktarıdır**; varsa plan süresi `planned_qty × dakika/birim` alt sınırını karşılamalı ve miktar sipariş miktarını aşmamalıdır. Alan yoksa sipariş miktarı sessizce plan miktarı sayılmaz; `baseline_duration.status=PARTIAL_OR_UNKNOWN_QUANTITY` olur. Tam bir fiziksel baz plan kıyasından önce bu alanın bütün operasyonlarda bulunması gerekir. Bitiş ve sonraki başlangıcın aynı dakika olması geçerlidir; bitişik vardiyalar kesintisiz tek pencere gibi kabul edilir. Fazla mesai planlandıysa dosyada açık vardiya penceresi olarak gösterilmelidir. Bu yalnız dar, kesintisiz operasyon varsayımına dayalı fiziksel tutarlılık kontrolüdür. Gerçekleşen olayların vardiya uyumu, setup, kesinti/devam, alternatif kaynak ve malzeme uygunluğu henüz denetlenmez.

CSV veya `.xlsx` dosyası kullanılabilir. Farklı sütun adları varsa manifestte **her dosya için** kanonik alan → kaynak başlık eşlemesi açıkça verilir. Excel için sayfa adı zorunludur; bir çalışma kitabındaki diğer sayfalar otomatik birleştirilmez. Başlık satırı varsayılan olarak 1'dir ve `header_row` ile seçilebilir. Örneğin `orders` dosyası:

```json
{
  "path": "orders.xlsx",
  "sheet": "Orders",
  "header_row": 2,
  "columns": {
    "order_id": "Order No",
    "lot_id": "Lot No",
    "product_id": "SKU",
    "quantity": "Units",
    "due_min": "Due Minute"
  }
}
```

Excel'de eşlenen hücrelerde formül, tarih/saat veya boolean kabul edilmez. Tarihleri, zaman dilimi tanımlı `origin` noktasından itibaren dakikaya; miktarları da beyan edilmiş ortak birime kaynak sahibiyle dönüştürmek gerekir. Bu okuyucu yalnız sütun başlıklarını eşler; ürün/makine kimliklerini, birimleri ve zaman eksenini tahmin ederek dönüştürmez. Ham dosyanın SHA-256 değeri, seçilen sayfa ve uygulanan eşleme raporda görünür; dosya değiştirilmez.

Mevcut üretim `routing` tablosu ürün/operasyon başına tek makine tanımladığı için alternatif makine satırları `unsupported_alternative_machine` ile reddedilir. BOM/stok, tam fiziksel plan doğrulaması ve solver'a aktarım sonraki teknik işlerdir. Bu ön incelemenin geçmesi G4 müşteri verisi kabulü veya G8 plan kıyası anlamına gelmez.

Üretim çözücüsünün takvimi şu anda sabit Pazartesi–Cumartesi 08:00–24:00 düzenli çalışma ve sınırlı fazla mesai modelidir. Dosya pilotundaki serbest vardiya aralıkları birebir aktarılmadan mevcut plan ile çözücü çıktısı eşit fiziksel koşullarda kıyaslanmış sayılmaz. Bu nedenle okuyucu doğrulanmış paketi otomatik çizelgeleme koşusuna göndermez.
