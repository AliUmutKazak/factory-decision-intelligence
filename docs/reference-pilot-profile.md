# G1-T referans üretim profili — laboratuvar kapsamı

Durum: **Teknik taslak**, 7 Ekim 2026. Kaynak: `FDI_Nihai_Birlesik_Yol_Haritasi.pdf` v1.1, bölüm 11-12. Proje sahibinin teyidine göre henüz pilot fabrika, temsilî müşteri verisi veya ERP/MES test erişimi yoktur. Bu profil müşteri kabulü, gerçek tesis modeli veya ROI kanıtı değildir.

## Tekrar üretilebilir referans

| Alan | Bu depodaki referans | Saha için açık karar |
|---|---|---|
| Üretim tipi | Çok operasyonlu, parti bazlı ayrık üretim örneği; 5 ürün (`P01`-`P05`), 2 aile, 3 makine (`M01`-`M03`) | Gerçek ürün ailesi, hat ve proses |
| Master data | Mühürlü `artifacts/reference/factory.db` içinde 13 routing ve 8 BOM satırı | Gerçek operasyon, alternatif makine, malzeme ve birim eşlemesi |
| Talep | `data/fixtures/demand_fixture.csv`: `date,store,item,sales`; 2017-01-01–2017-12-31. Referans DB'de 1.825 ürün-gün sipariş satırı | Gerçek sipariş/lot, due date, değişiklik geçmişi ve talep dönemi |
| Planlama ufku | Kod varsayımı: 4 haftalık taktik plan, 28 günlük forecast | Planlama çevrimi, ufuk ve freeze sınırı |
| Kapasite | Kod varsayımı: haftada 6 gün, günde 2×8 saat; 25 adetlik referans parti | Gerçek vardiya, mola, bakım, setup, operatör ve kalıp/aparat |
| Çizelge | Mühürlü referansta 31 operasyon satırı; CP-SAT varsayılan sınır 30 sn, 1 worker, seed 42 | Pilot solve hizmet hedefi ve eşzamanlı yük |
| Ekonomi/enerji | Parametrik maliyet ve analitik enerji/karbon modeli | Finans tarifeleri, sayaç ve actuals mutabakatı |

Kaynak özeti: `demand_fixture.csv` **Git blob ham baytları** SHA-256 `1df96565675322d028f505beb048ee124c9e52685a96c041fed97b235e625000`; mühürlü `artifacts/reference/factory.db` SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`. Windows checkout satır sonları fixture'ın çalışma kopyası hash'ini değiştirebilir; kaynak kimliği Git blob üzerinden tutulur. Referans run `RUN-20261006-00a0d3`; kendi manifest ve kaynak commit bilgisiyle değerlendirilir. Çalışma anındaki `data/factory.db` ACTIVE sürümü değişebilir ve test sabit referansı olarak kullanılmaz.

## Veri kaynağı envanteri

| Tür | Aday / mevcut kaynak | Uygun teknik sınama | Sınır |
|---|---|---|---|
| Etiketli sentetik | Proje fixture'ları ve mühürlü referans | Uçtan uca sözleşme, fail-safe, fizik ve maliyet kontrolleri | Müşteri performansı, vendor kabulü, nakit fayda göstermez |
| Açık çizelgeleme benchmark'ı | [OR-Library Job Shop](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/jobshopinfo.html) | Ortak problem tanımıyla CP-SAT çekirdek ve çözüm statüsü kıyası | Sipariş geçmişi, BOM, ERP/MES actuals veya ROI kaynağı değildir; dosya ve kullanım koşulu içe almadan önce kaydedilir |
| Açık üretim/tezgâh verisi | [NIST SMS Test Bed](https://www.nist.gov/laboratories/tools-instruments/smart-manufacturing-systems-sms-test-bed) | Olay alımı, zaman damgası, geç/sırasız kayıt ve veri kalitesi denemeleri | Tam planlama zinciri içerdiği varsayılmaz; kullanılacak akış/paket ve koşulları ayrıca seçilir |
| Şema kaynağı | [MESA B2MML-BatchML](https://github.com/MESAInternational/B2MML-BatchML) ve depodaki mühürlü 0701 bağımlılıkları | XSD ve yerel mesaj davranışı | Gerçek vendor profil/endpoint uyumluluğu değildir |

Birden fazla açık/sentetik kaynağı tek bir gerçek fabrika veri seti gibi birleştirmeyeceğiz. Her içe alınan örneğe kaynak türü, kaynak adresi, sürüm/indirme tarihi, lisans veya kullanım koşulu, SHA-256, kapsam, birim/zaman dilimi ve dönüşüm kaydı eklenecek. Müşteri verisi geldiğinde aynı kayıt `gerçek müşteri` olarak ayrı yetki ve saklama kurallarıyla tutulacak.

## İlk dosya pilotunun sınırı

Canlı bağlantı gerektirmeyen ilk değerlendirmede fabrika, tek hat/ürün ailesi için sipariş/lot, miktar, due date, operasyon sırası/süreleri, uygun makineler, vardiya ve bilinen duruşları; ayrıca mevcut planı ve mümkünse gerçekleşen üretimi CSV/Excel ile sağlar. İlgili alanların sahibi, birimi, zaman dilimi ve paylaşım izni yazılır. FDI öneri ve karşılaştırma üretir; üretim sistemine yazmaz.

**Mevcut uygulama sınırı:** `CustomerFileAdapter` bugün yalnız CSV sipariş ve MES actuals nesnelerine dönüştürür. G4-T `pilot_preflight` sipariş, makine, routing, vardiya, mevcut plan ve isteğe bağlı actuals içeren kanonik UTF-8 CSV paketini **salt okuyarak** ön kontrolden geçirir; örnek `examples/pilot-package/` altındadır. Üretim çekirdeği ürün/operasyon başına tek makine kullandığından alternatif makine rotaları ön kontrolde açıkça reddedilir. `actuals.csv` her lot/operasyon için tek toplu satır alır; kısmi üretim ve kesinti/devam olay dizisi G6-T işidir. Bu kontrol henüz müşteri sütun eşlemelerini çözmez, solver'a veri aktarmaz ve Excel okumaz. Dosya pilotu teklifinden önce bu eksikler tamamlanacak; Excel seçilirse açık dönüşüm kuralı ve kaynak dosya hash'i saklanacaktır.

BOM ve stok verilmezse MRP karşılaştırması yapılmaz. Yeterli tarihsel talep yoksa forecast başarısı iddia edilmez. Mevcut fabrika planı olmadan çizelgeleme faydası, actuals ve finans mutabakatı olmadan gerçekleşmiş nakit fayda açıklanmaz. Bu dosya pilotu G4/G8 için veri ve kıyas kanıtı oluşturabilir; G5 vendor entegrasyonunu kapatmaz.

## G1'e geçişte değişecekler

Referans varsayımları fabrika planlamacısı ve IT/MES sahibiyle tek tek doğrulanır veya değiştirilir. Tesis/hat, KPI eşikleri, onay/override/rollback rolleri, veri saklama ve erişim, actuals sıklığı, hizmet hedefi ve finans yöntemi `docs/pilot-charter.md` içinde kabul edilir. G1-T tamamlandı diye G1 kabul edilmiş sayılmaz.
