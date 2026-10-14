# FDI dar pilot için önceden yazılmış ölçüm protokolü

**Durum:** Şablon; G1 onayı, gerçek snapshot, actuals ve finans kabulü yok. [Pilot sözleşmesi](pilot-charter.md) kapsamı ve karar sahiplerini belirler; bu protokol aynı koşullu karşılaştırmanın nasıl kaydedileceğini tarif eder. [Strateji kararı](validated-strategy-2026-10-14.md) bu işi fabrika öncesi hazırlık olarak tutar.

## 1. G1'de dondurulacak tasarım

Tesis/hat/ürün ailesi, karar çevrimi ve ufuk; mevcut planın sahibi; planlamacının karar anında bildiği sipariş, routing, kaynak, vardiya, duruş ve stok; freeze/başlamış iş politikası; veri erişim izni; değerlendirme dönemi, dışlama nedenleri, örnek sayısı ve KPI eşikleri yetkili rollerce yazılır. FDI'nin sabit makine, tam sipariş, boş WIP ve tek ortak vardiya dosya solver sınırı açıkça kontrol edilir. Uymayan paket için yalnız veri profili/ret raporu üretilir, eşit koşullu solver kıyası yapılmaz.

## 2. Her karar çevriminde kaydedilecek sıra

1. **Snapshot:** Karar zamanı, timezone, kaynak dosya/versiyon/hash, veri sınıfı, şema ve dönüşüm raporu sabitlenir. Gerçek veri yalnız yetkili saklama alanına alınır; depo ve demo fixture'ına konmaz.
2. **Mevcut plan:** Aynı anda geçerli planın kimliği, operasyon/miktar kapsamı, uygulanabilirliği ve eksik alanları bağımsız denetimle yazılır. Eksik veya farklı ufuklu baseline “FDI kazancı” hesabına girmez.
3. **FDI adayı:** Aynı bilgi kesiti ve fizik kurallarıyla çöz; kod/run/solver sürümü, objective, zaman bütçesi, `OPTIMAL`/`FEASIBLE`/`UNKNOWN`, bound/gap varsa kaynağı, ret/fallback ve bağımsız fizik kontrolünü kaydet. `UNKNOWN` veya doğrulanmamış aday ACTIVE/öneri diye sunulmaz.
4. **İnsan kararı:** Öneri, kabul/ret/kısmi kabul/override, gerekçe, onaylayan rol ve gerçekten uygulanmış plan ayrı kaydedilir. Gölge mod üretim sistemine komut göndermez.
5. **Actuals:** Yetkili MES/iş kayıtlarından gerçekleşen başlangıç/bitiş, miktar, duruş, hurda/rework ve maliyet/enerji kaynakları sonradan bağlanır. Eksik actuals açıkça işaretlenir; uygulanmayan önerinin model farkı gerçekleşmiş fayda değildir.

Tarihsel veriyi yeniden oynatmak **çevrimdışı kıyas**, aynı zamanda önerileri göstermeden çalıştırmak **gölge gözlem**dir. İkisinde de FDI önerisinin uygulanmış sonucu yoktur; bunlar A/B testi veya nedensel tasarruf kanıtı diye adlandırılmaz. G10'da gerçekten uygulanan sınırlı bir değişikliğin etkisi incelenecekse karşılaştırma birimi, seçimi, eşzamanlı kontrolü, güvenlik/durdurma kuralı ve dış etkiler G1/G9 sahipleriyle önceden tasarlanır. Bir aylık süre veya belirli örnek sayısı veri görülmeden yeterli ilan edilmez.

## 3. Metrik kartı

Her metrik için formül, pay/payda, birim, zaman penceresi, kapsam, veri kaynağı, eksik veri davranışı ve kabul sahibi G1'de doldurulur. [ISO 22400-1 KPI çerçevesi](https://www.iso.org/standard/56847.html) ortak disiplin için referanstır; FDI'ye sertifika vermez.

| Metrik ailesi | Çevrimdışı aday karşılaştırması | Ancak actuals/finans ile söylenebilecek |
|---|---|---|
| Termin | Aynı sipariş/ufukta aday ve mevcut planın öngörülen geç lot sayısı, toplam/ağırlıklı gecikme | Gerçek teslim veya iş tamamlama gecikmesi |
| Fizik ve kararlılık | Makine/rota/takvim/freeze ihlali; taşınan iş ve başlangıç zamanı kayması | Uygulamadaki kural sapması ve operasyonel müdahale |
| Süre ve güvenilirlik | Solve p50/p95, `UNKNOWN`/timeout, fallback, ACTIVE yaşı ve veri gecikmesi | Sahada kabul edilen SLO ve destek maliyeti |
| Enerji ve maliyet | Varsayımlı kWh, tarife, setup, fazla mesai ve ceza bileşenleri ayrı model senaryosu | Sayaç ve bordro/muhasebe ile uzlaştırılmış gerçekleşen gider |
| Net fayda | Karar öncesi yalnız senaryo farkı; ROI yazılmaz | G11'de uygulanmış kararın onaylı brüt faydası eksi entegrasyon, işletim, destek ve diğer ek maliyetler |

TDABC tarzı süre maliyet farkı yalnız **model sonucu**dur. Finans sahibinin pratik kapasiteyi, kapasite maliyet oranını ve kaçınılabilir/sabit maliyet ayrımını doğrulaması; plan/actuals, fiilî enerji sözleşmesi, fazla mesai, WIP, kalite ve destek giderleriyle mutabakat kurması gerekir. Daha az hesaplanan makine dakikası veya darboğaz zamanı otomatik nakit girişi değildir. [Metodolojik rapor kararı](methodological-defense-review-2026-10-14.md) bu ayrımın gerekçesini kaydeder.

## 4. Geçerlilik ve karar

`FEASIBLE` optimumluk, sentetik başarı müşteri performansı, plan üstündeki maliyet farkı nakit tasarrufu değildir. Karşılaştırma aynı snapshot'a, bilgi anına, siparişlere, kaynaklara, fizik kurallarına ve ufka dayanır; aksi halde “karşılaştırılamaz” kaydedilir. FIFO/EDD/SPT yardımcı referans, fabrikanın fiilî planı ana baseline'dır. Eksik veri ve başarısız çevrimler sonuçtan çıkarılacaksa sayı ve neden önceden belirlenir ve raporlanır; yalnız başarılı aday seçilmez. Saha sonuçları model, tesis, dönem ve örnek sayısı dışında genellenmez.

G1 sahibi protokolü, G8 planlamacı/proses uzmanı fizik ve KPI yorumunu, G9 pilot sahibi insan kararını, G11 finans net faydayı ayrı kabul eder. Bu imzalar yoksa durum [kanıt envanterinde](evidence-register.json) `Bekliyor`/`Çalışılıyor` kalır.
