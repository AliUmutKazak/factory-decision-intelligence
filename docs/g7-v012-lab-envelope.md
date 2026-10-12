# G7 laboratuvar yük zarfı - `v0.1.2-lab`

**12 Ekim 2026, sentetik/açık referans.** Ölçümler `631719c0a24e724a552ae716e4d6c08d09a6d9f9` koduyla, OR-Tools 9.15.6755 ve SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf` mühürlü referans DB'de yapıldı. Kaynak DB salt okunur; her deneme bellek veya geçici kopyada yürütüldü. Ham raporlar ve hash'leri [kanıt envanterinde](evidence-register.json) kayıtlıdır. Aşağıdaki yükler farklı karar problemleridir; süreleri tek p95 altında birleştirilmez.

| Yük / bütçe | Tekrar ve sonuç | Toplam p50 / p95 | Solver p50 / p95 | Başarısızlık / koruma |
|---|---|---:|---:|---|
| [Referans CP-SAT](../artifacts/research/g7-reference-load-v012-2026-10-12.json), 2 sn | 5/5 `FEASIBLE` | 2,767 / 2,794 sn | 2,003 / 2,004 sn | 0 kabul edilmeyen çözüm |
| [Üç etiketli acil sipariş](../artifacts/research/g7-hot-order-stress-v012-2026-10-12.json), EDD sabit sıra, 2 sn | 9/9 `OPTIMAL` ve bağımsız denetimli | Vaka bazında: 0,224/0,238; 0,207/0,209; 0,647/0,669 sn | Vaka bazında JSON'da | 0 timeout, 0 audit reddi |
| [Yapay kısa bütçeli negatif kontrol](../artifacts/research/g7-timeout-negative-control-v012-2026-10-12.json), EDD, 0,001 sn | 3/3 `NO_ACCEPTED_SOLUTION` | 0,168 / 0,194 sn | Uygulanmaz | 3/3 `TimeoutError`; 3/3 geçici ACTIVE değişmedi |

Son satır gerçek yükte timeout oranı değildir; hata yolunu zorlamak için bütçe yapay olarak 1 ms tutuldu. Kabul edilen satırlarda oran yalnız bu küçük ve seçilmiş sentetik örneklemdeki deney sayısıdır. `OPTIMAL` sabit EDD dizisine bağlanan alt problem için geçerlidir; genel üretim modeli optimumluğu değildir. API/panel/dispatcher süreçleri arasındaki `429/SOLVER_BUSY` ve `503/SOLVER_TIMEOUT` davranışı [işletim runbook'unda](g7-operations-runbook.md) ve testlerde ayrıca ele alınır. Bu matris eşzamanlı isteklerin gerçek dağılımını, alarm eşiğini, actuals tazeliğini veya fabrika SLO'sunu ölçmez. G7 saha kapısı açık kalır.

Tekrar için [referans yük](g7-reference-load-probe.md), [acil sipariş matrisi](g7-hot-order-stress-matrix.md) ve `python -m src.scheduling.hot_order_load_probe --help` komutlarına bakın. Yayınlanan `ACTIVE` yalnız doğrulanmış planla değiştirilir; timeout durumunda eski sürüm korunur.
