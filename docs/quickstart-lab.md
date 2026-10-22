# Temiz klonda yerel laboratuvar demosu

Bu akış `v0.1.11-lab` sürümünün sentetik/açık veri sınırını gösterir. Python **3.11** gerekir. Gerçek tesis verisi, ERP/MES erişimi veya internete açık servis gerekmez. [Sürüm kimliği ve CI](evidence-register.json) kod değişirse yeniden doğrulanmalıdır.

## 1. Kod ve bağımlılıklar

PowerShell'de:

```powershell
git clone https://github.com/AliUmutKazak/factory-decision-intelligence.git
Set-Location factory-decision-intelligence
git checkout v0.1.11-lab
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.lock
```

Windows'ta `py` başlatıcısı yoksa ve `uv` kuruluysa aynı Python 3.11 ortamı şu komutlarla kurulabilir:

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-windows.lock
```

Linux x86_64 için `python3.11 -m venv .venv` ve `.venv/bin/python -m pip install -r requirements-linux.lock` kullanılır. Paket kurulumu internet gerektirir; tam sürümler lock dosyalarındadır. Kurulum başarısızsa çözüm üretmeye geçmeden Python sürümünü ve paket hata çıktısını kontrol edin.

## 2. Kaynak run ve salt okunur dosya örnekleri

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe scripts/verify_active_run.py
.\.venv\Scripts\python.exe -m src.integration.pilot_preflight examples/pilot-package/manifest.json
.\.venv\Scripts\python.exe -m src.integration.pilot_file_solve examples/pilot-solve/manifest.json --time-limit 5
```

`verify_active_run.py` başarısızsa önceki ACTIVE veya raporu geçerli diye paylaşmayın. Dosya örneği **sentetik**, tek ortak vardiyalı, sabit makineli ve tam siparişlidir; `pilot_preflight`/`pilot_file_solve` fabrika sistemine yazmaz. Komut çıktısında kabul/ret, run kimliği, solver statüsü ve fizik denetimi ayrı okunur. `FEASIBLE` optimumluk kanıtı değildir.

`main.py` laboratuvar akışı için 120 saniyelik çizelgeleme bütçesi kullanır; çözücünün genel 30 saniyelik varsayılanı ve API sınırı değişmez. Daha yavaş makinelerde demo birkaç dakika sürebilir. Süre dolarsa `UNKNOWN` başarısız sonuçtur; ACTIVE korunur ve yeniden deneme ayrıca değerlendirilir.

## 3. Yerel API ve panel

Servisler varsayılan kapalıdır. Üç ayrı rastgele anahtarı aynı PowerShell oturumunda üretin; anahtarları dosyaya veya Git'e yazmayın:

```powershell
$env:FDI_API_READ_TOKEN = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:FDI_API_SCENARIO_TOKEN = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
$env:FDI_API_RESCHEDULE_TOKEN = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up --build -d --wait api dashboard
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8000/api/v1/schedule/current -Headers @{Authorization = "Bearer $env:FDI_API_READ_TOKEN"}
```

Panel `http://127.0.0.1:8501` adresindedir; okuma anahtarını kenar çubuğundaki parola alanına girin. Compose portları yalnız `127.0.0.1` adresine bağlıdır. Docker yoksa [Python servis komutları](demo-and-customer-pilot.md#reproduce-the-technical-demo) kullanılabilir. Servisleri kapatmak için `docker compose down` çalıştırın; bu komut kalıcı `data/`, `reports/` ve `artifacts/runs/` dosyalarını silmez.

## Sınır ve hata yolu

- `401`: eksik/yanlış anahtar; `503`: eksik veya aynı üç anahtar ya da solver timeout; `429`: tek host çözücüsü meşgul. Hatalı sonucu yeni ACTIVE plan diye göstermeyin.
- İlk çalıştırma ve tam kurulum birkaç dakika sürebilir. CI'nın temiz Docker başlangıç/yeniden başlatma kanıtı yalnız [G0'daki aynı commit](fdi-roadmap-execution.md#g0-g13-kapı-matrisi) içindir.
- Gerçek müşteri dosyaları için [veri izni ve saklama kararı](../examples/pilot-package/README.md#gerçek-dosya-gelirse-veri-işleme-sınırı) gerekir; bu örnekler müşteri verisi değildir.
