# G3-T: PostgreSQL geçiş sözleşmesi ve kabul deneyi

**Durum:** Fabrika bağımsız tasarım; PostgreSQL çalışma zamanı uygulanmış değildir. Mevcut tek sunuculu laboratuvar profili SQLite kullanır. Bu belge, geçiş kararı verildiğinde aynı run izolasyonu ve ACTIVE atomikliğini korumak için doğrulanabilir bir sözleşmedir.

## Korunacak davranış

1. Her planlama girdi/çıktısı tek `run_id` kapsamındadır. Okuyucu bir istekte yalnız bir ACTIVE sürüm görür; eski-yeni satır karışımı yoktur.
2. Solve, fizik/lineage denetimi ve bundle mühürleme bitmeden yeni run görünür olmaz. Başarısız işlem önceki ACTIVE'i korur.
3. Karar/audit kaydı ve yeni ACTIVE kimliği birlikte doğrulanabilir; tekrar gelen olay ikinci planı sessizce yayımlamaz.
4. Eski run paketi okunabilir kalır; geri yükleme yalnız hash ve veri bütünlüğü denetiminden sonra yapılır.

## Mevcut bağımlılık envanteri

| Bileşen | SQLite bağımlılığı | PostgreSQL karşılığına geçiş işi |
|---|---|---|
| `src/utils/db.py` | `sqlite3`, `sqlite_master`, `PRAGMA table_info`, `?` parametreleri | Repository arayüzü, şema/migration yönetimi ve SQL lehçesi ayrımı |
| `main.py` | staging dosyası, SQLite backup, `os.replace` tek yayın noktası | Run satırlarını staging durumunda yükleme; tek transaction ile ACTIVE pointer değiştirme |
| `src/scheduling/rescheduler.py` | disk/bellek SQLite kopyaları, doğrudan SQL ve dosya bundle'ı | Solver'a immutable girdi snapshot'ı; sonuç yazımı ile transaction yayınının ayrılması |
| `src/api/server.py` ve panel | SQLite backup ile istek snapshot'ı, doğrudan tablo sorguları | Transaction başında ACTIVE pointer alma; bütün ilgili okumaları aynı snapshot'ta yapma |
| `src/utils/run_bundle.py` | SQLite dosyasını bundle içine mühürleme | Veri dışa aktarım biçimi, sürüm/şema kimliği ve geri yükleme denetimi |

## Önerilen transaction sözleşmesi

PostgreSQL'de `runtime_state(installation_id PRIMARY KEY, active_run_id, generation)` tek ACTIVE pointer olur; `pipeline_runs` yaşam döngüsü ve `run_id` kapsamlı tablolar ayrı kalır. Yayın anında kısa bir transaction açılır, ilgili `runtime_state` satırı `SELECT ... FOR UPDATE` ile kilitlenir, `generation` ve beklenen önceki `active_run_id` yeniden kontrol edilir, mühürlenmiş/VALIDATED run'a pointer atanır, önceki run arşivlenir, audit ve generation aynı transaction içinde commit edilir. Çakışan publisher yeniden okur; stale baseline üzerine otomatik yayın yapmaz. Uzun CP-SAT solve sırasında transaction veya kilit tutulmaz. [PostgreSQL satır kilitleri](https://www.postgresql.org/docs/current/explicit-locking.html) ve [MVCC](https://www.postgresql.org/docs/current/mvcc-intro.html) bu ayrımın teknik dayanağıdır. Bu tasarım henüz uygulanmış/ölçülmüş değildir.

Okuyucu aynı transaction snapshot'ında pointer ve run verisini alır. Eski sürüm, retention tamamlanana kadar sorgulanabilir kalır. Bundle manifesti veritabanı satırlarından ayrı olarak SHA-256 ile mühürlenir; commit öncesi manifest/run kimliği doğrulanır. Başarısız commit bundle'ı yetim bırakabilir; periyodik denetim yalnız kesin olarak yayımlanmamış yetim paketi güvenli biçimde işaretler, otomatik silmez.

## Geçişi başlatma koşulları ve deney

Karar için eşzamanlı kullanıcı/solve sayısı, veri hacmi, RTO/RPO, backup saklama, şifreleme, IT işletim sahibi ve maliyet ölçülmelidir. Bu girdi olmadan PostgreSQL'i kurmak tek başına bir kalite kazanımı kanıtlamaz.

Geçiş PR'ında aynı mühürlü referansın iki backend'de run kimliği, fizik, KPI ve karar audit karşılaştırması; iki eşzamanlı publisher yarışında yalnız bir generation artışı; yayın öncesi/sonrası süreç çökmesi; yanlış manifest ve yarım restore reddi; eski run'ın okunması; API'nin istek boyunca tek snapshot görmesi otomatik sınanmalıdır. Canlı restore tatbikatı, gerçek RTO/RPO ve operasyon sahibi kabulü daha sonra gerekir. [NIST OT yedek rehberi](https://csrc.nist.gov/pubs/sp/1339/final) yedek almanın yanında düzenli test ve kurtarma tatbikatını vurgular.
