# G3: mühürlü run paketinin geri yükleme provası

8 Ekim 2026'da `artifacts/reference/` içindeki `RUN-20261006-00a0d3` referans paketiyle çevrimdışı laboratuvar provası yapıldı. Manifest SHA-256 `6c6a61358608d12d3d374428446621b8dda0156cd20bc0a449dd732d96ecaf6e` girişte zorunlu tutuldu. Paketin kendi `verify_run_bundle` denetimi; kaynakta, geçici snapshot'ta ve ayrı geri yüklenmiş kopyada çalıştırıldı. Geri yüklenen `factory.db` için SQLite bütünlük ve yabancı anahtar denetimleri geçti. Kaynak manifest ve içerik işlem sonunda tekrar doğrulandı. Geçici kopyalar silindi; çalışma zamanı veritabanı ve ACTIVE sürüm değiştirilmedi.

```powershell
python -m src.utils.bundle_restore_rehearsal artifacts/reference RUN-20261006-00a0d3 --manifest-sha256 6c6a61358608d12d3d374428446621b8dda0156cd20bc0a449dd732d96ecaf6e
```

Sonuç `PASS`: 18 manifest dosyası, toplam 675.263 bayt, kaynak/snapshot/geri yükleme doğrulaması ve geri yüklenen DB bütünlük kontrolleri başarılı. Kod hash'i ve makinece okunabilir sonuç [`artifacts/research/bundle-restore-rehearsal.json`](../artifacts/research/bundle-restore-rehearsal.json) içinde. Küçük mühürlü paket için başarılı geri yükleme, yanlış manifest hash'i ve değiştirilmiş içerik ret senaryoları test edildi.

Bu çalışma [tek SQLite dosyası provasını](sqlite-restore-rehearsal.md) genişletir; yine de **canlı kurtarma kabulü değildir**. Eşzamanlı yazılan runtime DB, gerçek/uzak yedek saklama, yetki ve şifreleme, ACTIVE işaretçisinin atomik geri dönüşü, felaket tatbikatı, RTO/RPO ve IT onayı açık kalır. Referans run `COMPLETED` durumundadır; bir üretim kesintisinden gerçek ACTIVE sürüme dönüş burada sınanmadı.
