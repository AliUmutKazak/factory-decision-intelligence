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

## 11 Ekim 2026 tekrarlı denetim

Aynı kaynak SHA-256 ve mühürlü referans DB ile `ft06`, `la01`, `la02`, `ft10` üçer kez yeniden çalıştırıldı. Her koşuda 30 saniye sınırı, tek worker, sabit seed ve aynı politika kullanıldı. [Makinece okunabilir matris](../artifacts/research/jsp-repeat-matrix-2026-10-11.json) giriş/kod hash'lerini, her sonucu ve doğrusal ara değerli p50/p95 çözücü sürelerini içerir.

| Örnek | Geçerli ve düz JSP ile karşılaştırılabilir koşum | Tekrarlı makespan | Yorum |
|---|---:|---|---|
| `ft06` | 3/3 | 55, 55, 55 | `OPTIMAL`; bağımsız denetim geçti. |
| `la01` | 3/3 | 666, 666, 666 | `OPTIMAL`; bağımsız denetim geçti. |
| `la02` | 3/3 | 655, 655, 655 | `OPTIMAL`; bağımsız denetim geçti. |
| `ft10` | 0/3 | 1505, 1505, 1505 | `FEASIBLE` ve fiziksel olarak geçerli; ilk düzenli vardiyayı aştığı için **eşit düz JSP koşulu sağlanmadı**. |

Önceki tek `ft10` koşumundaki 938 değeri tarihsel sonuçtur. Eski ve yeni raporlardaki ham Python dosya hash'leri farklıdır; Windows checkout satır sonu dönüşümü de bu farkı yaratabildiği için yalnız hash farkından algoritma değişikliği sonucu çıkarılmaz. Kaynak ve referans DB hash'leri, OR-Tools sürümü, tohum ve işçi sayısı eşleşse de 30 saniyelik zaman sınırında elde edilen aday kalitesi değişti. Son üç koşum güncel ortamda 938 kalitesinin güvenilir biçimde tekrarlandığını göstermiyor. `ft10` için optimum/üstünlük iddiası çıkarılmaz; zaman sınırı, model takvimi ve aday kalitesi G7/G8-T açık riski olarak kalır. Negatif sonuç saklanır, kaynak veya önceki ölçüm geriye dönük değiştirilmez.

Yeni kıyas raporları ham `code_hashes` yanında `code_hashes_normalized_lf` alanını da kaydeder. İkinci alan Python kaynak dosyalarının yalnız satır sonlarını LF'ye çevirip hash'ler; kaynak kodun diğer baytları değişirse hash yine değişir. Eski raporlarda bu alan bulunmadığından önceki koşumlara geriye dönük yeni kimlik atanmamıştır.

## Aynı gün 60 saniyelik `ft10` tekrar deneyi

30 saniyelik negatif sonucu silmeden, aynı kaynak SHA-256, mühürlü referans DB, tek worker, seed ve amaç politikasıyla yalnız `ft10` üç kez **60 saniye** sınırında yeniden çalıştırıldı. [Ham tekrar matrisi](../artifacts/research/jsp-ft10-repeat-60s-2026-10-11.json) her üç koşumda bağımsız denetimin `ACCEPTED`, düz JSP karşılaştırılabilirlik kontrolünün `true` ve makespan'in **930** olduğunu gösterir. Üçü de `FEASIBLE` döndü; 60 saniyede model optimumluğu kanıtı çıkmadı. Deneyin p50/p95 çözüm süreleri sırasıyla yaklaşık 60,006/60,012 saniyedir ve bütçeye dayanır. [Özgün araştırma karşılaştırma tablosu](https://pmc.ncbi.nlm.nih.gov/articles/PMC7571099/) `FT10` için 930'u bilinen optimum olarak listeler; bu dış bilgiyle sayısal eşleşme, bu üç koşumdaki çözücü durumunu `OPTIMAL` yapmaz.

Sonuç: 30 saniyelik hizmet bütçesinde `ft10` aday kalitesi güvenilir değildir; 60 saniyede bu sabit makineli, hazırlıksız ve tek vardiya içine sığan alt problemde 3/3 geçerli 930 adayı bulunmuştur. Süre/kalite eğrisi başka makine, takvim, malzeme ve olay yüklerine taşınmaz. Üç tekrardan hız üstünlüğü veya gerçek fabrika SLO'su çıkarılmaz.

