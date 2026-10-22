# G7-T: mühürlü referans yükte tekrarlı çözücü ölçümü

Bu laboratuvar aracı, aynı tamamlanmış referans run'ını her denemede yeni bir bellek içi veritabanına kopyalar ve yalnız `CP-SAT` politikasını çalıştırır. Kaynak SQLite veritabanı salt okunur açılır; dosya SHA-256 değeri ölçüm öncesi ve sonrası doğrulanır. Hiçbir `ACTIVE` run veya üretim dosyası yayımlanmaz.

## Tekrar çalıştırma

Proje kökünden, bağımlılıkların kurulu olduğu Python ile:

```powershell
python -m src.scheduling.reference_load_probe `
  --db artifacts/reference/factory.db `
  --baseline-run-id RUN-20261006-00a0d3 `
  --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf `
  --repeats 5 --time-limit 2 `
  --output <yeni-dosya.json>
```

Güncel araç `OPTIMAL` veya `FEASIBLE` çözücü sonucunu ancak çizelge bağımsız fizik denetiminden de geçerse kabul sayar. Denetim görev ve miktar korunumu, rota, malzeme serbest bırakma, setup, işlem sırası, makine çakışması, takvim, fazla mesai, bakım ve kayıtlı donmuş/esnek kısıtları kontrol eder. Reddedilen çözüm `REJECTED_BY_AUDIT` olarak kalır; çözücünün özgün durumu ve denetim sorunları ayrıca saklanır. `NO_ACCEPTED_SOLUTION` ayrıca sayılır ve gerekçesi saklanır. Toplam deneme süresi bellek kopyalama, model kurma, denetim ve raporlamayı içerir. p50/p95 sıralanmış örnekler üzerinde doğrusal ara değer yöntemiyle hesaplanır; yalnız birkaç örneğin p95 değeri hizmet hedefi değildir.

[22 Ekim 2026 tek işçili yeni koşum](../artifacts/research/g7-reference-independent-audit-2026-10-22.json) aynı mühürlü sentetik kaynakta, 2 saniye solver sınırı ve tohum 42 ile **5/5 `FEASIBLE` ve 5/5 bağımsız kabul** verdi. CP-SAT süresi p50/p95 **2,0038 / 2,0044 sn**; denetim dahil deneme süresi p50/p95 **3,2014 / 3,2940 sn**. [Dört işçili tek koşum](../artifacts/research/g7-reference-independent-audit-workers4-2026-10-22.json) 10 saniye sınırı ve aynı tohumla **1/1 `FEASIBLE` ve 1/1 bağımsız kabul** verdi. Her iki çıktı kaynak, girdi, kod ve denetim hash'lerini, kaynak commit'ini ve her denemenin sonucunu taşır. Farklı süre sınırları ve bu küçük örnekle işçi ayarı seçilmez.

Eski [8 Ekim 2026 sonucu](../artifacts/research/g7-reference-load-probe.json), kod commit'i `b905ab7` üzerinde 2 saniye sınırıyla **5/5 `FEASIBLE`** bildirmişti. O kayıtta bağımsız aday denetimi yoktur ve yeni kabul sayılarıyla aynı kanıt sınıfında değildir. Her iki küçük örnek yalnız referans yükte araç ve raporlama zincirinin çalıştığını gösterir; optimumluk kanıtı değildir.

`WhatIfEngine` de kaynak veritabanını salt okunur açar. Yerel testte acil sipariş senaryosu zaman aşımı hatasıyla durdurulduğunda kaynak dosyanın hash'i, önceki `ACTIVE` run kimliği ve run kayıtları değişmedi. Bu başarısız çözüm emniyeti kanıtıdır; gerçek timeout/fallback oranı ölçümü değildir.

## Kanıtın sınırı

Bu ölçüm tek yerel bilgisayarda, sentetik/tamamlanmış referans yükte, tek iş parçacığıyla çalışır. [Acil sipariş olay oynatması](g7-hot-order-replay.md) ayrı ve daha zor bir yükü sınar; bu iki sonucun süreleri birbirine eşdeğer gösterilmez. Eşzamanlı API istekleri, gerçek müşteri yükü, `ACTIVE` yaşlanması, fallback, actuals gecikmesi ve saha SLO'su ölçülmüş sayılmaz. `FEASIBLE`, optimum kanıtı değildir. `NO_ACCEPTED_SOLUTION` genel sayısı doğrudan timeout oranına eşit değildir; `UNKNOWN`, `INFEASIBLE` ve diğer hata nedenleri ayrı yorumlanmalıdır. G7 kabulü için temsilî yük zarfı, başarısız çözüm yolu, alarm/runbook ve saha sorumlusu ayrıca gerekir.
