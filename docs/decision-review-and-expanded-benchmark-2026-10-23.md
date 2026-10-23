# Aday karar incelemesi ve genişletilmiş laboratuvar kıyası

**23 Ekim 2026.** Bu çalışma fabrika verisi veya saha kabulü içermez. Karar ekranı ve deneyler FDI'nin mevcut sabit rota, sentetik laboratuvar kapsamındadır.

Kod sürümü `ec67ba4bafea94847b01d957ddb0c6b78dfdb6b3` üzerinde ölçüldü. Ham kayıtlar kaynak, manifest ve ilgili kod hash'lerini taşır; çalışma ağacındaki belgeler daha sonra eklenmiştir.

## Aday planı inceleme

Makine arızası ve acil sipariş what-if sonuçlarında baz ve aday çizelgenin tamamlanma süresi, öncelik ağırlıklı gecikmesi ve hazırlık süresi yan yana gösterilir. Görev kimliğiyle eşleştirilen mevcut operasyonların makinesi, başlangıcı veya bitişi değişirse ayrı sayılır; yeni acil sipariş operasyonları ayrıca sayılır. Mutlak başlangıç kayması yalnız mevcut operasyonları kapsar. Değişen operasyonların satırları ve çözücü durumu görünür. Böylece eski “etkilenen görevler” etiketinin toplam görev sayısını etki gibi sunması önlenir.

Kullanıcı oturumunda “İncelemede”, “Denemeye uygun” veya “Reddedildi” ön değerlendirmesi ve notu seçebilir; karşılaştırma JSON olarak indirilebilir. Bu seçim **yalnız oturum belleğindedir** ve ACTIVE planı yayımlamaz. Yetkili saha kişisi/kurumu olmadan üretim onayı olarak yorumlanamaz. What-if baz planı yeniden çözülür, üretim gerçekleşmesi değildir. MRP yeniden hesaplanmadığı için malzeme farkı ölçülmüş gibi gösterilmez.

## Dış açık örnekler: OR-Library

[OR-Library jobshop1](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/jobshopinfo.html) içindeki üç ek Lawrence örneği (`la03`, `la04`, `la05`) önceden seçildi. Kaynak dosyanın SHA-256 değeri `7f36d103332f94cfdeb76358e40927a57cfa7a426ebeaabd4de666350c69f028`; mühürlü referans DB değeri `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`. Her örnek üç kez, aynı 10 saniye çözücü sınırı ve aynı varsayılan çözücü ayarlarıyla çalıştı. Salt okunur kaynaklar belleğe kopyalandı; bağımsız fiziksel uygunluk ve düz JSP karşılaştırılabilirlik kapıları tüm koşularda geçti. [Ham matris](../artifacts/research/jsp-la03-la05-repeat-2026-10-23.json) sürüm, kod hash'i, süre ve başarısızlık alanlarını içerir.

| Örnek | Geçerli/koşu | Üç makespan | Çözücü durumu |
|---|---:|---|---|
| `la03` | 3/3 | 597, 597, 597 | 3× `OPTIMAL` |
| `la04` | 3/3 | 590, 590, 590 | 3× `OPTIMAL` |
| `la05` | 3/3 | 593, 593, 593 | 3× `OPTIMAL` |

Bu sonuçlar yalnız sıfır hazırlık/gecikme ve etkisiz takvimli düz statik JSP alt problemine aittir; fabrika yanıt süresi veya müşteri kazancı kanıtı değildir. Eski `ft10` negatif ve değişken sonuçları [ayrı kayıtta](external-jsp-benchmark.md) korunur.

## Eşlenik sentetik acil sipariş kıyası

[Önceden yazılmış altı vaka](../examples/g7-hot-order-expanded-cases.json) beş ürün rotasına, farklı miktar/teslim/önceliklere yayılır. 2 saniyelik ana deneyde tohumlar `7, 17, 42, 73, 101`; yöntemler `FULL`, `FIFO`, `EDD`, `SPT`; her yöntem aynı mühürlü ACTIVE başlangıç çizelgesi, olay zamanı 0, tek worker, aynı vaka ve tohumla çalışır. Sonuçlar [120 koşuluk ham kayıtta](../artifacts/research/g7-paired-hot-order-expanded-2026-10-23.json) bulunur. Bağımsız denetimden geçmeyen veya aday bulamayan koşu kalite/kararlılık hesabına katılmaz, ama başarı paydasında başarısızlık sayılır.

