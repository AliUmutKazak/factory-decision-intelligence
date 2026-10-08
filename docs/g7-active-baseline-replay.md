# G7-T: kabul edilmiş planla acil sipariş oynatması

Bu deney, [ilk acil sipariş ölçümündeki](g7-hot-order-replay.md) baz planın her istekte yeniden çözülmesi maliyetini ayırır. Mühürlü sentetik referans verisinin yalnız geçici kopyası `ACTIVE` yapılır. Yeni yol, o kopyadaki **tek kabul edilmiş** `ACTIVE` solver kaydını ve çizelgeyi okur, acil sipariş için ayrı run girdilerini klonlar ve mevcut çizelgeyi CP-SAT başlangıç ipucu olarak kullanır. Kaynak dosyaya veya gerçek `ACTIVE` plana yazmaz. Eksik/`UNKNOWN` baz planı reddeder; önceki planı yeni sipariş kabul edilmiş gibi sunmaz.

## Bilimsel ve teknik dayanak

- [Vieira, Herrmann ve Lin (2003)](https://doi.org/10.1023/A:1022235519958), üretim yeniden çizelgelemesinde mevcut çizelge ve olay tetikleyicisi etrafındaki politika seçimini çerçeveler. FDI'de acil sipariş bir olaydır; mevcut kabul edilmiş plan karşılaştırma temelidir.
- [Kovács ve diğerleri (CP 2021)](https://doi.org/10.4230/LIPIcs.CP.2021.36), gerçek üretim verili bir makine yük dengeleme uygulamasında hızlı sezgisel çözümü optimizasyonu başlatmak için kullanır. Bu, başlangıç çözümü araştırmasını destekler; onların tesis sonucunu FDI performansına aktarmıyoruz.
- [Google OR-Tools CP-SAT API](https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model) çözüm ipucu mekanizmasını sağlar. İpucu fizibilite kanıtı değildir; yeni sipariş eklenince solver yine tüm kısıtları çözmelidir.

Kod incelemesinde ayrı bir kimlik çakışması bulundu: mevcut çizelgeden alınan görev kimlikleri korunurken yeni acil sipariş görevlerine `0`dan başlayan kimlikler verilebiliyordu. Bu, `MODEL_INVALID` üretiyordu. Yeni kimlikler mevcut kimliklerden farklı seçiliyor ve solver kurulmadan tekrar kontrol ediliyor.

## Aynı sentetik olayla ölçüm

Girdi `P01`, 51 adet, teslim zamanı 1200 dakika, öncelik ağırlığı 20. Mühürlü kaynak SHA-256: `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`. Kod commit'i: `306acb1ea08e5113b3881115b3a6043ab3aa5a20`. Her deneme ayrı geçici DB kopyasında; kaynak ve geçici `ACTIVE` hash'i sonunda kontrol edilir.

| Baz plan yöntemi | Acil sipariş limiti | Tekrar | Kabul edilen yeni plan | Toplam replay p50 / p95 |
|---|---:|---:|---:|---:|
| [Yeniden çözüm](../artifacts/research/g7-hot-order-baseline-5s.json), baz limit 5 sn | 2 sn | 5 | 0/5; 4 baz, 1 senaryo başarısız | 5,3823 / 7,1639 sn |
| [Kabul edilmiş `ACTIVE` kopyası](../artifacts/research/g7-hot-order-active-2s.json) | 2 sn | 5 | 0/5; baz başarısızlığı 0 | 2,1188 / 2,1375 sn |
| [Kabul edilmiş `ACTIVE` kopyası](../artifacts/research/g7-hot-order-active-10s.json) | 10 sn | 3 | 3/3 `FEASIBLE` | 10,1672 / 10,1777 sn |

`ACTIVE` kopyası geçmişte 30 saniyede `FEASIBLE` bulunmuş bir plandır; onun eski solve süresi replay gecikmesine eklenmez. 2 ve 10 saniyelik limitler farklı koşullardır. Bu küçük örnekler güvenilirlik yüzdesi, p95 hizmet taahhüdü veya fabrika performansı değildir. Yeni plan 10 saniye sınırında üç kez bulundu, fakat **optimal olduğu kanıtlanmadı**. Başlangıç ipucu ve kimlik düzeltmesi aynı geliştirmede olduğu için hangisinin çözüm oranına ne kadar katkı yaptığı bu deneyden ayrı ayrı çıkarılamaz.

Tekrar için önceki komuta `--reuse-active-baseline` eklenir; `--scenario-limit` ile 2 veya 10 saniye seçilir. Bu modda `--baseline-limit` uygulanmaz; JSON'da `baseline_limit_seconds` ve replay baz çözüm süresi `null`, kaynak planın geçmiş solve süresi ayrı alandadır.

## Karar ve sonraki kapı

Bu yol G7 laboratuvar araştırmasıdır. API'nin varsayılan davranışı değiştirilmedi. Kullanıcıya sunulacak acil sipariş yanıtı için belirlenmiş yük zarfı, birkaç farklı olay/tohum, bağımsız çizelge uygunluk denetimi, gerçek eşzamanlı istek davranışı, `ACTIVE` yaş politikası ve timeout sonrası açık kullanıcı mesajı hâlâ sınanmalıdır. Fabrika verisi olmadan bu adımlar sentetik olarak sürdürülebilir; saha kabulü daha sonraki G1/G9-G12 kapılarında kalır.
