# G5-T: MES yeniden çizelgeleme niyetinin kalıcılığı

**Tarih:** 10 Ekim 2026. Bu sentetik teknik hazırlık, kimlikli MES olayından sonra servis kapanırsa yeniden çizelgeleme ihtiyacının kaybolduğu boşluğu kapatır. `record_event` olay, takip güncellemesi, `mes_external_inbox` ve gerekirse `mes_reschedule_outbox` satırını **aynı SQLite işleminde** yazar. Yazılardan biri başarısızsa hepsi geri alınır.

`MACHINE_DOWN` veya 60 dakikayı aşan görev sapması için çıkış kaydı `PENDING` olur. Aynı dış mesaj tekrar teslim edilirse yeni MES olayı yazılmaz; ancak `PENDING` olduğu sürece `reschedule_required=True` döner. `list_pending_reschedule_intents()` bekleyen olayları eski run'lar dahil sıralar. Önceki sürümden kalan kimlikli inbox satırları ilk erişimde ihtiyatlı biçimde `PENDING` olarak geri kazanılır; daha önce gerçekten işlenmiş olup olmadığı bilinmediğinden otomatik `ACKED` sayılmaz.

`ack_reschedule_intent(event_id, audit_id)` yalnız `reschedule_audit_log` içinde aynı `trigger_event_id` ve kaynak run'a bağlı kayıt, ayrıca bu kaydın yeni run'ı `ACTIVE` veya `ARCHIVED` ise niyeti `ACKED` yapar. Aynı audit ile tekrar ACK etkisizdir; farklı audit reddedilir. ACK'ten sonraki MES tekrarı `reschedule_required=False` döner. İşleyici, `RescheduleTriggerEvent.event_id` alanına MES `event_id` değerini metin olarak koymalı; başarılı ve yayımlanmış yeniden çizelgelemenin audit kimliğiyle ACK vermelidir.

Bu API **işleyici veya gerçek MES bağlantısı değildir**. Bekleyen kaydı bir sürecin okuması, duruş süresini ve freeze kuralını güvenilir sözleşmeden üretmesi, solver'ı çalıştırması ve sonucu ACK etmesi hâlâ gerekir. PENDING iş iki kez işlenmeye çalışılabilir; paralel worker claim/idempotent solver sınırı kurulmadan exactly-once veya otomatik üretim davranışı iddia edilmez. Kimliksiz eski MES çağrıları bu korumaya dahil değildir. G5 saha kabulü açık kalır.

Hedefli testler: yeniden başlatma/tekrar teslim ve run değişimi, ilk sürüm inbox geri kazanımı, yanlış veya yayımlanmamış audit reddi, idempotent ACK, çıkış yazısı hatasında atomik rollback. Komut:

```powershell
python -m pytest tests/test_mes_external_inbox.py tests/test_mes_integration.py tests/test_local_message_replay.py -q
```

Tek SQLite veritabanı sınırındaki atomiklik için [SQLite işlem tanımı](https://www.sqlite.org/lang_transaction.html) kullanılır. Bu kanıt gerçek fabrika olayı, vendor ACK'i veya saha SLO'su değildir.
