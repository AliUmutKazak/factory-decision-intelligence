# G7-T: sentetik malzeme hazır olma zamanı denetimi

**Tarih:** 8 Ekim 2026. [Takvim denetiminden](g7-calendar-candidate-audit.md) sonra acil sipariş adayının malzeme zaman kapısı da bağımsız olarak kontrol edildi. Denetim üretim çözücüsünü çağırmaz; mühürlü kaynak veritabanında ürün–malzeme BOM ilişkilerini ve ilgili run'ın ilk hafta MRP satırlarını yeniden okur.

Bu **mevcut sentetik senaryonun** kuralıdır: `EXPEDITE` satırında tedarikçi hızlandırma 240, mal kabul 120 ve kalite bekleme 120 dakika; negatif planlı salım haftasının her adımı için ek 480 dakika. Diğer satırlarda hazır olma 0 kabul edilir. Ürünün en erken başlangıcı, BOM bileşenlerinin en geç hazır olanına eşittir. Denetim bu değeri her çizelge görevinin `release_time_min` alanıyla eşleştirir ve fiili başlangıcın bundan erken olmadığını kontrol eder. Eksik BOM veya MRP malzemesi, çift MRP malzemesi ve geçersiz salım haftası adayı reddeder. Bilerek bozulmuş release, erken başlangıç ve eksik MRP satırı testte reddedildi.

```powershell
python -m src.scheduling.hot_order_stress_matrix --db artifacts/reference/factory.db --baseline-run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --cases examples/g7-hot-order-stress-cases.json --repeats 3 --scenario-limit 2 --dispatch-rule EDD --output artifacts/research/g7-hot-order-material-release-edd-2s.json
```

[Ham kanıt](../artifacts/research/g7-hot-order-material-release-edd-2s.json): üç etiketli sentetik vaka × üç tekrar = **9/9** sabit EDD sıra alt probleminde `OPTIMAL` ve genişletilmiş bağımsız denetimde **0 ihlal**. Kaynak DB SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`; yürütme commit'i `5b3e10d5d16658da2777a22b0d7852e754afd91e`. Yeniden hesaplanan hazır olma sınırı P01, P02, P04 ve P05 için 480; P03 için 960 dakikadır. Manifest ve kod hash'leri çalıştırılan Windows dosyalarının ham baytlarını gösterir; satır sonu dönüşümünde Git blob hash'inden farklı olabilir.

Bu kontrol **malzeme miktarı, stok rezervasyonu, gerçek açık satın alma siparişi, gerçek mal kabulü, kalite onayı veya tedarikçi güvenilirliğini doğrulamaz**. `EXPEDITE` gecikmeleri sentetik politika varsayımlarıdır; müşteri ERP/MES kaydı veya saha hizmet hedefi olarak sunulamaz. G4/G8 gerçek veri kabulü açık kalır.
