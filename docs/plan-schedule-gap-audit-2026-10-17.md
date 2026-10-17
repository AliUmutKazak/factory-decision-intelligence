# İlk hafta plan–çizelge farkı: sentetik referans denetimi

Kaynak: mühürlü `artifacts/reference/factory.db` (SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`), `RUN-20261006-00a0d3`. Bu bir müşteri üretim kaydı değildir.

## Bulgu

`sku_production_plan` birinci hafta için **8.400 adet** hedefliyor. Son operasyonun `end_min <= 10080` koşuluna göre [salt okunur karşılaştırma](../artifacts/research/plan-schedule-consistency-2026-10-17.json) **6.100 adet** birinci hafta içinde, **2.300 adet** daha sonra bitiyor. Sarkan son operasyonlar P02: 100, P04: 1.250 ve P05: 950 adet. Önceki `%100 mutabakat` satırı yalnız bütün planlı adetlerin çizelge ufkuna *yerleştirildiğini* ölçüyordu; hafta sonuna dek bitişi ölçmüyordu.

Referans LP kapasite tablosunda M01 işlem yükü ve izinli kapasite aynı yuvarlatılmış değerde: **134,3 saat**. Sonraki çizelgede M01 toplam işlem süresi 8.053 dakika (134,22 saat), sıra bağımlı hazırlık süresi 235 dakika (3,92 saat). Dolayısıyla LP'nin işlem süresi kısıtı, hazırlık ve operasyonlar arası öncüllük dahil edildiğinde haftalık bitiş garantisi değildir. M02 ve M03'ün toplam işlem yükleri daha düşük olsa da son operasyonları M01'den gelen alt lotları bekleyebilir. Bu değerler M01 baskısını ve operasyonel kısıtları gösterir; farkın tam olarak hangi kısmına hangi kısıtın neden olduğunu tek başına ispatlamaz.

Aynı referans üzerinde, ayrı bellek kopyasında 60 saniye, 4 işçi, tohum 42 ve `BALANCED` amaçla yapılan keşif tekrarında geçerli fakat optimumluğu kanıtlanmamış (`FEASIBLE`, yaklaşık %4,88 bileşik amaç boşluğu) çözüm **6.200 / 8.400** adedi birinci hafta içinde bitirdi; **2.200** adet sarktı. Bu tekrar üretim varsayılanı için bir iyileşme kanıtı değildir: işçi sayısı ve süre birlikte değişti, ayrıca önceki işçi deneyi kısa sürede 4 işçinin daha kötü aday da üretebildiğini göstermişti. Bu nedenle varsayılan çözücü ayarı veya LP tamponu değiştirilmedi. Aynı fiziksel kısıtlar altında bütün 8.400 adedin ilk haftada bitmesinin mümkün ya da imkânsız olduğu da kanıtlanmadı.

## Uygulanan düzeltme

- Çizelgeleme paneli, planlanan toplamı, hafta sonunda son operasyonu biten adedi ve sonraya sarkan adedi ayrı gösterir; ürün bazında döküm verir ve bunları fiili üretim olarak adlandırmaz.
- Çizelgeleyici logundaki `%100 mutabakat` ifadesi, miktar mutabakatı olarak düzeltildi; ayrıca ilk hafta bitiş sayısı yazdırılır.
- Tek sentetik örneğe dayanarak talebi, kapasiteyi, fazla mesai iznini veya güvenlik tamponunu yapay biçimde değiştiren otomatik düzeltme eklenmedi.

## Kalan karar

Gerçek tesisin hedef haftası, vardiya ve fazla mesai yetkisi, makine çevrimleri, hazırlık süreleri ve teslimat toleransı bilinmeden bu fark için tek bir doğru parametre seçilemez. Fabrika öncesinde yapılabilecek sonraki araştırma, aynı sabit girdilerle hafta sonuna tam bitişin fiziksel fizibilitesini ayrı bir karar problemi olarak sınamak ve farklı sentetik yüklerdeki sonuçları raporlamaktır; bunun sonucu dahi saha kabulü sayılmaz.
