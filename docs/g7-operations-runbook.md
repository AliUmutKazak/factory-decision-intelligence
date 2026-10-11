# G7-T: ACTIVE tazeliği ve yerel işletim yanıtı

Yeni ACTIVE yayını `pipeline_runs.published_at_utc` alanına zaman dilimli UTC anı yazar. `GET /api/v1/operations/status` okuma anahtarı ister ve tek veritabanı snapshot'ından run kimliği, yayın yaşı ve bekleyen MES niyeti sayısını döndürür. Varsayılan `max_active_age_min=1440` yalnız laboratuvar gözlem eşiğidir; fabrika SLO'su değildir. İstek bu eşiği `1..43200` dakika aralığında değiştirebilir. Eski kayıtların naif `timestamp` alanı UTC varsayılmaz.

| Durum | Anlamı | İlk yerel işlem |
|---|---|---|
| `READY` | UTC yayın anı var ve seçilen yaş eşiğinin içinde | Run kimliğini ve `/ready` sonucunu birlikte kaydet. |
| `STALE_ACTIVE` | Yeni ACTIVE yayın eşiği aşmış | Son pipeline/dispatcher sonucu, kaynak veri tarihi ve bekleyen niyetleri incele; otomatik yeni plan yayımlama. |
| `AGE_UNKNOWN` | Legacy run'da geçerli UTC yayın anı yok | Naif timestamp'ten yaş uydurma; doğrulanmış yeni run yayınını ve işletim kaydını bekle. |
| `CLOCK_SKEW` | Yayın anı yerel UTC saatinden 60 saniyeden fazla gelecekte | Host saat senkronizasyonunu ve kayıt kaynağını kontrol et. |
| `pending_mes_intents > 0` | Kalıcı yeniden çizelgeleme niyeti bekliyor | Olay kimliği, türü, duruş süresi ve kaynak run'ı kontrol et; `NEEDS_DURATION`/`NEEDS_EVENT_POLICY` durumlarını insan kararıyla çöz. |
| `429/SOLVER_BUSY` | Bu API sürecindeki tek çözücü yuvası dolu | `Retry-After` süresinden sonra yeniden dene; yük devam ediyorsa eşzamanlılık/worker tasarımını ölç. |
| `503/SOLVER_TIMEOUT` | Geçerli senaryo planı zamanında bulunmadı | ACTIVE'i koru; olay ve çözücü kanıtını kaydet; daha uzun bütçe veya manuel plan kararı için incele. |

`/ready` kaynak veritabanı ve ACTIVE solver metadata durumunu kontrol eder; tazelik eşiğini zorunlu kabul kapısı yapmaz. Buradaki yaş, **yayın anının** yaşıdır; MES actuals akışının güncelliği veya gerçek fabrika planının tazeliği değildir. Çok süreçli panel/API toplam yükü, alarm hedefi, uyarı kanalı ve gerçek SLO fabrika işletim ekibiyle belirlenecek.
