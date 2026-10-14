# Nihai gelişim raporu: güncel kanıtla karar

Kaynak: kullanıcının verdiği dokuz sayfalık `FDI_Nihai_Gelisim_Karari_ve_Yol_Haritasi_2026-10-14.pdf`, SHA-256 `86636ba985bff272a4de24d1bd2a36f91f8d13456bef301a7e0ec8047719b894`. Raporun önerileri proje talimatı veya saha kabulü sayılmadı; her öneri kod, test, kanıt kaydı ve birincil kaynaklarla karşılaştırıldı. Bu kayıt raporun yazıldığı andan sonraki repo durumunu açıklar.

## Karar ve zaman farkı

Rapordaki ana karar uygundur: FDI bugün **tek sunuculu, sentetik/açık veride çalışan laboratuvar karar destek POC'si** olarak paylaşılır. İnternete açık üretim servisi, evrensel ERP/MES adaptörü, optimumluk veya müşteri tasarrufu iddiası yapılmaz. Bu sınır [fabrika öncesi teknik kapsam](prefactory-technical-closure.md) ve [G0–G13 kanıt kaydında](fdi-roadmap-execution.md) zaten korunuyor.

Raporun sayfa 3, 6 ve 8'indeki `v0.1.4-lab` ve “main CI/artifact bekleniyor” bilgisi artık tarihsel. `v0.1.6-lab`, `f3350772...` commit'i için [main CI 38497838377](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/38497838377) 344 test, Docker başlangıç/yeniden başlatma ve sentetik artifact kanıtı verdi. [Temiz Windows klon provası](clean-demo-v016-2026-10-14.md) uçtan uca ACTIVE ve dar dosya örneklerini doğruladı. Bu kanıt **o commit'e** aittir; daha yeni kod otomatik olarak aynı sürüm kabulünü devralmaz.

Bu incelemeden sonra panel düzeltmesini içeren `v0.1.7-lab` (`a6cbe65f3bae4fe4972ec7faed3e64db0d4e69b4`) ayrıca doğrulandı: [main CI 38556658542](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/38556658542) 344 test ve Docker işlerinde başarılı; [yeni temiz klon provası](clean-demo-v017-2026-10-14.md) ACTIVE ve dar dosya akışını geçti. Güncel kimlik [kanıt envanterindedir](evidence-register.json).

| Rapordaki öneri | Nesnel sonuç | Bu turdaki karar |
|---|---|---|
| P0 sürüm kanıtı ve temiz demo | `v0.1.7-lab` için tamam | Sonraki kaynak kodu için CI ve temiz demo ayrı izlenir. |
| Solver status, amaç, bound ve gap görünürlüğü | Alanlar backend ve API'de vardı, panelin ana çizelge bölümünde amaç/bound/gap görünmüyordu. | Panelde ACTIVE run'a bağlı “Çözücü kanıtı ve sınırı” görünümü eklendi. `FEASIBLE` optimum diye sunulmaz; boşluk yalnız model amacı içindir. |
| Problem keşfi, dar dosya sözleşmesi, güvenli yerel demo | Rehber, ön kontrol, sınırlar ve localhost güvenliği kayıtlı | Yeni müşteri bulgusu varmış gibi yazma. Görüşme ve saha kabulü açık kalır. |
| İnsan onayı | Laboratuvar `reschedule` anahtarı isteği başlatır ve başarılı adayı doğrudan ACTIVE yapar. Ayrı aday inceleme/kabul adımı mevcut değildir. | Panel ve kullanım belgelerinde bu durum açık gösterilir. G9/G10 için gerçek planlamacı kabulü ayrı tasarlanır; bugünkü token kullanımına “saha insan onayı” denmez. |
| Monte Carlo, başlangıç ipucu, AI, edge/cloud, genel FJSP | Veri ve aynı koşullu kazanım kanıtı yok; bazıları saha kuralına bağlı | Varsayılan ürün kapsamına eklenmez. Sadece tanımlı hipotez olarak tutulur. |
| SHA-256 “imza” söylemi | Hash, güvenilir referansa göre bütünlük kontrolüdür; imzalayan kimliği vermez. | README ve bundle kaydı zaten bunu ayırıyor; ek kriptografi iddiası eklenmez. |

## Global uygulama ve araştırmadan alınan ders

