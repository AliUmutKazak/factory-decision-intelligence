# Küresel kaynaklarla fabrika öncesi teknik denetim — 11 Ekim 2026

Bu inceleme, FDI'nin birleşik yol haritasındaki fabrika öncesi kapsamı için birincil standart, resmî teknik belge ve özgün araştırma kaynaklarını mevcut kod/kanıtla karşılaştırır. İncelenen kaynaklar dünyadaki tüm çalışmaların eksiksiz listesi değildir. Kaynakların önerileri FDI için otomatik uyumluluk veya saha kabulü oluşturmaz.

| Kaynak / alan | FDI'de doğrulanan durum | Karar ve açık sınır |
|---|---|---|
| [ISA-95](https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard), özellikle [Bölüm 8 bilgi alışverişi profili](https://www.isa.org/products/ansi-isa-95-00-08-2020-enterprise-control-system-i) | B2MML 0701 XSD doğrulaması ve yerel MES olay/niyet akışı var. | Standart şema ile belirli ERP/MES'in mesaj profili eşdeğer değildir. Vendor alanları, ID alias'ları, zaman/birim anlamları, ACK ve red senaryoları G5 saha sözleşmesinde netleşecek; gerçek birlikte çalışabilirlik iddiası yok. |
| [OR-Tools job shop örneği](https://developers.google.com/optimization/scheduling/job_shop) ve [OR-Library](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/jobshopinfo.html) | `ft06` ve birkaç sabit makineli örnek, üretim çözücüsünde ve bağımsız fizik denetiminde sınandı. | Job shop alt problemi genel esnek job shop veya FDI'nin malzeme/takvim/maliyet modeliyle aynı değildir. G8-T sonuçları eşit girdi ve kısıt parmak izi olmadan rakip çözücü üstünlüğü diye sunulmaz. |
| [Yeniden çizelgelemede verimlilik ve kararlılık üzerine özgün çalışma](https://www.sciencedirect.com/science/article/pii/S0360835203000950) | FDI freeze horizon ve başlangıç kayması/nervousness raporu tutuyor. | Akademik kavramla uyumlu bir ölçüm yönü var; FDI'nin ağırlıkları, karar eşiği ve işletme maliyeti fabrika olmadan doğrulanamaz. Daha iyi makespan tek başına kabul koşulu değildir. |
| [OWASP API5 yetki](https://api-security.owasp.org/editions/2023/en/0xa5-broken-function-level-authorization/) | Önce API mutasyonları ve panel erişimi açıktı; yerel üç anahtarlı kapalı varsayılan ve olumsuz rol testleri eklendi. | Paylaşılan laboratuvar anahtarları kullanıcı/tesis kapsamı, IdP veya pilot RBAC değildir. G2 açık kalır. |
| [OWASP API4 kaynak tüketimi](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/) | API pahalı solve uçlarında tek süreçlik eşzamanlılık sınırı ve `429/SOLVER_BUSY` yanıtı eklendi. | Dashboard ayrı süreçte çözer; dağıtık kuyruk, müşteri bazlı hız sınırı ve yük zarfı G7'de hâlâ açık. |
| [NIST SP 800-82 Rev. 3](https://csrc.nist.gov/pubs/sp/800/82/r3/final) ve [NIST 2026 OT Backup Quick Start Guide](https://csrc.nist.gov/pubs/sp/1339/final) | Yerel port sınırı, mühürlü bundle geri yükleme provası ve süreçler arası SQLite yazıcı kilidi testi var. | Ağ/TLS/IT-OT sınırı, gerçek yetkilendirme, canlı yedek ve restore tatbikatı, RTO/RPO ve değişiklik yönetimi fabrika ortamı gerektirir. 2026 Rev. 4, inceleme tarihinde taslaktır; final gibi uygulanmış sayılmaz. |
| [PostgreSQL eşzamanlılık ve kilitleme belgesi](https://www.postgresql.org/docs/current/explicit-locking.html) | Mevcut tek sunucu SQLite yayın noktası ve dosya kilidi vardır. | PostgreSQL'e sadece bağlantı dizgesini değiştirerek geçilemez: dosya kopyası/`os.replace`, `sqlite_master`, `PRAGMA` ve run bundle davranışının işlem/pointer tasarımı gerekir. G3 geçiş kararı ölçülen ölçek ve kurtarma gereksinimine bağlıdır. |
| [NIST Smart Manufacturing Systems Test Bed](https://www.nist.gov/laboratories/tools-instruments/smart-manufacturing-systems-sms-test-bed) | Açık makine/olay verisi için aday kaynak olarak kayıtlıdır. | Veri akışı sipariş, BOM, rota, mevcut plan ve actuals'ın aynı tesiste eksiksiz bulunduğu anlamına gelmez. Üretilmiş bir sentetik birleştirme gerçek müşteri karşılaştırması diye sunulmaz. |

## Bu denetimde düzeltilenler

- API ve panelde yetkisiz erişim/mutasyon sınırı; hata yanıtında iç istisna metni sızıntısı.
- Pahalı API çözücü çağrılarının sınırsız eşzamanlı yürütülmesi.
- Docker build bağlamına yerel `tmp/`, `output/`, PDF ve gizli anahtar dosyalarının girebilmesi.
- [Referans pilot profilindeki](reference-pilot-profile.md) artık yanlış olan “Excel okumaz/eşleme yapmaz” ifadesi; G4-T ön kontrolü açık CSV/XLSX eşlemesini yapar, fakat hâlâ solver aktarımı yapmaz.
- Main CI'de doğrulanmış sentetik run paketinin indirilebilir aday artifact ve SHA-256 kimliği için adım eklendi. Kanıt, yalnız CI başarılı olduğunda mevcuttur; Git etiketi veya container image digest'i sayılmaz.

## Açık kalan fabrika öncesi teknik kararlar

G3'te PostgreSQL sınırı ve canlı ACTIVE geri yükleme yöntemi, G5-T'de gerçek worker/transport yerine laboratuvar dispatcher'ının işletim modeli, G6-T'de rework/WIP için proses varsayımı yapmadan temsil sınırı, G7'de dashboard/API toplam çözücü yükü ve alarm/runbook, G8-T'de daha geniş eşit kısıtlı tekrarlı kıyas ve G0'da release kimliği henüz tam kanıtlanmadı. Bunlar fabrika verisi olmasa da tasarım/deney düzeyinde ilerletilebilir. G1, G4-G8 saha kabulü ve G9 sonrası gerçek pilot/finans sonuçları fabrika katılımı olmadan kapatılamaz.
