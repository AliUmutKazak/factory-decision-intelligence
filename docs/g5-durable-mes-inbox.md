# G5-T: SQLite üzerinde dış MES mesajı tekilleştirme

**Tarih:** 9 Ekim 2026. `MESIntegrationService.record_event` artık `source_system` ve `external_message_id` **birlikte** verildiğinde dış mesajın kimliğini `mes_external_inbox` tablosunda saklar. Bu yol, mevcut `mes_execution_events` kaydı ve `mes_order_tracking` güncellemesiyle aynı SQLite işleminde çalışır. Tablo yeni veritabanında kurulur; mevcut veritabanında ilk kimlikli çağrıda oluşturulur.

Kimlik `(source_system, external_message_id)` çiftidir ve run değişse de korunur. `event_type`, makine, olay zamanı, görev kimliği ve gerekçe kanonik olarak hash'lenir. `MACHINE_DOWN` için isteğe bağlı pozitif tamsayı `outage_duration_min` verilirse hash'e katılır ve `mes_execution_events.actual_duration_min` içinde saklanır. Alan verilmezse önceki hash biçimi aynen korunur; eski mesajların tekrar teslimi çelişki sayılmaz. Aynı kimlik ve içerik tekrarında yeni olay satırı veya tracking güncellemesi yazılmaz; sonuç `DUPLICATE_IGNORED` döner. Yeniden çizelgeleme gerektiren olayda yeni [kalıcı niyet kaydı](g5-reschedule-outbox.md) `ACKED` olana kadar tekrar teslim `reschedule_required=True` döner. Aynı kimliğin farklı içeriği reddedilir. İkinci mesaj yeni kimlikle gelirse ayrı olay sayılır; vendor'ın kararlı mesaj kimliği sağlaması gerekir.

Dış mesaj yolunda yalnız `TASK_START`, `TASK_COMPLETE`, `MACHINE_DOWN` kabul edilir; sonlu ve negatif olmayan olay zamanı aranır. Görev olaylarında `task_id` ile run/makine eşleşmesi doğrulanır. Duruş süresi görev olaylarında veya kimliksiz çağrıda kabul edilmez; bilinmeyen süre için `None` kullanılır, tahmin üretilmez. Eski veritabanında süre kolonu ilk kimlikli MES erişiminde eklenir. Kimliksiz eski `record_event` çağrıları uyumluluk için çalışmaya devam eder ve **tekilleştirme garantisi taşımaz**. Bu yöntem henüz bir B2MML/XML alıcısına veya gerçek transport'a bağlanmış değildir.

```powershell
python -m pytest tests/test_mes_external_inbox.py tests/test_mes_integration.py tests/test_local_message_replay.py -q
```

Bu ilk dilimdeki testler servis yeniden yaratıldıktan sonra mesajın tek satır kalmasını, run değişimini, çelişki reddini, eşzamanlı teslimi ve rollback'i sınadı. Sonraki dilimde bekleyen tetikleme ve doğrulanmış ACK senaryoları eklendi; güncel kapsam ve sınırlar [çıkış kuyruğu notunda](g5-reschedule-outbox.md). Yerel [B2MML teslim replay'i](g5-local-message-replay.md) ayrı salt okunur katmandır.

SQLite'ın [işlem ve rollback belgeleri](https://www.sqlite.org/lang_transaction.html), tek veritabanındaki değişikliklerin tek işlem olarak commit/rollback edilmesinin dayanağıdır. Test edilen güvence yalnız **bu SQLite dosyası içindeki** olay + tracking + inbox + çıkış niyeti yazılarıdır. Dış MES'e gönderilen ACK, ayrı kuyruk, solver çalıştırma veya başka bir veritabanıyla uçtan uca exactly-once sonucu kanıtlanmaz. `original_trigger_reschedule` ilk kararı; çıkış kuyruğu durumu ise henüz onaylanmamış işin varlığını gösterir.

**Açık işler:** Mesaj kimliğinin vendor sözleşmesinde kaynağı ve kapsamı, kimlik doğrulama/rol, B2MML actuals ile bu girişin eşlenmesi, alım zamanı ve saat eşzamanı, gerçek worker/transport ACK, yeniden başlatma ve backup/restore deneyi, gerçek retry yükü ve saha kabulü. G5 kapısı açık kalır.
