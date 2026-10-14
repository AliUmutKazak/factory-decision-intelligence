# Fabrika öncesi teknik kapsam ve teslim ölçüsü

Bu kayıt, birleşik yol haritasının **paylaşılabilir tek sunuculu laboratuvar POC** hedefi için alınan teknik kapsam kararlarını açıklar. G0–G13 saha kapılarının kabul kaydı [yol haritasında](fdi-roadmap-execution.md) tutulur. Fabrika, müşteri verisi veya ERP/MES test erişimi olmadan müşteri KPI'sı ve üretim uygunluğu onaylanamaz.

## Üretilen laboratuvar kanıtı

| Alan | Tekrarlanabilir kanıt | Kapsam |
|---|---|---|
| Uçtan uca karar zinciri | `python main.py`, `python scripts/verify_active_run.py`, tam pytest/CI | Sentetik referans; forecast → LP → MRP → CP-SAT → karar/audit/analitik |
| Güvenli ACTIVE sürümü | Değişmez run bundle, hash doğrulaması, atomik yayın, yedek/restore provası, hata testleri | Tek host SQLite; gerçek tesis felaket kurtarma hedefi değil |
| Dış fizik kıyası | [OR-Library sabit makineli JSP](external-jsp-benchmark.md) ve bağımsız aday denetimi | Küçük örnekler optimum; `ft10` süre/kalite sınırı görünür |
| Dosya değerlendirme yolu | [CSV/XLSX ön kontrolü](../examples/pilot-package/README.md) ve [dar solver aktarımı](../examples/pilot-solve/README.md) | Tam sipariş, tek ortak vardiya, sabit makine, actuals/WIP yok; bellekte, salt okunur |
| Yerel olay yolu | MES inbox, kalıcı yeniden çizelgeleme niyeti ve tek olay dispatcher'ı | Vendor bağlantısı veya otomatik tesis komutu yok |
| Güvenlik ve işletim | Varsayılan kapalı üç yerel erişim rolü, çözücü yuvası, tazelik ucu, [bağımlılık taraması](dependency-security-2026-10-11.md), [G7 sentetik yük/hata zarfı](g7-v012-lab-envelope.md), Docker restart CI | Yerel demo; IdP, TLS/OT ağı ve çok hostlu SLO yok |

## Fabrika öncesi ürün kararları

1. **SQLite tek host:** Bu sürümün dosya pilotu ve yerel demo yükü için repository/restore sınırı test edilir. [PostgreSQL geçiş sözleşmesi](g3-postgresql-migration-design.md) hazırdır. Eşzamanlı çok hostlu kullanım veya saha IT mimarisi belirlenmeden ayrı bir PostgreSQL runtime yayımlanmaz; böyle bir kurulum bu sürümün desteklenen kapsamı değildir.
2. **Dosya önce:** Müşteri test tenant'ı olmadan sahte ERP/MES transport ve ACK kanıtı üretilmez. Yerel dispatcher yalnız tekrar, sıra, durum ve geri kazanım semantiğini sınar. İlk görüşmede salt okunur dosya akışı teklif edilir.
3. **Bilinmeyen proses kuralı reddedilir:** Başlamış/kısmi iş, WIP taşıma ve rework için fabrika semantiği yoksa dosya solver yoluna alınmaz. Desteklenmeyen olayın sessizce tam sipariş gibi çizelgelenmesi kabul edilmez.
4. **Ölçüm dürüstlüğü:** `FEASIBLE` optimumluk değildir; 9.14'ün 30 saniyelik `ft10` negatif sonucu korunur. 9.15 sürümünde [30 ve 60 saniyelik tekrarlar](external-jsp-benchmark.md#or-tools-915-sürümünde-yeniden-ölçüm) yapıldı; 30 saniyede aday kalitesi değişken, 60 saniyede üç aday 930 fakat solver statüsü yine `FEASIBLE` kaldı. Sentetik kıyas müşteri baz çizelgesi, gerçekleşmiş tasarruf veya ROI yerine geçmez.
5. **Tek host işletim:** Yerel kilit ve `429/SOLVER_BUSY` bu dağıtımın eşzamanlılık sınırıdır. Çok host, kurumsal alarm/kimlik ve saha RTO/RPO ancak somut pilot mimarisiyle tasarlanır; bu sürüm internete açık üretim servisi olarak sunulmaz.

## Paylaşım kararı

Paylaşılabilir ifade: **“Tek sunuculu, sentetik/açık veride tekrar üretilebilir endüstriyel karar destek POC'si; sınırlı salt okunur dosya pilotu hazırlığı var.”** Teknik sürüm için aynı commit üzerinde tam CI, Docker temiz başlangıç/yeniden başlatma ve doğrulanmış run artifact kimliği gerekir. Sürüm etiketi bu kanıtın alındığı main commit'ine bağlanır. [Paylaşım kartı](release-evidence-and-field-boundary.md) gösterim kontrol listesidir.

Fabrika bulunduğunda G1 kapsam/KPI/rol onayı, G4–G8 gerçek veri ve vendor deneyi, G9 gölge gözlem, G10 kontrollü işletim, G11 finans uzlaştırması ve G12 ikinci tesis kanıtı ayrı yapılır. Bu işleri laboratuvar sonucuyla tamamlandı olarak işaretlemeyiz.