- [Google OR-Tools CP-SAT belgeleri](https://developers.google.com/optimization/cp/cp_solver) `OPTIMAL`, `FEASIBLE` ve `UNKNOWN` ayrımını yapar. FDI panelinin çözüm statüsü, amaç değeri ve alt sınırı birlikte göstermesi bu ayrımı kullanıcıya taşır. Yüzde boşluk, teslimat/enerji/para sonuçlarının her biri için garanti değildir.
- [Timefold'un score analysis belgeleri](https://docs.timefold.ai/timefold-solver/latest/constraints-and-score/understanding-the-score) sayısal skoru kısıt katkıları ve gerekçelerle açıklamayı ayrı bir yetenek olarak ele alır. FDI'de LP bağlayıcı kapasite ve karar izi vardır; CP-SAT için “bu sipariş şu yüzden gecikti” nedensel açıklaması henüz yoktur. Yalnız sonuç ve model varsayımı gösterilir; sahte kısıt nedeni üretilmez.
- [Siemens Opcenter APS](https://www.siemens.com/en-us/products/opcenter/advanced-planning-scheduling-aps/advanced-scheduling-software/) malzeme, alternatif kaynak, sıra bağımlı değişim ve plan/gerçekleşme görüntüleme yeteneklerini belgeler. [PyJobShop'un FJSP tanımı](https://pyjobshop.org/latest/examples/flexible_job_shop.html) her operasyon için uygun makineler arasından seçim gerektirir. FDI'nin sabit makineli ve dar dosya profili bu kapsamlarla eşdeğer değildir; alternatif kaynak kuralları saha verisiyle seçilir.
- [Oracle Production Scheduling uygulama rehberi](https://docs.oracle.com/cd/E18727_01/doc.121/e27241/T581889T582279.htm) onay ve yayını ayrı işlemler olarak anlatır. FDI'nin laboratuvar otomatik ACTIVE geçişi bununla aynı kontrol değildir. İnsan kabul/ret ve yayımlama ayrımı ilk gerçek pilotun G9/G10 tasarım gereğidir.
- Jeffrey W. Herrmann'ın [üretim çizelgelemesinde bilgi akışı ve karar verme çalışması](https://isr.umd.edu/Labs/CIM/projects/ierc2004/ierc256.html), çizelgelemeyi tek başına optimizasyon hesabına indirgemez. FDI'nin aynı snapshot, karar sahibi, insan değerlendirmesi ve actuals zincirini ayrı ölçmesi bu yöntemle uyumludur; makale FDI'ye onay vermez.
- NIST araştırmacıları Moneer Helu ve Thomas Hedberg'in [üretim verisini toplama ve yeniden kullanma önerileri](https://www.nist.gov/publications/recommendations-collecting-curating-and-re-using-manufacturing-data-0) ile [SMS Test Bed](https://www.nist.gov/laboratories/tools-instruments/smart-manufacturing-systems-sms-test-bed), veri kökeni ve bağlam ihtiyacını destekler. Testbed makine/ürün yaşam döngüsü verisi sağlar; FDI için tam sipariş-BOM-route, müşteri baz planı veya ROI verisi yerine geçmez.
- [NIST OT güvenliği rehberi](https://csrc.nist.gov/pubs/sp/800/82/r3/final) tesise göre tehdit, güvenilirlik ve ağ mimarisi değerlendirmesini gerektirir. Hava boşluğu, edge veya bulut konusunda evrensel seçim yapılmaz. [MESA B2MML 0701 şemaları](https://github.com/MESAInternational/B2MML-BatchML) XML sözleşmesi sağlar; vendor kabulü ayrıca gerekir.

## Sonraki karar kapısı

Fabrika öncesi ürün sınırını genişletmek için genel bir gerekçe bulunmadı. Dış erişim veya otomatik MES yayını açılmadan önce gerçek bir kullanıcı problemi, veri izni, proses kuralları ve güvenlik sahibi belirlenir. G9'da öneri, planlamacı kabul/ret kaydı, gerçekten uygulanmış plan ve actuals ayrı tutulur. G10'da aday planı inceleme ile yayımlama birbirinden ayrılır. Finansal fayda ancak G11'de uygulanmış karar ve maliyet mutabakatıyla ileri sürülür.
