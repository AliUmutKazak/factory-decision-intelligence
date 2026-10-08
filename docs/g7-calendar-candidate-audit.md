# G7-T: acil sipariş adayının bağımsız takvim denetimi

**Tarih:** 8 Ekim 2026. [G7 sentetik vaka matrisindeki](g7-hot-order-stress-matrix.md) üç acil sipariş, önceki [miktar/rota/makine denetimine](g7-independent-candidate-audit.md) eklenen takvim kurallarıyla yeniden değerlendirildi. Denetim üretim çözücüsünü veya takvim servisinin hesaplama kodunu çağırmaz; kaynak veritabanındaki makine saatleri, W1 fazla mesai tahsisi ve aktif bakım aralıklarını ayrı okur.

Her görevin hazırlık ve üretim aralıklarında pazar gününe taşma, ikinci ve sonraki haftaların gece aralığı, bakım çakışması, W1 fiili gece dakikalarının makine bütçesini aşması ve açılan gece sayısının tahsisle uyuşması kontrol edilir. Gece sınırı makineye ait günlük çalışma saatinden hesaplanır. Kaynakta makine takvimi veya W1 bütçesi eksikse aday reddedilir. Bilerek değiştirilmiş çizelge ve kaynak kopyaları bu ihlallerin yakalandığını gösteren testlerden geçti.

```powershell
python -m src.scheduling.hot_order_stress_matrix --db artifacts/reference/factory.db --baseline-run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --cases examples/g7-hot-order-stress-cases.json --repeats 3 --scenario-limit 2 --dispatch-rule EDD --output artifacts/research/g7-hot-order-calendar-audit-edd-2s.json
```

[Ham kanıt](../artifacts/research/g7-hot-order-calendar-audit-edd-2s.json): üç etiketli sentetik vaka × üç tekrar = **9/9** sabit EDD sıra alt probleminde `OPTIMAL` ve genişletilmiş bağımsız denetimde **0 ihlal**. Kaynak DB SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`; yürütme commit'i `73df8478d33ee860fd855367cb39348a20409d84`. Manifest ve kod SHA-256 değerleri kullanılan Windows çalışma ağacının ham baytlarıdır; satır sonu dönüşümü nedeniyle Git blob veya başka işletim sistemi baytlarından farklı olabilir. Kanıt, kaynak ve senaryo dosyalarının çalışma sırasında değişmediğini doğrular.

Bu kontrol **yalnız mevcut sentetik dosya modelinin** vardiya, pazar kapanışı, bakım ve W1 fazla mesai politikası içindir. Malzeme mevcudiyeti/MRP, gerçekleşmiş üretim, saha vardiya istisnaları, insan kabulü, maliyet ve hizmet hedefi bağımsız olarak burada doğrulanmadı. Üç senaryonun geçmesi fabrika takvimine uygunluk iddiası değildir.
