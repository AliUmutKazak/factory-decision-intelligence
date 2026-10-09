# G6-T: kısmi üretim ve kesinti/devam için sentetik olay denetimi

**Tarih:** 9 Ekim 2026. Bu laboratuvar örneği tek lotun tek operasyonunu, tek makinede, tam sayı **adet** ve sentetik dakika ekseninde yeniden oynatır. `src.execution.synthetic_replay` yalnız JSON okur ve rapor üretir; çizelgeleme motoruna, ACTIVE plana, veritabanına veya MES'e yazmaz. `examples/pilot-package/actuals.csv` hâlâ operasyon başına toplu bir gerçekleşen kayıttır; bu olay akışı onun yerine otomatik alınmaz.

## Elle doğrulanabilir vaka

[Girdi](../examples/g6-partial-interruption.json) 10 birimlik `EX-L1` / operasyon 1 / `EX-M1` örneğidir:

| Dakika | Olay | Sağlam | Hurda | Kalan | Durum | Freeze |
|---:|---|---:|---:|---:|---|---|
| 60 | START | 0 | 0 | 10 | RUNNING | Evet |
| 70 | PRODUCE 4 | 4 | 0 | 6 | RUNNING | Evet |
| 72 | INTERRUPT | 4 | 0 | 6 | INTERRUPTED | Evet |
| 90 | RESUME | 4 | 0 | 6 | RUNNING | Evet |
| 100 | PRODUCE 5 | 9 | 0 | 1 | RUNNING | Evet |
| 102 | SCRAP 1 | 9 | 1 | 0 | RUNNING | Evet |
| 105 | COMPLETE | 9 | 1 | 0 | COMPLETED | Hayır |

Kural: her kabul edilen üretim/hurda olayı miktarı **bir kez** ekler; `remaining = planned - good - scrap` hiçbir zaman negatif olamaz. Aynı `event_id` ve aynı içerik tekrar gelirse yok sayılır; aynı kimliğin farklı içeriği reddedilir. Yeni olay zamanları geriye gidemez. Üretim/hurda yalnız RUNNING durumunda; COMPLETE yalnız kalan sıfırken kabul edilir. Bu freeze alanı, çalışmaya başlamış lotun otomatik taşınmaması için **laboratuvar işareti**dir; motorun fiilî freeze kuralı veya fabrika onayı değildir.

```powershell
python -m src.execution.synthetic_replay --input examples/g6-partial-interruption.json --output artifacts/research/g6-partial-interruption-replay.json
```

[Ham rapor](../artifacts/research/g6-partial-interruption-replay.json) olay başına durum ve miktarı, tekrarı, girdi ham baytlarının ve uygulama dosyasının LF-normalleştirilmiş içeriğinin SHA-256'sını verir. Girdi ve rapor Git checkout'unda baytları korunacak şekilde işaretlenmiştir. Beş hedefli test elle hesaplanan ara/son durumu, aynı olayın yeniden gelişi, çelişkili kimlik, yanlış geçiş, eksik/fazla miktar, ters zaman ve desteklenmeyen REWORK olayını sınar. Sonuç `ACCEPTED` olsa bile akış eksik kalabilir: `final_state` ve `remaining_units` ayrıca okunmalıdır; bitmiş üretim yalnız `COMPLETED` durumudur.

**Açık proses kararları:** Rework burada açıkça `unsupported_event` ile reddedilir; hurdanın yeniden işlenebilirliği veya yeni rota/miktar doğurması varsayılmaz. Başlamış işin başka makineye aktarımı, kesinti boyunca setup korunumu, WIP, kalite kararı ve kısmi tamamlamanın sonraki operasyona aktarımı tanımlı değildir. Proses uzmanı ve gerçek olay sözleşmesi olmadan G6 saha kapısı kapanmaz. Bu vaka ne solver'ın kesintiyi hesaba kattığını ne de MES round-trip'ini kanıtlar.

ISA-95'in [imalat operasyonları yönetimi çerçevesi](https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard) ve OPC UA ISA-95 [job response/status](https://reference.opcfoundation.org/specs/OPC-10031-4/6) modeli olayların sözleşme düzeyinde ele alınması için bağlam sağlar. Yukarıdaki durum geçişleri, `event_id` kuralı ve miktar denklemi **FDI'nin sentetik laboratuvar seçimidir**; bu kaynaklardan birebir standart uygunluğu veya sertifikasyon iddiası çıkarılmaz.
