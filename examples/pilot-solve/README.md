# G4-T/G8-T salt okunur dosya çizelgeleme örneği

Bu bağımsız paket, önceden denetlenen [sentetik dosya pilotu](../pilot-package/README.md) alanlarını kullanır; `actuals` içermez. Böylece tamamlanmış veya devam eden üretim yokmuş gibi varsayarak gerçek WIP'yi yanlışlıkla yeniden planlamaz.

Proje kökünden:

```powershell
python -m src.integration.pilot_file_solve examples/pilot-solve/manifest.json --time-limit 5
```

Örnek tek lot, tek operasyon ve tek makinedir. Beyan edilmiş mevcut plan 80. dakikada, üretim CP-SAT çekirdeğinin bellekte ürettiği aday 20. dakikada tamamlanır. Her ikisinin işlem süresi 20 dakikadır; kaynak vardiyası içinde kalırlar. [Hash ve bağımsız denetim içeren koşum çıktısı](../../artifacts/research/g4-file-pilot-lab-solve-2026-10-11.json) saklıdır. Bu yalnız **sentetik model karşılaştırmasıdır**; müşteri tasarrufu, gerçekleşmiş teslimat veya üretime gönderilmiş talimat değildir. Aday `THROUGHPUT_MAX` ile hesaplanır; gecikme ve bitiş metrikleri ayrı gösterilir. Kaynak dosyalar, mühürlü referans DB ve ACTIVE sürüm değiştirilmez.

Aktarım yalnız şu alt kümede çalışır: `FULL_ORDER` beyanı ve tam/miktarı bilinen mevcut plan, tam sayılı sipariş miktarı ve operasyon süresi, ürün/operasyon başına tek makine, bütün makinelerde aynı ve 24 saat içinde tek kesintisiz vardiya, boş actuals/WIP. Manifestte `lab_model_assumptions` alanı sıfır setup, malzemenin modellenmemesi, bakım/fazla mesai olmaması ve işlerin henüz başlamamış olması varsayımlarını açıkça bildirir. Bu beyan eksikse çözüm başlatılmaz. Üretim modelinin günlük vardiyası kaynak penceresine sabit zaman kaymasıyla eşlenir; aday ayrıca bağımsız rota, süre, sıra, makine çakışması ve kaynak vardiyası kontrolünden geçer. Model daha sonraki güne kayarsa aday ölçümü `INCOMPLETE` kalır. Farklı vardiyalar, setup, BOM/stok, alternatif makine, devam eden iş, rework veya müşteri takvim semantiği için otomatik dönüşüm yapılmaz. Gerçek dosya pilotunda bu alanlar açık veri sözleşmesi ve tesis onayı gerektirir.
