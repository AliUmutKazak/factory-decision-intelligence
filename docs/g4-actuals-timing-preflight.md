# G4-T: dosya pilotunda gerçekleşen işlem zamanı ve bildirim gecikmesi

**Tarih:** 8 Ekim 2026. Dar kapsamlı [sentetik CSV paketinin](../examples/pilot-package/README.md) salt okunur ön incelemesi genişletildi. `actuals.csv` hâlâ her lot/operasyon için tek toplu kayıttır; bu çalışma olay akışı, kısmi üretim veya MES entegrasyonu değildir.

Ön inceleme, mevcut kimlik/rota kontrollerine ek olarak aynı lotun gerçekleşen operasyonlarında öncüllüğü ve aynı makinedeki işlem aralıklarında çakışmamayı kontrol eder. İsteğe bağlı `reported_min` alanı, olayın sisteme ulaştığı dakikayı manifestteki zaman başlangıcına göre bildirir. Bir lotun sonraki operasyonu önceki operasyondan daha erken bildirilirse `out_of_order_actual_report`; bildirim tamamlanmadan önceyse `reported_before_completion` üretilir. Manifestte **veri sahibi tarafından** `max_actual_reporting_lag_min` verilmişse gerçek bitişten bildirime kadar geçen süre bu sınırla karşılaştırılır ve aşım `late_actual_report` ile reddedilir. Sistem evrensel bir gecikme eşiği varsaymaz.

`reported_min` veya ilan edilmiş eşik yoksa raporun `actuals_timing.status` alanı sırasıyla `NO_REPORTING_TIMES` veya `NO_DECLARED_LAG_LIMIT` olur; gecikme uygunluğu iddia edilmez. `actuals.csv` tamamen yoksa `NO_ACTUALS` kaydedilir. Eşik ilan edilip mevcut satırlarda bildirim zamanı eksikse paket reddedilir.

```powershell
python -m src.integration.pilot_preflight examples/pilot-package/manifest.json
```

[Ham kanıtta](../artifacts/research/g4-actuals-timing-preflight.json) sentetik örnek `ACCEPTED`: işlem 82. dakikada bitmiş, 90. dakikada bildirilmiş, **8 dakika** gözlenen gecikme manifestteki **30 dakika** sentetik sınırın altında. Dosya ve kod SHA-256 değerleri ile yürütme commit'i `62ae0387c83ee5f06f7b886266d8592f48b8f638` kayıtlıdır. Sekiz hedefli test, geç/sırasız bildirim, operasyon öncüllüğü, makine çakışması, eksik zaman alanı ve eşiğin yokluğunu doğrular.

Bu ham kanıt tarihsel commit'e aittir. Güncel örnek `current_plan.csv` dosyasında ayrıca `planned_qty` vardır; güncel dosyanın SHA-256 değeri tarihsel kanıttakiyle aynı değildir.

Bu kabul yalnız dosya yapısı ve tanımlanan laboratuvar zaman kuralları içindir. Gerçek MES olayının kaynağı, saat eşzamanı, veri kesiti eksiksizliği, kesinti/devam, kısmi miktar, rework, operatör düzeltmesi ve fabrika hizmet eşiği ayrı G4/G5/G6 saha kararlarıdır. `reported_min` dışa aktarma zamanı olarak doldurulursa bildirim gecikmesi ölçüsü anlamını kaybeder; gerçek pilotta alanın kaynak semantiği veri sahibiyle onaylanmalıdır.
