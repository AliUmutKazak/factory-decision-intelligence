# G8-T: son sürüm koduyla sentetik tahmin geri testi

`v0.1.2-lab` etiketi temiz klonda 12 Ekim 2026'da yeniden çalıştırıldı. Uçtan uca run `RUN-20261012-7cf0e6` ACTIVE olarak doğrulandı. [Makinece okunabilir özet](../artifacts/research/forecast-v012-lab-2026-10-12.json), sentetik talep fixture'ı SHA-256 `1df96565675322d028f505beb048ee124c9e52685a96c041fed97b235e625000`, `train_forecast.py` normalleştirilmiş kod hash'i, ham lineage/metadata hash'leri, dört rolling-origin fold ve basit Naive kıyasını birlikte saklar. Ürün dönemi 2017'dir; koşum tarihi müşteri güncelliği anlamına gelmez.

| Ürün | Seçilen model | Seçilen WAPE | Naive WAPE | Seçilen RMSE |
|---|---|---:|---:|---:|
| P01 | Holt-Winters | 0,0363 | 0,0508 | 8,50 |
| P02 | Holt-Winters | 0,0133 | 0,0153 | 8,56 |
| P03 | Holt-Winters | 0,0185 | 0,0207 | 7,83 |
| P04 | Holt-Winters | 0,0371 | 0,0447 | 8,28 |
| P05 | Naive | 0,0464 | 0,0464 | 8,33 |

WAPE birimsiz hata oranıdır; RMSE ve bias kendi ürün miktar birimindedir. Fold bazlı WAPE, RMSE ve bias ham özette ayrı kayıtlıdır. Seçim yalnız bu sentetik seri, dört ileri zamanlı bölme ve ilgili SKU için geçerlidir; tablo gerçek müşteri tahmin doğruluğu veya genel model üstünlüğü değildir. Sıfır talep ufkunda WAPE tanımsız tutulup RMSE ile seçim yapılmasına ilişkin ayrı [regresyon kanıtı](tr-global-science-market-audit-2026-10-11.md) vardır; bu beş ürün o negatif vakayı temsil etmez. `P10/P90` yöntemi `normal_rmse_heuristic_uncalibrated` olduğundan kalibre kapsama veya servis garantisi iddiası kurulmaz.

Tekrar için `v0.1.2-lab` temiz klonunda [hızlı başlangıç](quickstart-lab.md) akışını çalıştırın. Bu kanıt paketinin eklendiği güncel depodaki `scripts/export_lab_forecast_evidence.py` aracına temiz klonun `data/processed/forecast_model_lineage.csv`, `reports/forecast_model_metadata.json` ve `data/fixtures/demand_fixture.csv` yollarını, ayrıca `--source-commit 631719c0a24e724a552ae716e4d6c08d09a6d9f9` parametresini verin; araç eski `v0.1.2-lab` etiketinde henüz yoktur. Yeni run kimliği veya kütüphane sürümü çıktı baytlarını değiştirebilir; kaynak/kod/veri kimlikleri ve fold metrikleri karşılaştırılmalıdır.
