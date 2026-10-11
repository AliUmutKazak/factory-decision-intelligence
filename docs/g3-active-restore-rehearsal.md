# G3-T: yerel ACTIVE sürümün geçici alanda geri açılması

11 Ekim 2026'da `data/factory.db` içindeki `RUN-20261007-255265` ACTIVE sürümü ve ona ait mühürlü run paketi birlikte sınandı. `src.utils.active_restore_rehearsal`, uygulama yazıcı kilidi altında SQLite backup API'siyle tek sürüm snapshot'ı alır, kaynak bundle manifestini/hash'lerini doğrular, veritabanını ve paketi geçici dizine geri kopyalar. Hem snapshot hem geri açılan veritabanında SQLite bütünlüğü, yabancı anahtarlar, tek ACTIVE run, çizelge ve solver metadata kontrol edilir; paket yeniden hash'lenir. Kaynak DB/bundle değiştirilmez. Bu yerel koşumda `PASS`; kaynak bundle manifest SHA-256 `e66b37a1d7eabc92f5fa92defcf54286d933b45d2d7efe5c42289cede07f642e`.

```powershell
python -m src.utils.active_restore_rehearsal data/factory.db artifacts/runs
```

İki hedefli test, başarılı geçici geri açmayı ve bozuk bundle'ın reddini; ayrı bir test iki süreç arasındaki yazıcı kilidini sınar. Bu testler yerel veriye dayanmaz ve CI'de tekrar edilir.

**Sınır:** Geri açılmış kopya canlı servise geçirilmedi. Uzak saklama, eşzamanlı dış yazıcılar, kesinti sırasında uygulama devri, yedek şifreleme, çok sunuculu yarış, retention ve ölçülmüş RTO/RPO yoktur. [NIST OT yedek rehberi](https://csrc.nist.gov/pubs/sp/1339/final) doğrultusunda gerçek dağıtımda düzenli yedek/restore ve kurtarma tatbikatı ayrıca kabul edilmelidir.
