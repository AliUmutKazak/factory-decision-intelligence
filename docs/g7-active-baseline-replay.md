# G7-T: kabul edilmiş planla acil sipariş oynatması

Bu deney, [ilk acil sipariş ölçümündeki](g7-hot-order-replay.md) baz planın her istekte yeniden çözülmesi maliyetini ayırır. Mühürlü sentetik referans verisinin yalnız geçici kopyası `ACTIVE` yapılır. Yeni yol, o kopyadaki **tek kabul edilmiş** `ACTIVE` solver kaydını ve çizelgeyi okur, acil sipariş için ayrı run girdilerini klonlar ve mevcut çizelgeyi CP-SAT başlangıç ipucu olarak kullanır. Kaynak dosyaya veya gerçek `ACTIVE` plana yazmaz. Eksik/`UNKNOWN` baz planı reddeder; önceki planı yeni sipariş kabul edilmiş gibi sunmaz. Referansın model bağlamı boştur; dondurulmuş görev, esnek pencere, bakım kısıtı veya ileri başlangıç zamanı taşıyan `ACTIVE` planı, bu kısıtlar senaryoya aktarılmadığı için açıkça reddeder.

## Bilimsel ve teknik dayanak

- [Vieira, Herrmann ve Lin (2003)](https://doi.org/10.1023/A:1022235519958), üretim yeniden çizelgelemesinde mevcut çizelge ve olay tetikleyicisi etrafındaki politika seçimini çerçeveler. FDI'de acil sipariş bir olaydır; mevcut kabul edilmiş plan karşılaştırma temelidir.
- [Kovács ve diğerleri (CP 2021)](https://doi.org/10.4230/LIPIcs.CP.2021.36), gerçek üretim verili bir makine yük dengeleme uygulamasında hızlı sezgisel çözümü optimizasyonu başlatmak için kullanır. Bu, başlangıç çözümü araştırmasını destekler; onların tesis sonucunu FDI performansına aktarmıyoruz.
- [Google OR-Tools CP-SAT API](https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model) çözüm ipucu mekanizmasını sağlar. İpucu fizibilite kanıtı değildir; yeni sipariş eklenince solver yine tüm kısıtları çözmelidir.

Kod incelemesinde ayrı bir kimlik çakışması bulundu: mevcut çizelgeden alınan görev kimlikleri korunurken yeni acil sipariş görevlerine `0`dan başlayan kimlikler verilebiliyordu. Bu, `MODEL_INVALID` üretiyordu. Yeni kimlikler mevcut kimliklerden farklı seçiliyor ve solver kurulmadan tekrar kontrol ediliyor. Ayrıca laboratuvar ölçümünde `EDD`, `FIFO`, `SPT` veya `Greedy` ile makine sırası sabitlenebilir; bu, tam modelin optimizasyon alanını daraltır ve sonuç kapsamını değiştirir.

## Aynı sentetik olayla ölçüm

Girdi `P01`, 51 adet, teslim zamanı 1200 dakika, öncelik ağırlığı 20. Mühürlü kaynak SHA-256: `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`. Her JSON kendi kod commit'ini ve dosya hash'lerini taşır. Her deneme ayrı geçici DB kopyasında; kaynak ve geçici `ACTIVE` hash'i sonunda kontrol edilir.

| Baz plan yöntemi | Acil sipariş limiti | Tekrar | Kabul edilen yeni plan | Toplam replay p50 / p95 |
|---|---:|---:|---:|---:|
| [Yeniden çözüm](../artifacts/research/g7-hot-order-baseline-5s.json), baz limit 5 sn | 2 sn | 5 | 0/5; 4 baz, 1 senaryo başarısız | 5,3823 / 7,1639 sn |
| [Kabul edilmiş `ACTIVE` kopyası](../artifacts/research/g7-hot-order-active-2s.json) | 2 sn | 5 | 0/5; baz başarısızlığı 0 | 2,6286 / 2,6537 sn |
| [`ACTIVE`, ilk 10 sn koşumu](https://github.com/AliUmutKazak/factory-decision-intelligence/blob/2ba62b3/artifacts/research/g7-hot-order-active-10s.json) | 10 sn | 3 | 3/3 `FEASIBLE` | 10,1672 / 10,1777 sn |
| [`ACTIVE`, tekrar koşum](../artifacts/research/g7-hot-order-active-10s.json) | 10 sn | 3 | 0/3 | 10,4417 / 10,4621 sn |
| [`ACTIVE`, uzun tekrar](../artifacts/research/g7-hot-order-active-20s.json) | 20 sn | 3 | 0/3 | 20,4551 / 20,4646 sn |
| [`ACTIVE`, tam model](../artifacts/research/g7-hot-order-full-60s.json) | 60 sn | 1 | 1/1 `FEASIBLE` | 60,2578 sn |

`ACTIVE` kopyası geçmişte 30 saniyede `FEASIBLE` bulunmuş bir plandır; onun eski solve süresi replay gecikmesine eklenmez. Farklı süre limitleri ayrı koşullardır. Aynı 10 saniye sınırıyla iki koşumun 3/3 ve 0/3 olması, bu örnekte dahi kabul oranının kararlı olmadığını gösterir. 60 saniyelik tek kabul de hizmet hedefi değildir. Bu küçük sentetik örneklerden güvenilirlik yüzdesi, p95 hizmet taahhüdü veya fabrika performansı çıkarılamaz. `FEASIBLE`, **optimal kanıtı değildir**. Başlangıç ipucu ve kimlik düzeltmesi aynı geliştirmede olduğu için hangisinin çözüm oranına ne kadar katkı yaptığı ayrı ayrı çıkarılamaz.

### Sıra sabitlemeli keşif

Aynı olayda kabul edilmiş baz plan ve **2 saniye** solver sınırıyla her kural beş kez ölçüldü:

| Sıra kuralı | Kabul | Replay p50 / p95 | Makespan | Ağırlıklı gecikme | Kapsam |
|---|---:|---:|---:|---:|---|
| [EDD](../artifacts/research/g7-hot-order-edd-2s.json) | 5/5 | 0,2290 / 0,2466 sn | 14149 dk | 62669 dk | Sabit sıra içinde `OPTIMAL` |
| [FIFO](../artifacts/research/g7-hot-order-fifo-2s.json) | 5/5 | 0,2393 / 0,2463 sn | 14149 dk | 62669 dk | Sabit sıra içinde `OPTIMAL` |
| [SPT](../artifacts/research/g7-hot-order-spt-2s.json) | 5/5 | 0,2388 / 0,2736 sn | 14320 dk | 68920 dk | Sabit sıra içinde `OPTIMAL` |
| [Greedy](../artifacts/research/g7-hot-order-greedy-2s.json) | 5/5 | 0,2258 / 0,3184 sn | 14320 dk | 68920 dk | Sabit sıra içinde `OPTIMAL` |

Bu `OPTIMAL` sonuçları **tam CP-SAT modelinin optimumu değildir**; makine sırası kural tarafından kilitlenmiştir. Baz plandaki ağırlıklı gecikme 6064 dakikadır, fakat o planda acil sipariş bulunmaz; doğrudan kalite karşılaştırması yapılamaz. 60 saniyelik tam modelin tek `FEASIBLE` örneğinde ağırlıklı gecikme 236624 dakika çıktı; tek koşum ve bulunmuş ilk/ara çözüm olduğu için sıra kurallarına genel üstünlük sonucu çıkarılmaz. Sabit sıra denemesi hızlı ve geçerli bir aday üretiyor, ama ürün varsayılanı veya otomatik yayın politikası olarak henüz kabul edilmedi.

Tekrar için önceki komuta `--reuse-active-baseline` eklenir; `--scenario-limit` seçilir. Sıra sabitlemeli koşumda `--dispatch-rule EDD` gibi bir kural eklenir. Bu modda `--baseline-limit` uygulanmaz; JSON'da `baseline_limit_seconds` ve replay baz çözüm süresi `null`, kaynak planın geçmiş solve süresi ayrı alandadır. JSON'daki `optimization_scope` alanı tam model ile sabit sıra sonuçlarını ayırır.

## Karar ve sonraki kapı

Bu yol G7 laboratuvar araştırmasıdır. API'nin varsayılan davranışı değiştirilmedi. Kullanıcıya sunulacak acil sipariş yanıtı için belirlenmiş yük zarfı, birkaç farklı olay/tohum, bağımsız çizelge uygunluk denetimi, gerçek eşzamanlı istek davranışı, `ACTIVE` yaş politikası ve timeout sonrası açık kullanıcı mesajı hâlâ sınanmalıdır. Özellikle sıra sabitlemeli adayın gecikme ve maliyet etkisi açık kabul eşiği olmadan otomatik yayımlanmamalıdır. Fabrika verisi olmadan bu adımlar sentetik olarak sürdürülebilir; saha kabulü daha sonraki G1/G9-G12 kapılarında kalır.
