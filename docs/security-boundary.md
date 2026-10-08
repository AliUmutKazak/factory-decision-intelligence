# G2 güvenlik sınırı ve API yetki envanteri — taslak

Durum: **Çalışılıyor**. Bu kayıt, `FDI_Nihai_Birlesik_Yol_Haritasi.pdf` G2 için mevcut saldırı yüzeyini ve pilot öncesi gerekli kararları tanımlar. Mevcut API'de kimlik doğrulama ve rol denetimi bulunmadığından uygulama yetkili bir pilot ağına henüz açılmamalıdır. Docker Compose portları bu aşamada yalnız `127.0.0.1` üzerinde yayımlanır; doğrudan Uvicorn başlatma, başka Compose override'ları veya farklı ağ yapılandırmaları için aynı koruma otomatik olarak geçerli değildir.

## Uç ve asgari yetki

| Uç | Mevcut davranış | Pilot için önerilen rol/sınır |
|---|---|---|
| `GET /health`, `GET /ready` | Sağlık ve hazır olma | Ağ sınırı; hassas ayrıntı vermeme |
| `GET /api/v1/schedule/current`, `GET /api/v1/schedule/solver-metadata` | ACTIVE çizelgesi ve çözüm bilgisi | Yetkili planlamacı/operasyon okuma |
| `GET /api/v1/schedule/audit-log`, `GET /api/v1/decisions` | Karar ve denetim geçmişi | Yetkili denetim/planlama okuma; veri minimizasyonu |
| `POST /api/v1/schedule/what-if/breakdown`, `POST /api/v1/schedule/what-if/hot-order` | Senaryo hesabı | Yetkili planlamacı; hız/kaynak sınırı ve kayıt |
| `POST /api/v1/schedule/reschedule` | Yeniden çizelgeleme işlemi | Ayrı operasyon yetkisi; onay ve geri dönüş kuralı |

Bu roller uygulanmış bir politika değil, G1'de fabrika ve IT/MES ile kesinleşecek tasarımdır. Özellikle `POST` çağrısının sadece "JWT var" kontrolüyle açılması yeterli değildir; issuer, audience, süre, imza, rol ve ilgili tesis/hat kapsamı doğrulanmalıdır. Dashboard'un kullandığı aynı API yolunda da yetki zorunlu olmalıdır.

## G2 uygulama ve kabul işleri

1. Kimlik sağlayıcısı, token doğrulama yöntemi, anahtar döndürme ve servis hesabı sınırları IT/MES tarafından belirlenir. Kimlik/rol bilgisi eksik veya geçersizse varsayılan davranış ret olur.
2. Her uç için okuma, senaryo ve yeniden çizelgeleme hakları ayrı tanımlanır; tesis/hat kapsamı uygulanır. Üretim talimatı gönderimi G9 gölge modda kapalı kalır.
3. Yetkisiz/yanlış rol/yanlış tesis/geçersiz token için negatif testler, kritik mutation başarısının **sıfır** olduğunu kanıtlar. Audit kaydı kim, ne zaman, hangi run ve hangi kararı istedi bilgisini taşır; hassas veri ve secret loglanmaz.
4. TLS sonlandırma, ağ segmenti, erişim kaydı, secret saklama, container kullanıcı/izinleri ve bağımlılık taraması pilot ortamında gözden geçirilir. Geliştirme kolaylığı için kullanılan yerel port bağlama tek başına güvenlik kabulü sayılmaz.
5. Güvenlik CI sonucu, açıkların sahibi/önceliği ve IT/MES kabulü G2 kanıt paketine eklenir. Bu paket tamamlanmadan dış erişim açılmaz.

Bekleyen girdiler: kimlik sağlayıcısı, pilot dağıtım ağı, rol sahipleri, veri sınıflandırması, saklama süresi ve IT/MES kabul yetkilisi.