| Yöntem | Geçerli/koşu | Kabul edilenlerde medyan makespan | Medyan değişen mevcut operasyon | Medyan mutlak başlangıç kayması |
|---|---:|---:|---:|---:|
| `FULL` | 0/30 | Hesaplanamaz | Hesaplanamaz | Hesaplanamaz |
| `FIFO` | 30/30 | 14.149 | 31 | 47.048 dk |
| `EDD` | 30/30 | 14.149 | 31 | 47.048 dk |
| `SPT` | 30/30 | 14.320 | 31 | 156.350 dk |

`FULL` için 2 saniyede 30 kez ilk kabul edilebilir çözüm çıkmadı. Bu onun kalite bakımından kötü olduğunu göstermez; kalite değeri yoktur. Sabit sevk sıraları aynı fiziksel modele ek sıralama kısıtı getirir; bunların `OPTIMAL` durumu serbest modelin optimumu değildir. Tüm 90 kabul edilen koşuda 31 eski operasyonun tamamı taşındı; bu laboratuvar başlangıcında plan kararlılığı ciddi bir maliyettir. Vaka ve tohumlar bağımsız fabrika örneklemi değildir; 30 koşu bir güven aralığı veya servis garantisi vermez.

İkinci eşit bütçeli 10 saniyelik koşu, ana deneydeki aday bulunamama sonucunun bütçe duyarlılığını sınamak için aynı altı vaka ve `7, 17, 42` tohumlarıyla ayrı raporlandı; iki bütçenin sonuçları tek havuzda birleştirilmez.

[10 saniyelik 72 koşunun ham kaydında](../artifacts/research/g7-paired-hot-order-expanded-10s-2026-10-23.json) `FULL` 6/18 geçerli aday üretti, 12/18 koşuda yine ilk aday bulunamadı. [Aynı kod ve ayarlarla ikinci tekrar](../artifacts/research/g7-paired-hot-order-expanded-10s-repeat2-2026-10-23.json) aynı 6/18 sonucunu ve aynı vaka/tohum kabul desenini verdi; bu tekrar yeni bağımsız fabrika örnekleri eklemez. `FIFO`, `EDD` ve `SPT` her iki koşuda 18/18 geçerli kaldı. `FULL` adaylarının çözücü durumu yalnız `FEASIBLE` idi; kabul edilen altı adayın medyan makespan'i 17.845, medyan ağırlıklı gecikmesi 100.505 oldu. `FIFO` ve `EDD` için karşılık gelen medyanlar 14.149 ve 60.394, `SPT` için 14.320 ve 45.655'tir. Bunlar yalnız kabul edilen koşuların betimsel değerleridir; `FULL` için on iki başarısızlığın kalitesi bilinmez, dolayısıyla koşullu medyanları tek başına yöntem üstünlüğü olarak sıralamak yanlı olur. Daha uzun bütçe ve başka başlangıç planları için sonuç açık kalır.

## Tekrar komutları

```powershell
$source = Join-Path $env:TEMP 'fdi-orlib-jobshop1.txt'
Invoke-WebRequest 'https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/jobshop1.txt' -OutFile $source
.\.venv\Scripts\python.exe -m scripts.repeat_jsp_benchmark $source --sha256 7f36d103332f94cfdeb76358e40927a57cfa7a426ebeaabd4de666350c69f028 --instances la03 la04 la05 --repeats 3 --time-limit 10 --output artifacts/research/jsp-la03-la05-repeat-2026-10-23.json
.\.venv\Scripts\python.exe -m src.scheduling.hot_order_method_comparison --db artifacts/reference/factory.db --baseline-run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --cases examples/g7-hot-order-expanded-cases.json --seeds 7 17 42 73 101 --methods FULL FIFO EDD SPT --scenario-limit 2 --workers 1 --output artifacts/research/g7-paired-hot-order-expanded-2026-10-23.json
.\.venv\Scripts\python.exe -m src.scheduling.hot_order_method_comparison --db artifacts/reference/factory.db --baseline-run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --cases examples/g7-hot-order-expanded-cases.json --seeds 7 17 42 --methods FULL FIFO EDD SPT --scenario-limit 10 --workers 1 --output artifacts/research/g7-paired-hot-order-expanded-10s-2026-10-23.json
# İkinci 10 sn tekrarı için aynı komutu farklı --output ile yeniden çalıştırın.
```
