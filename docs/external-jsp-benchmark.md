# G8-T: bağımsız sabit makineli iş çizelgeleme kıyası

## Sınır ve kaynak

Bu laboratuvar deneyi [OR-Library jobshop1](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/jobshopinfo.html) içindeki `ft06` örneğini kullanır. İndirilen tam `jobshop1.txt` dosyasının SHA-256 değeri `7f36d103332f94cfdeb76358e40927a57cfa7a426ebeaabd4de666350c69f028` olarak doğrulandı. Ham kaynak depoya eklenmedi. `ft06`, 6 iş × 6 makine ve 36 operasyon içerir. Kaynak makine kimlikleri 0–5 aralığındadır; aktarımda 1–6 aralığına çevrilir. Sürelerin birimi soyut benchmark birimidir; testte **1 kaynak birimi = 1 model dakikası** kabul edilir. Bu fabrika süresi veya müşteri standardı değildir.

OR-Library'deki sabit makine rotası, mevcut FDI üretim modelinin tek makine/operasyon yapısıyla eşleşir. Alternatif makineli `Mk01` bu eşleşmeye sahip değildir; onun optimumuyla kıyas yapılmaz. [FICO'nun yayımladığı FT06 örneği](https://examples.xpress.fico.com/example.pl?id=jobshopas_5) 55 birimlik bilinen optimumu bildirir; FDI sonucunu değerlendirirken aynı düz statik JSP problemi kullanılır.

## Tekrar çalıştırma

PowerShell'de proje kökünden:

```powershell
$source = Join-Path $env:TEMP 'fdi-orlib-jobshop1.txt'
Invoke-WebRequest 'https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/jobshop1.txt' -OutFile $source
(Get-FileHash $source -Algorithm SHA256).Hash
python -m src.scheduling.external_jsp_benchmark $source ft06 --sha256 7f36d103332f94cfdeb76358e40927a57cfa7a426ebeaabd4de666350c69f028
```

Komut belirtilen hash'i zorunlu tutar. Mühürlü `artifacts/reference/factory.db` yalnız salt okunur açılır ve belleğe kopyalanır. Bellekte eski fabrika ürünleri, rotaları, makineleri, takvimi, BOM/MRP, hazırlık ve makine durumu temizlenir. `ft06` için 6 iş ve 36 operasyon kaydı hazırlanır; hafta 1 fazla mesai sıfır, hazırlık ve malzeme talebi sıfır, tüm teslim tarihleri etkisizdir. `THROUGHPUT_MAX` politikası yalnız makespan'i pozitif ağırlıkla en aza indirir. Kaynak zaman ekseni, modelin ilk açık vardiyası olan 480. dakikaya taşınır. Sonuç bağımsız `check_fjsp_schedule` ile atama, süre, öncüllük ve makine çakışması açısından denetlenir. Hiçbir ACTIVE sürüm veya üretim dosyası yayımlanmaz.

`la01`, `la02` ve `ft10` için aynı komuttaki örnek adını değiştirerek deney tekrarlanır. Kaynak dosya ve SHA-256 aynıdır; `ft10` için 30 saniyelik süre sınırında `FEASIBLE` sonuç optimum kanıtı sayılmaz.

## Sonuçlar ve yorumu

8 Ekim 2026 yerel çalışmasında CP-SAT `OPTIMAL` döndü; modelin mutlak bitişi 535 dakika, kaynak eksenine çevrilmiş makespan **55 birim** oldu. Bağımsız denetim 36 operasyonun tamamını kabul etti. Sıfır hazırlık, sıfır gecikme, sıfır fazla mesai ve ilk açık vardiya içinde tamamlama kontrolleri geçti. Çözücü sürümü, süre sınırı, tohum, işçi sayısı, kaynak/veritabanı/kod hash'leri ve çalışma ortamı komutun JSON çıktısındadır. Küçük sentetik sabit makineli örnekle uçtan uca aktarım ve disk dosyalarının değişmediği de test edilir.

8 Ekim 2026 tarihinde aynı mühürlü kaynak ve referansla üç ek sabit makineli örnek çalıştırıldı. Tüm satırlarda bağımsız çizelge denetimi ve karşılaştırılabilir düz JSP alt kümesi kontrolü geçti. Süreler bu yerel koşuma aittir; ürün yanıt süresi veya farklı araçlara karşı hız kıyası değildir.

| Örnek | İş × makine; operasyon | Çözücü durumu | Makespan (kaynak birimi) | Çözücü süresi |
|---|---:|---|---:|---:|
| [`ft06`](../artifacts/research/ft06-static-jsp.json) | 6 × 6; 36 | `OPTIMAL` | 55 | 0,1405 sn |
| [`la01`](../artifacts/research/la01-static-jsp.json) | 10 × 5; 50 | `OPTIMAL` | 666 | 0,1269 sn |
| [`la02`](../artifacts/research/la02-static-jsp.json) | 10 × 5; 50 | `OPTIMAL` | 655 | 0,5023 sn |
| [`ft10`](../artifacts/research/ft10-static-jsp.json) | 10 × 10; 100 | `FEASIBLE` | 938 | 30,004 sn |

`ft10` çizelgesi uygundur; 30 saniye içinde en iyilik kanıtlanmadı. JSON çıktısında model amaç değeri ve alt sınır ayrı kaydedilir. Kaynak dosyanın kendisi ve hiçbir müşteri verisi depoya eklenmedi.

Bu sonuç **yalnız eşitlenmiş düz statik JSP alt kümesi** için matematiksel uygunluk ve optimum kanıtıdır. FDI'nin gerçek fabrika takvimi, setup, malzeme, WIP, gerçek sipariş gelişleri, maliyet/enerji/karbon modeli veya müşteri tasarrufu bu deneyle doğrulanmış olmaz. Daha büyük dış örneklerde takvim bağlayıcı olursa `comparable_static_jsp_subset` yanlış döner; aynı problem olarak yüzde iyileşme raporlanmaz. Bu G8-T teknik kanıtı, G8 saha kabulünü kapatmaz.
