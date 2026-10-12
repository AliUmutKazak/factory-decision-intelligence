# G2 güvenlik sınırı ve API yetki envanteri

Durum: **G2 saha kapısı çalışılıyor; G2-lab kanıtı hazır**. Bu kayıt, `FDI_Nihai_Birlesik_Yol_Haritasi.pdf` G2 için mevcut saldırı yüzeyini ve pilot öncesi gerekli kararları tanımlar. API ve panel laboratuvar kullanımı için varsayılan olarak kapalıdır; üç ayrı uzun Bearer anahtarı yapılandırıldığında okuma, senaryo ve yeniden çizelgeleme yetkileri açılır. Docker Compose portları yalnız `127.0.0.1` üzerinde yayımlanır. Laboratuvar image'ı UID 1001 ile ayrıcalıksız çalışır; [v0.1.4-lab main CI 38268272543](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/38268272543) bu kullanıcıyı, temiz başlangıç/yeniden başlatmayı ve erişim anahtarlarının container loglarında görünmemesini doğruladı. Bind-mount dizinlerinin yerel yazma izni kurulumda kontrol edilmelidir. Bu paylaşılan anahtar düzeni kişisel kimlik, tesis kapsamı, TLS veya pilot IT kabulünün yerini tutmaz; internete açılmamalıdır.

## Uç ve asgari yetki

| Uç | Mevcut davranış | Pilot için önerilen rol/sınır |
|---|---|---|
| `GET /health`, `GET /ready` | Sağlık ve hazır olma | Ağ sınırı; hassas ayrıntı vermeme |
| `GET /api/v1/schedule/current`, `GET /api/v1/schedule/solver-metadata` | ACTIVE çizelgesi ve çözüm bilgisi | Laboratuvarda üç anahtardan biri; pilotta yetkili planlamacı/operasyon okuma |
| `GET /api/v1/operations/status` | ACTIVE yayın yaşı ve bekleyen MES niyet sayısı | Laboratuvarda üç anahtardan biri; pilotta yetkili işletim/planlama okuma |
| `GET /api/v1/schedule/audit-log`, `GET /api/v1/decisions` | Karar ve denetim geçmişi | Laboratuvarda üç anahtardan biri; pilotta yetkili denetim/planlama okuma |
| `POST /api/v1/schedule/what-if/breakdown`, `POST /api/v1/schedule/what-if/hot-order` | Senaryo hesabı | Yalnız senaryo anahtarı; pilotta hız/kaynak sınırı ve kayıt |
| `POST /api/v1/schedule/reschedule` | Yeniden çizelgeleme işlemi | Yalnız yeniden çizelgeleme anahtarı; pilotta insan onayı ve geri dönüş kuralı |

Laboratuvar anahtarları farklı rollerin negatif testlerini sağlar. Panel de veri okuma ve doğrudan simülasyon/yeniden çizelgeleme öncesinde aynı yetkileri denetler. Bunlar kişi veya tesis kimliği taşımaz. G1'de fabrika ve IT/MES ile kesinleşecek pilot politikası için issuer, audience, süre, imza, rol ve ilgili tesis/hat kapsamı doğrulanmalıdır.

## Yerel kullanım

`FDI_API_READ_TOKEN`, `FDI_API_SCENARIO_TOKEN`, `FDI_API_RESCHEDULE_TOKEN` ortam değişkenlerini birbirinden farklı ve en az 32 karakterlik rastgele değerlerle ayarlayın. Eksik, kısa veya aynı değerlerden oluşan yapılandırma tüm veri erişimini kapatır (`503`). API çağrılarında `Authorization: Bearer <anahtar>` başlığını kullanın. Panelde anahtarı kenar çubuğundaki parola alanına girin. Okuma anahtarı yalnız okur; senaryo anahtarı okur ve what-if çalıştırır; yeniden çizelgeleme anahtarı okur ve ACTIVE değişikliği ister. Anahtarlar yalnız yerel geliştirme içindir; kaynak koduna veya Git'e eklenmez.

API işleminde aynı anda en fazla bir çözücü çağrısı çalışır; diğer istek `429/SOLVER_BUSY` ve `Retry-After` alır. Ek olarak API, panel ve yerel MES dispatcher aynı DB yolundaki süreçler arası çözücü kilidini kullanır. Panel meşgul durumu kullanıcıya gösterir; hiçbiri bu durumda ACTIVE yayımlamaz. Bu tek hostlu laboratuvar sınırıdır; çok sunuculu dağıtım, küresel kuyruk ve gerçek kullanıcı hız sınırı G7/pilot tasarımında ele alınmalıdır.

## G2 uygulama ve kabul işleri

1. Kimlik sağlayıcısı, token doğrulama yöntemi, anahtar döndürme ve servis hesabı sınırları IT/MES tarafından belirlenir. Kimlik/rol bilgisi eksik veya geçersizse varsayılan davranış ret olur.
2. Her uç için okuma, senaryo ve yeniden çizelgeleme hakları ayrı tanımlanır; tesis/hat kapsamı uygulanır. Üretim talimatı gönderimi G9 gölge modda kapalı kalır.
3. Yetkisiz/yanlış rol/yanlış tesis/geçersiz token için negatif testler, kritik mutation başarısının **sıfır** olduğunu kanıtlar. Audit kaydı kim, ne zaman, hangi run ve hangi kararı istedi bilgisini taşır; hassas veri ve secret loglanmaz.
4. TLS sonlandırma, ağ segmenti, erişim kaydı, secret saklama, container kullanıcı/izinleri ve bağımlılık taraması pilot ortamında gözden geçirilir. Geliştirme kolaylığı için kullanılan yerel port bağlama tek başına güvenlik kabulü sayılmaz.
5. Güvenlik CI sonucu, açıkların sahibi/önceliği ve IT/MES kabulü G2 kanıt paketine eklenir. Bu paket tamamlanmadan dış erişim açılmaz.

Bekleyen girdiler: kimlik sağlayıcısı, pilot dağıtım ağı, rol sahipleri, veri sınıflandırması, saklama süresi ve IT/MES kabul yetkilisi.
