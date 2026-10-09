# G5-T: yerel B2MML mesaj teslim sırası ve tekrar denetimi

**Tarih:** 9 Ekim 2026. [Etiketli sentetik paket](../examples/g5-local-messages/manifest.json) iki operasyonun B2MML 0701 `OperationsPerformance` XML mesajını yerel dosyadan okur. Mevcut `mes_from_xml` şema ve fabrika profilini doğrular; kanonik `MESActual` yeniden XML'e yazılıp okunarak round-trip kontrol edilir. Bu işlem veritabanına, ACTIVE plana veya bir MES endpoint'ine yazmaz.

| Teslim dakikası | Mesaj | Operasyonun bitişi | Gecikme | Karar |
|---:|---|---:|---:|---|
| 125 | `m-op2`, operasyon 2 | 120 | 5 dk | Operasyon 1 gelene kadar tamponda |
| 130 | `m-op1`, operasyon 1 | 80 | 50 dk | 1 ve ardından 2 sıra ile serbest |
| 140 | `m-op2` tekrarı | 120 | — | Aynı kimlik ve XML baytları: yok sayıldı |

Manifestteki **60 dakika** teslim gecikmesi sınırı yalnız bu sentetik örneğin beyanıdır; evrensel fabrika hizmet hedefi değildir. Alım sırası `received_min` ile artar, operasyon sırası manifestte açıkça verilir. Önce gelen sonraki operasyon tamponlanır; beklenen önceki operasyon hiç gelmezse paket reddedilir. Aynı `message_id` ile farklı XML, yeni kimlikle aynı operasyon, bitişten önce bildirilen yeni sonuç, yeni mesajda eşik aşımı, ters alım zamanı, operasyon öncüllüğü ihlali, geçersiz/DTD'li XML ve paket dışı dosya yolu reddedilir. Tam tekrar sonraki tesliminde yok sayılır; bu tekrarın gecikmesi ayrı hizmet metriği olarak ölçülmez. Herhangi bir ret halinde `accepted_actuals` boş döner; kısmi aktarım yapılmaz.

```powershell
python -m src.integration.local_message_replay --manifest examples/g5-local-messages/manifest.json --output artifacts/research/g5-local-message-replay.json
```

[Ham kanıt](../artifacts/research/g5-local-message-replay.json) giriş, uygulama ve XML SHA-256 değerlerini, her teslim kararını ve sıraya alınmış iki kanonik gerçekleşeni içerir. Girdi ve kanıt dosyalarının baytları Git checkout'unda korunur; uygulama hash'i LF-normalleştirilmiş içeriktendir. Hedefli testler geçerli akışla birlikte çelişkili tekrarı, farklı kimlikle çift operasyonu, geç/eksik teslimi, bozuk XML'i, güvenilmeyen yolu, ters zamanı ve çakışan operasyonları sınar.

**Uygulama sınırı:** Bu, dosya tabanlı bir teslim laboratuvarıdır. Sonraki [SQLite inbox çalışması](g5-durable-mes-inbox.md) kimlikli `MESIntegrationService.record_event` çağrılarını tekilleştirir; buradaki B2MML/XML mesajları o metoda otomatik aktarılmaz. Retry/ack, gerçek transport, saat eşzamanı, vendor kimlik eşlemesi, B2MML profil uyumu ve saha gecikme eşiği G5 için açık kalır. B2MML actual kaydı operasyon başına topludur; [G6-T olay semantiği](g6-synthetic-execution-replay.md) için kısmi üretim/kesinti akışının yerine geçmez.

OPC Foundation'ın [ISA-95 Job Response modeli](https://reference.opcfoundation.org/specs/OPC-10031-4/6.3.5) iş emri sonucu için kimlik ve gerçekleşen bilgileri ayrı tanımlar. Bu sayfa tasarım bağlamıdır. Buradaki JSON teslim zarfı, 60 dakika eşiği ve tamponlama politikası FDI'nin sentetik test seçimidir; OPC UA veya vendor uyumluluğu iddiası değildir.
