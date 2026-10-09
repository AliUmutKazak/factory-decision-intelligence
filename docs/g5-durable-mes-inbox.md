# G5-T: SQLite üzerinde dış MES mesajı tekilleştirme

**Tarih:** 9 Ekim 2026. `MESIntegrationService.record_event` artık `source_system` ve `external_message_id` **birlikte** verildiğinde dış mesajın kimliğini `mes_external_inbox` tablosunda saklar. Bu yol, mevcut `mes_execution_events` kaydı ve `mes_order_tracking` güncellemesiyle aynı SQLite işleminde çalışır. Tablo yeni veritabanında kurulur; mevcut veritabanında ilk kimlikli çağrıda oluşturulur.

Kimlik `(source_system, external_message_id)` çiftidir ve run değişse de korunur. `event_type`, makine, olay zamanı, görev kimliği ve gerekçe kanonik olarak hash'lenir. Aynı kimlik ve içerik tekrarında yeni olay satırı veya tracking güncellemesi yazılmaz; sonuç `DUPLICATE_IGNORED` döner, yeniden çizelgeleme tekrar tetiklenmez. Aynı kimliğin farklı içeriği reddedilir. İkinci mesaj yeni kimlikle gelirse ayrı olay sayılır; vendor'ın kararlı mesaj kimliği sağlaması gerekir.

Dış mesaj yolunda yalnız `TASK_START`, `TASK_COMPLETE`, `MACHINE_DOWN` kabul edilir; sonlu ve negatif olmayan olay zamanı aranır. Görev olaylarında `task_id` ile run/makine eşleşmesi doğrulanır. Kimliksiz eski `record_event` çağrıları uyumluluk için çalışmaya devam eder ve **tekilleştirme garantisi taşımaz**. Bu yöntem henüz bir B2MML/XML alıcısına veya gerçek transport'a bağlanmış değildir.

```powershell
python -m pytest tests/test_mes_external_inbox.py tests/test_mes_integration.py tests/test_local_message_replay.py -q
```

Geçici SQLite veritabanında **17 hedefli test** geçti: servis nesnesi yeniden yaratıldıktan sonra aynı mesajın tek satır kalması; ACTIVE run değişince eski mesajın tekrar yazılmaması; çelişkili kimlik ve geçersiz girdi reddi; eşzamanlı iki gönderimde tek kayıt; tracking veya inbox yazısı başarısız olunca olay, tracking ve inbox değişikliklerinin birlikte geri alınması; makine duruşu tekrarında ikinci reschedule tetiklenmemesi. Yerel [B2MML teslim replay'i](g5-local-message-replay.md) ayrı salt okunur katmandır.

SQLite'ın [işlem ve rollback belgeleri](https://www.sqlite.org/lang_transaction.html), tek veritabanındaki değişikliklerin tek işlem olarak commit/rollback edilmesinin dayanağıdır. Test edilen güvence yalnız **bu SQLite dosyası içindeki** olay + tracking + inbox yazılarıdır. Dış MES'e gönderilen ACK, ayrı kuyruk, solver tetikleme veya başka bir veritabanıyla uçtan uca exactly-once sonucu kanıtlanmaz. Özellikle servis commit'ten sonra, sonucu çağıran taraf yeniden çizelgelemeyi başlatmadan önce kapanırsa inbox tekrar mesajı bastırır ve tetikleme kaçabilir. Bu yüzden otomatik yeniden çizelgeleme için kalıcı tetikleme niyeti/çıkış kuyruğu ve işlem sonrası onay tasarımı gerekir; mevcut `original_trigger_reschedule` alanı yalnız ilk kararı gösterir, işlendiğini kanıtlamaz.

**Açık işler:** Mesaj kimliğinin vendor sözleşmesinde kaynağı ve kapsamı, kimlik doğrulama/rol, B2MML actuals ile bu girişin eşlenmesi, alım zamanı ve saat eşzamanı, kalıcı kuyruk/ACK, yeniden başlatma ve backup/restore deneyi, gerçek retry yükü ve saha kabulü. G5 kapısı açık kalır.
