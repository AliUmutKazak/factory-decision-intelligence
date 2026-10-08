# G7-T: sentetik acil sipariş olay oynatması

Bu laboratuvar deneyi, mühürlü `artifacts/reference/factory.db` içindeki tamamlanmış referans run'ını her denemede ayrı bir geçici SQLite dosyasına kopyalar. Yalnız geçici kopyada run `ACTIVE` yapılır. `WhatIfEngine`, bu kopyayı salt okunur açıp baz planı ve `P01` ürünü için 51 adetlik sentetik acil siparişi bellek içinde çözer. Kaynak dosya ve geçici `ACTIVE` run, başarılı veya başarısız denemede değişmez.

## Tekrar çalıştırma

Proje kökünden, bağımlılıkların kurulu olduğu Python ile:

```powershell
python -m src.scheduling.hot_order_load_probe `
  --db artifacts/reference/factory.db `
  --baseline-run-id RUN-20261006-00a0d3 `
  --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf `
  --repeats 5 --baseline-limit 5 --scenario-limit 2 `
  --output artifacts/research/g7-hot-order-baseline-5s.json
```

8 Ekim 2026 yerel koşumunda baz planın **4/5** denemesi 5 saniyede geçerli çözüm bulamadı. Baz planın `FEASIBLE` olduğu tek denemede acil sipariş adımı 2 saniyede `TimeoutError` ile durdu. Bu beş denemede **0/5 kabul edilmiş acil sipariş planı** vardır. Tüm denemelerde geçici `ACTIVE` run ve mühürlü kaynak hash'i korundu. [Ham sonuç](../artifacts/research/g7-hot-order-baseline-5s.json), commit, kod/kaynak hash'leri, iki ayrı süre sınırı, aşama, hata türü ve her deneme süresini içerir.

Bu profil özellikle kısa etkileşimli süre sınırını sınar; **5 saniyelik baz plan denemesi ile 2 saniyelik acil sipariş denemesi ayrı paydalardır**. Baz plan başarısızsa acil sipariş çözücüsü çalıştırılmaz. Toplam replay süresi kopyalama sonrası baz ve senaryo çözümünü içerir. Beş örneğin p95'i hizmet hedefi değildir; kabul edilmiş senaryo olmadığı için senaryo çözücü p50/p95'i `null` bırakılır. Daha uzun baz plan sınırıyla yapılan keşif koşumunda baz plan geçerli çözüm bulmuş, kısa acil sipariş adımı yine çözümsüz kalmıştır; resmî tekrar sayısı ve kanıt yalnız yukarıdaki beş koşumdur.

## Sonraki teknik iş ve sınır

Baz planı yeniden çözmenin maliyeti için [kabul edilmiş `ACTIVE` planını yeniden kullanan takip ölçümü](g7-active-baseline-replay.md) yapıldı. Başarısız denemede doğrulanmamış plan yayımlanmaz; fakat gerçek API eşzamanlılığı, kuyruk, alarm, fallback politikası, `ACTIVE` yaşı ve müşteri SLO'su bu deneyle kanıtlanmaz. Bu sonuç, G7 saha kabulü veya fabrika performansı değildir.
