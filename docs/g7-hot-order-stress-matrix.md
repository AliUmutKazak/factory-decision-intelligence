# G7-T: etiketli sentetik acil sipariş stres matrisi

**Tarih:** 8 Ekim 2026. [Endüstriyel karar zekâsı araştırmasının değerlendirmesi](endustriyel-karar-zekasi-analizi-degerlendirmesi.md), tek sentetik olayın tekrarını farklı ve açıkça etiketli girdilerle genişletmeyi önerir. Bu deney mevcut acil sipariş çözümü ve [bağımsız çekirdek uygunluk denetimini](g7-independent-candidate-audit.md) kullanır. Mühürlü referans DB'yi değiştirmeden her deneme için geçici `ACTIVE` kopyası kurar.

## Yöntem ve tekrarlama

Üç vaka [JSON manifestinde](../examples/g7-hot-order-stress-cases.json) tanımlıdır. `P01` için 1 ve 51 birimlik farklı terminli siparişler; `P03` için farklı rotalı 200 birimlik sipariş vardır. Her biri üç kez, `EDD` sabit sevk sırası ve 2 saniye CP-SAT sınırıyla oynatıldı. Kaynak DB SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`, kaynak run `RUN-20261006-00a0d3`.

```powershell
python -m src.scheduling.hot_order_stress_matrix --db artifacts/reference/factory.db --baseline-run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --cases examples/g7-hot-order-stress-cases.json --repeats 3 --scenario-limit 2 --dispatch-rule EDD --output artifacts/research/g7-hot-order-stress-matrix-edd-2s.json
```

## Kaydedilen sonuç

| Sentetik vaka | Kabul | Bağımsız denetlenen görev | Replay p50 / p95 |
|---|---:|---:|---:|
| 1 birim, erken termin, `P01` | 3/3 | 34 | 0,2140 / 0,2315 sn |
| 51 birim, `P01` | 3/3 | 34 | 0,2145 / 0,2150 sn |
| 200 birim, farklı rota, `P03` | 3/3 | 33 | 0,2077 / 0,2083 sn |

[Ham JSON](../artifacts/research/g7-hot-order-stress-matrix-edd-2s.json) manifest, kod, Git ve kaynak hash'lerini; her denemenin solver durumunu, duvar süresini, bağımsız denetim sonucunu ve başarısızlık nedenini saklar. Toplam **9/9** aday `OPTIMAL` durumunda ve bağımsız denetimde 0 bulguyla kabul edildi. Bu `OPTIMAL` yalnız **sabit EDD sırası içindeki alt problem** içindir. Üçer tekrarın p95 değeri hizmet hedefi veya güven aralığı değildir.

Denetim miktar, rota, işlem aralığı, setup, öncüllük ve makine işgalini kapsar. Fabrika takvimi, bağımsız MRP/OT, gerçek makine olayları, simülasyon doğruluğu, insan kararı ve ekonomik fayda bu deneyde ölçülmedi. Üç etiketli vakanın geçmesi daha geniş yük ve arıza dağılımında güvenilirlik kanıtı sayılmaz. Gerçek tesisin planı ve actuals'ı oluştuğunda G8 saha kıyası ayrıca yapılacaktır.
