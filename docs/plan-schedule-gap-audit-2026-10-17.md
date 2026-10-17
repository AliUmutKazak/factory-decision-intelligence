# İlk hafta plan–çizelge farkı: sentetik referans denetimi

Kaynak: mühürlü `artifacts/reference/factory.db` (SHA-256 `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf`), `RUN-20261006-00a0d3`. Bu bir müşteri üretim kaydı değildir.

## Bulgu

`sku_production_plan` birinci hafta için **8.400 adet** hedefliyor. Son operasyonun `end_min <= 10080` koşuluna göre [salt okunur karşılaştırma](../artifacts/research/plan-schedule-consistency-2026-10-17.json) **6.100 adet** birinci hafta içinde, **2.300 adet** daha sonra bitiyor. Sarkan son operasyonlar P02: 100, P04: 1.250 ve P05: 950 adet. Önceki `%100 mutabakat` satırı yalnız bütün planlı adetlerin çizelge ufkuna *yerleştirildiğini* ölçüyordu; hafta sonuna dek bitişi ölçmüyordu.

Referans LP kapasite tablosunda M01 işlem yükü ve izinli kapasite aynı yuvarlatılmış değerde: **134,3 saat**. Sonraki çizelgede M01 toplam işlem süresi 8.053 dakika (134,22 saat), sıra bağımlı hazırlık süresi 235 dakika (3,92 saat). Dolayısıyla LP'nin işlem süresi kısıtı, hazırlık ve operasyonlar arası öncüllük dahil edildiğinde haftalık bitiş garantisi değildir. M02 ve M03'ün toplam işlem yükleri daha düşük olsa da son operasyonları M01'den gelen alt lotları bekleyebilir. Bu değerler M01 baskısını ve operasyonel kısıtları gösterir; farkın tam olarak hangi kısmına hangi kısıtın neden olduğunu tek başına ispatlamaz.

Aynı referans üzerinde, ayrı bellek kopyasında 60 saniye, 4 işçi, tohum 42 ve `BALANCED` amaçla yapılan keşif tekrarında geçerli fakat optimumluğu kanıtlanmamış (`FEASIBLE`, yaklaşık %4,88 bileşik amaç boşluğu) çözüm **6.200 / 8.400** adedi birinci hafta içinde bitirdi; **2.200** adet sarktı. Bu tekrar üretim varsayılanı için bir iyileşme kanıtı değildir: işçi sayısı ve süre birlikte değişti, ayrıca önceki işçi deneyi kısa sürede 4 işçinin daha kötü aday da üretebildiğini göstermişti. Bu nedenle varsayılan çözücü ayarı veya LP tamponu değiştirilmedi.

## Sabit modelde son teslim fizibilitesi

[Ayrı, salt okunur fizibilite deneyi](../artifacts/research/week-one-feasibility-2026-10-17.json) aynı mühürlü girdiyi bellek içinde kopyaladı. Yalnız deney koşusunda bütün operasyonların bitişine sert bir üst sınır eklendi. Tüm alt lotların nihai operasyonu bu sınıra uyacaksa, rota öncüllüğü nedeniyle önceki operasyonları da aynı sınıra uymak zorundadır. Girdi imzası iki koşuda aynı kaldı; kaynak veritabanının hash'i deney başında ve sonunda doğrulandı.

| Sert bitiş sınırı | CP-SAT durumu | Yorum |
|---:|---|---|
| 10.080. dakika (birinci hafta sonu) | `INFEASIBLE` | **Mevcut model, veri ve fazla mesai yetkisi altında** tüm 8.400 adedin ilk hafta bitmesi mümkün değil; bu çözücünün zaman aşımı veya geçerli aday bulamaması değildir. |
| 13.000. dakika (pozitif kontrol) | `FEASIBLE` | Aynı girdilerle sınır içinde geçerli bir çizelge bulundu. Kaydedilen en geç bitiş 11.450. dakika; amaç optimumluğu kanıtlanmadı. |

Her iki koşu 4 işçi, tohum 42 ve 20 saniye sınırıyla yapıldı. İlk koşuda çözücü `INFEASIBLE` durumunu süre dolmadan döndürdü. [OR-Tools durum tanımına](https://developers.google.com/optimization/cp/cp_solver#cp-sat_return_values) göre bu, `UNKNOWN` zaman aşımı değil, **model içi** bir olanaksızlık kanıtıdır. Gerçek fabrikanın kapasite sınırı veya hangi tek kısıtın sorumlu olduğu hakkında kanıt değildir. Pozitif kontrol, deneysel sert bitiş seçeneğinin bütün çizelgeleri yanlışlıkla reddetmediğini gösterir. Deney seçeneği kalıcı çıktı yazarken kullanılamaz; üretim varsayılanı değişmedi.

Tekrar komutu: `python -m scripts.week_one_feasibility_probe --db artifacts/reference/factory.db --run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --deadlines 10080 13000 --time-limit 20 --workers 4 --seed 42 --output <yeni-rapor.json>`. Paralel aramada geçerli adayın zamanları değişebilir; kayıtlı artefakt kendi girdi ve kod hash'lerini taşır.

## Uygulanan düzeltme

- Çizelgeleme paneli, planlanan toplamı, hafta sonunda son operasyonu biten adedi ve sonraya sarkan adedi ayrı gösterir; ürün bazında döküm verir ve bunları fiili üretim olarak adlandırmaz.
- Çizelgeleyici logundaki `%100 mutabakat` ifadesi, miktar mutabakatı olarak düzeltildi; ayrıca ilk hafta bitiş sayısı yazdırılır.
- Tek sentetik örneğe dayanarak talebi, kapasiteyi, fazla mesai iznini veya güvenlik tamponunu yapay biçimde değiştiren otomatik düzeltme eklenmedi.

## Kalan karar

Gerçek tesisin hedef haftası, vardiya ve fazla mesai yetkisi, makine çevrimleri, hazırlık süreleri ve teslimat toleransı bilinmeden bu fark için tek bir doğru parametre seçilemez. Modeldeki hangi kısıtın farkı ne ölçüde oluşturduğunu ayrıştırmak veya alternatif kapasite senaryosu önermek ayrıca araştırılabilir; tek sentetik referanstan işletme kararı türetilemez. Fabrika öncesi karar, farkı açıkça göstermek ve gerçek tesis parametrelerini gelince yeniden sınamaktır.
