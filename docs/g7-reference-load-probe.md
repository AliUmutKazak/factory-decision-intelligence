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
  --output artifacts/research/g7-reference-load-probe.json
```

Çıktı her denemenin durumunu, toplam deneme süresini ve kabul edilmiş çözümlerde CP-SAT'ın kendi süresini ayrı kaydeder. `OPTIMAL` ve `FEASIBLE` geçerli çözüm sayılır; `NO_ACCEPTED_SOLUTION` ayrıca sayılır ve gerekçesi saklanır. Toplam süre, bellek kopyalama, model kurma ve raporlama yükünü de içerir. p50/p95, sıralanmış örnekler üzerinde doğrusal ara değer yöntemiyle hesaplanır; yalnız birkaç örneğin p95 değeri hizmet hedefi değildir. [Makine tarafından okunabilen sonuç](../artifacts/research/g7-reference-load-probe.json) aynı kaynak, girdi ve kod hash'lerini içerir.

8 Ekim 2026 yerel koşumunda, kod commit'i `b905ab7` üzerinde 2 saniye sınırıyla **5/5 `FEASIBLE`** sonuç alındı; optimum kanıtlanmadı. Kabul edilmiş çözümlerin CP-SAT süreleri için p50 **2,0026 sn**, p95 **2,0038 sn**; tüm deneme süresi için p50 **2,7585 sn**, p95 **2,7776 sn** ölçüldü. Bu küçük örnek yalnız referans yükte araç ve raporlama zincirinin çalıştığını gösterir.

`WhatIfEngine` de kaynak veritabanını salt okunur açar. Yerel testte acil sipariş senaryosu zaman aşımı hatasıyla durdurulduğunda kaynak dosyanın hash'i, önceki `ACTIVE` run kimliği ve run kayıtları değişmedi. Bu başarısız çözüm emniyeti kanıtıdır; gerçek timeout/fallback oranı ölçümü değildir.

## Kanıtın sınırı

Bu ölçüm tek yerel bilgisayarda, sentetik/tamamlanmış referans yükte, tek iş parçacığıyla çalışır. Hot-order olay replay'i, eşzamanlı API istekleri, gerçek müşteri yükü, `ACTIVE` yaşlanması, fallback, actuals gecikmesi ve saha SLO'su ölçülmüş sayılmaz. `FEASIBLE`, optimum kanıtı değildir. `NO_ACCEPTED_SOLUTION` genel sayısı doğrudan timeout oranına eşit değildir; `UNKNOWN`, `INFEASIBLE` ve diğer hata nedenleri ayrı yorumlanmalıdır. G7 kabulü için temsilî yük zarfı, başarısız çözüm yolu, alarm/runbook ve saha sorumlusu ayrıca gerekir.
