# G7: ardışık olay ve dondurma ufku provası

**18 Ekim 2026.** Mühürlü sentetik referans veritabanından geçici bir kopya alındı. Aynı kopyada olaylar zaman sırasıyla işlendi; ilk olayın doğrulanıp `ACTIVE` yayımlanan çizelgesi ikinci olayın başlangıcı oldu. Kaynak veritabanı değişmedi. Bu, tek politika ve tek olay dizisiyle yapılan yerel provadır; yöntem karşılaştırması veya saha performansı ölçümü değildir.

## Sabit girdi ve tekrar çalıştırma

- Kaynak: `artifacts/reference/factory.db`, ham SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`, baz koşum `RUN-20261006-00a0d3`.
- [Olay dizisi](../examples/g7-reschedule-event-trace.json): dakika 600'de M01 için 120 dakika; dakika 2000'de M02 için 90 dakika sentetik kesinti. Her ikisinde dondurma ufku 120 dakika. İkinci olay ilk yayımdan önce çizelgeleyiciye verilmez.
- Üretim varsayılan yeniden çizelgeleme yolu kullanıldı: yerel onarım denemesi ve gerekirse CP-SAT. Her iki olayda da yerel onarım kabul edilmedi; karar yolu `CPSAT_REOPTIMIZATION` oldu. Solver kaydı 30 saniye, 1 worker ve seed 42 gösteriyor.
- Çözücü adayı bağımsız yeniden çizelgeleme denetiminden, koşum geçerlilik kapısından ve paket mühürlemeden geçti; yalnız bundan sonra `ACTIVE` yayımlandı. Her adım geçici SQLite veritabanında yürütüldü.

```powershell
python -m scripts.probe_reschedule_event_trace --db artifacts/reference/factory.db --sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --baseline-run-id RUN-20261006-00a0d3 --events examples/g7-reschedule-event-trace.json --output artifacts/research/g7-two-event-freeze-2026-10-18.json
```

## Gözlenen sonuç

| Olay | Önceki → yeni `ACTIVE` | Dondurulan görev | Yeri değişen görev | Ortalama mutlak başlangıç kayması | Toplam çalışma |
|---|---|---:|---:|---:|---:|
| M01, dakika 600 | `RUN-20261006-00a0d3` → `TRACE-01` | 1/31 | 29/31 | 1.765,35 dk | 42,02 sn |
| M02, dakika 2000 | `TRACE-01` → `TRACE-02` | 3/31 | 28/31 | 2.147,58 dk | 40,89 sn |

İki olay da kabul edildi; son tek `ACTIVE` sürüm `TRACE-02` oldu. Bu hareket büyüklüğü, sentetik planın **kararlılık maliyetini** gösterir; daha iyi teslimat veya parasal fayda kanıtı değildir. Çalışma süreleri bu bilgisayarın uçtan uca laboratuvar süreleridir, hizmet seviyesi hedefi değildir.

[Ham sonuç](../artifacts/research/g7-two-event-freeze-2026-10-18.json) olayları, her adımın solver metadatasını, karar yolunu, hareket ölçülerini ve kaynak/kod SHA-256 özetlerini içerir. Geçersiz kaynak özeti, yinelenen/sırasız olay veya başarısız yayın sonrası başka olaya devam etme reddedilir. Windows'taki geçici dosya kilidi de çıktı okuma bağlantısını açıkça kapatan düzeltme ve regresyon testiyle giderildi.

## Açık sınır

Tek iz, olay sıklığı veya yöntem üstünlüğü çıkarımı için yeterli değildir. Aynı fiziksel modelde farklı olay dizileri, farklı dondurma ufukları, eşit çözüm bütçeli yöntemler ve başarı/timeout paydalarıyla genişletilmiş karşılaştırma gerekir. Saha actuals'ı, başlamış işin miktarı, WIP, rework, operatör ve malzeme durumu bu provada yoktur. Müşteri yükü ve kabulü bekleniyor.