Bu sonuç **yalnız eşitlenmiş düz statik JSP alt kümesi** için matematiksel uygunluk kanıtıdır. `ft10` adayının bilinen 930 değeriyle eşleşmesi, bu koşulardaki `FEASIBLE` solver durumunu optimumluk sertifikasına dönüştürmez. FDI'nin gerçek fabrika takvimi, setup, malzeme, WIP, gerçek sipariş gelişleri, maliyet/enerji/karbon modeli veya müşteri tasarrufu bu deneyle doğrulanmış olmaz. Daha büyük dış örneklerde takvim bağlayıcı olursa `comparable_static_jsp_subset` yanlış döner; aynı problem olarak yüzde iyileşme raporlanmaz. Bu G8-T teknik kanıtı, G8 saha kabulünü kapatmaz.

## OR-Tools 9.15 sürümünde yeniden ölçüm

Bağımlılık güvenliği nedeniyle çözücü 9.14.6206'dan 9.15.6755'e yükseltildikten sonra aynı kaynak/referans hash'i, sabit seed, tek worker ve aynı normalleştirilmiş Python kod hash'leriyle ölçüm tekrarlandı. [30 saniyelik ham matris](../artifacts/research/jsp-repeat-ortools915-30s-2026-10-11.json) dört örneğin her birinde 3/3 bağımsız geçerli ve düz JSP ile karşılaştırılabilir aday verdi. `ft06` 55, `la01` 666, `la02` 655 değerlerinde üçer kez `OPTIMAL` kaldı. `ft10` 938, 938, 930 değerlerini üretti; üçünde de yalnız `FEASIBLE` durumu vardı. `ft10` p50/p95 çözüm süresi yaklaşık 30,003/30,037 saniyedir. [60 saniyelik yeni ham matris](../artifacts/research/jsp-repeat-ortools915-ft10-60s-2026-10-11.json) `ft10` için 3/3 geçerli, karşılaştırılabilir 930 adayı verdi; üç solver durumu yine `FEASIBLE`, p50/p95 yaklaşık 60,011/60,017 saniyedir.

9.14'ün 30 saniyelik **0/3** negatif kaydı tarihsel olarak korunur. 9.15'in **3/3** sonucu bu sürümün ölçülen koşullarında iyileşmedir; süre sınırına dayanan çözüm kalitesi tek üçlü deneyle güvenilir bir servis seviyesi veya sürümler arası genel performans üstünlüğü kanıtı değildir. 30 saniyede optimum 930 yalnız bir tekrarda bulundu; 60 saniyede üç tekrarda bulundu, fakat solver optimumluğu kanıtlamadı. Diğer fabrika kısıtları ve müşteri planları için ayrı deney gerekir.

## `v0.1.2-lab` koduyla 12 Ekim yeniden ölçüm

Önceki 9.15 matrislerinden sonra `src/config.py` ve `src/scheduling/schedule_cpsat.py` değiştiği için eski ölçümün kod hash'i yayımlanan `v0.1.2-lab` ile eşleşmiyordu. Bu nedenle aynı OR-Library kaynak SHA-256'sı, mühürlü referans DB, OR-Tools 9.15.6755, tek worker, sabit seed ve `THROUGHPUT_MAX` politikasıyla [30 saniyelik dört örnek matrisi](../artifacts/research/jsp-repeat-v012-30s-2026-10-12.json) yeniden üretildi. Matrisin normalleştirilmiş kod hash'leri yayımlanan commit'in kaynak dosyalarıyla eşleşir; test ortamı ve her adayın bağımsız denetimi JSON içinde kayıtlıdır.

| Örnek | Bağımsız kabul / tekrar | Makespan | Solver durumu | p50 / p95 solver süresi |
|---|---:|---|---|---:|
| `ft06` | 3/3 | 55, 55, 55 | 3× `OPTIMAL` | 0,183 / 0,245 sn |
| `la01` | 3/3 | 666, 666, 666 | 3× `OPTIMAL` | 0,220 / 0,223 sn |
| `la02` | 3/3 | 655, 655, 655 | 3× `OPTIMAL` | 2,828 / 2,888 sn |
| `ft10` | 3/3 | 938, 938, 938 | 3× `FEASIBLE` | 30,021 / 30,026 sn |

`ft10` için aynı kod ve kaynakla [60 saniyelik üç tekrar](../artifacts/research/jsp-repeat-v012-ft10-60s-2026-10-12.json) 3/3 bağımsız geçerli ve karşılaştırılabilir **930** adayına ulaştı; üçü de yine `FEASIBLE` ve p50/p95 60,012/60,081 saniyedir. 30 saniyede 930'a erişilememesi süre/kalite riskini teyit eder. Eski 9.15 koşusundaki 938/938/930 sonucu değiştirilmez; deneme ve kod kimliği farkı olmadan bu sonuçlar birleştirilmez. Az tekrarın p95 değeri saha SLO'su veya rakip üstünlüğü değildir. Referans run, müşteri planı, WIP, gerçek vardiya, malzeme, gerçek maliyet ve üretim kabulü hâlâ ayrı kanıt ister.
