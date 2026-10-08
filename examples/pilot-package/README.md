# G4-T sentetik dosya pilotu örneği

Bu paket yalnız laboratuvar ön incelemesidir. Gerçek müşteri veya vendor verisi içermez. `manifest.json` kaynağı, zaman başlangıcını ve dosyaları tanımlar. Dakika alanları, zaman dilimi yazılı `origin` anına göredir. Miktar birimi bu örnekte **adet**, işlem süresi **dakika/adet** kabul edilmiştir; gerçek pilotta birim sözleşmesi ayrıca onaylanır.

Proje kökünden çalıştırma:

```powershell
python -m src.integration.pilot_preflight examples/pilot-package/manifest.json
```

Çıktı `ACCEPTED` veya `REJECTED`, dosya SHA-256 özetleri, ayrıştırılan satır sayıları ve hata nedenlerini içerir. İşlem hiçbir dosyayı veya ACTIVE planı değiştirmez. `actuals.csv` isteğe bağlıdır; olmadığı durumda gerçekleşen üretim veya nakit fayda kıyası yapılamaz. Mevcut `actuals.csv` şeması her lot ve operasyon için tek bir toplu kayıt kabul eder; kısmi üretim, kesinti/devam, hurda ve rework olay dizisini henüz temsil etmez (G6-T açık).

Mevcut sınır: yalnız UTF-8 CSV ve kanonik sütun adları desteklenir. Mevcut üretim `routing` tablosu ürün/operasyon başına tek makine tanımladığı için alternatif makine satırları `unsupported_alternative_machine` ile reddedilir. Excel, müşteri sütun eşlemeleri, BOM/stok, fiziksel plan doğrulaması ve solver'a aktarım sonraki teknik işlerdir. Bu ön incelemenin geçmesi G4 müşteri verisi kabulü veya G8 plan kıyası anlamına gelmez.
