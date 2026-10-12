# `v0.1.2-lab` temiz klon gösterim provası

12 Ekim 2026'da depo yerel olarak **yeni bir dizine** klonlandı ve `v0.1.2-lab` etiketi (`631719c0a24e724a552ae716e4d6c08d09a6d9f9`) seçildi. Python 3.11 ve `requirements-windows.lock` ile kurulu aynı bağımlılıklar kullanıldı; depo içindeki önceki runtime/ACTIVE dosyaları klona taşınmadı. Prova müşteri verisi içermedi.

| Adım | Sonuç |
|---|---|
| `python main.py` | Sentetik fixture kullanıldı; `RUN-20261012-7cf0e6` 80,55 sn'de ACTIVE yayımlandı. |
| `python scripts/verify_active_run.py` | Veritabanı, fizik, lineage ve bundle hash doğrulaması geçti. |
| `python -m src.integration.pilot_preflight examples/pilot-package/manifest.json` | `SYNTHETIC`; `ACCEPTED`, sıfır ret; manifest ve altı kaynak hash'i raporlandı. |
| `python -m src.integration.pilot_file_solve examples/pilot-solve/manifest.json --time-limit 5` | `SYNTHETIC`; `ASSESSED`, mevcut plan ve aday kıyası; aday `OPTIMAL` ve bağımsız denetim `ACCEPTED`. |
| Yerel API/panel ve Docker restart | Bu Windows ortamında Docker kurulu değil; aynı `v0.1.2-lab` commit'indeki [GitHub CI 38158404770](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/38158404770) temiz Docker başlangıç/yeniden başlatma, `/ready`, yetkisiz ret ve ACTIVE korunumu işlerini geçti. Sonraki ayrıcalıksız container değişikliği de [PR #32 Docker CI 38251690447](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/38251690447) içinde geçti. |

Tam adım sırası [hızlı başlangıçta](quickstart-lab.md) yer alır. Python 3.11 dışındaki sistemler, farklı CPU ve paket sürümleri süre veya çözücü statüsünü değiştirebilir. Hata durumunda doğrulanmamış plan `ACTIVE` sayılmaz. Tek bir sentetik dosya örneğindeki `OPTIMAL`, genel planlama üstünlüğü, gerçek fabrika performansı veya ROI kanıtı değildir.
