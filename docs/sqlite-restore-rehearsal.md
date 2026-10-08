# G3: mühürlü SQLite referansı için geri yükleme provası

8 Ekim 2026'da `artifacts/reference/factory.db` üzerinde **çevrimdışı laboratuvar** provası yapıldı. Kaynak dosyanın beklenen SHA-256 değeri `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf` olarak zorunlu tutuldu. Kaynak salt okunur açıldı; SQLite backup API'siyle geçici dizine snapshot, oradan ayrı bir geri yüklenmiş kopya oluşturuldu. Her üç veritabanında bütünlük ve yabancı anahtar kontrolleri, kaynak/snapshot/geri yükleme arasında mantıksal döküm hash'i karşılaştırması ve kaynak dosyanın değişmediği kontrol edildi. Geçici kopyalar işlem sonunda silinir; çalışma zamanı `data/factory.db` dosyasına ve ACTIVE sürüme dokunulmaz.

```powershell
python -m src.utils.sqlite_restore_rehearsal artifacts/reference/factory.db --sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf
```

Sonuç: `PASS`, 32 kullanıcı tablosu, bir `pipeline_runs` kaydı, `integrity_check=ok`, `foreign_key_check=ok`; snapshot ile geri yükleme mantıksal SHA-256 değeri eşit. Makine tarafından okunabilir sonuç, kod hash'i ve kullanılan SQLite/Python sürümleri [`artifacts/research/sqlite-restore-rehearsal.json`](../artifacts/research/sqlite-restore-rehearsal.json) içindedir. Küçük geçerli, yanlış hash'li ve WAL yan dosyalı örnekler için üç hedefli test vardır.

**Kapsam sınırı:** Bu araç yalnız hash ile mühürlenmiş, WAL yan dosyası olmayan **tek SQLite dosyası** için provadır. Canlı eşzamanlı yazma, run artifact bundle'ının tüm dosyaları, uzak/kalıcı yedek saklama, şifreleme, gerçek geri dönüş prosedürü, RTO/RPO ve PostgreSQL geçişi sınanmadı. Dolayısıyla G3 saha/işletim kabulü açık kalır. Gerçek veri alınmadan önce bu başlıklar dağıtım ve veri sahibiyle tamamlanmalıdır.
