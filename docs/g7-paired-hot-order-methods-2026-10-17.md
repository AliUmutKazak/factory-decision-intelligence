# G7: eşlenik sentetik acil sipariş yöntemi kıyası

**Tarih:** 17 Ekim 2026. Bu deney, [TU/e uyumluluk denetimindeki](tue-dynamic-benchmark-compatibility-2026-10-17.md) sabit rota ilkesini FDI'nin mevcut **tek olaylı** what-if yoluna uygular. TU/e'nin çevrimiçi FJSP sonuçlarıyla ortak benchmark veya fabrika performansı iddiası değildir. Başlangıç planı ve her vaka, mühürlü sentetik veritabanında sabittir; olay zamanı 0'dır. Sonraki olay veya sahadan gelen actuals bulunmaz.

## Önceden belirlenen deney

- [Üç sentetik acil sipariş](../examples/g7-hot-order-stress-cases.json), tohumlar `7, 17, 42`, yöntemler `FULL, FIFO, EDD, SPT`. Her vaka/tohum/yöntem kombinasyonu bir kez çalışır: **36 deneme**.
- Her denemede aynı `ACTIVE` baz çizelgenin yalıtılmış geçici kopyası, 1 CP-SAT worker ve 2 saniye çözücü sınırı kullanılır. Yöntemlerin çalıştırma sırası tohuma göre döndürülür. `FULL` serbest sıralama modelidir; diğerleri seçili sevk sırasına ek kısıt koyan aynı fiziksel CP-SAT modelidir. Bu yüzden sabit sıralı `OPTIMAL`, tam modelin optimumu anlamına gelmez.
- Bağımsız [uygunluk denetimi](g7-independent-candidate-audit.md) reddederse veya çözücü çözüm bulamazsa kalite ve kararlılık istatistiklerine aday eklenmez; başarısızlık paydada ve ham kayıtta kalır.
- KPI'lar: makespan, ağırlıklı toplam gecikme, setup, çözücü süresi, mevcut görevlerin kaçının yeri değiştiği ve mevcut görevlerin mutlak başlangıç kayması. Yeni acil sipariş görevleri hareket sayısına katılmaz. Kabul edilen sonuçların medyan/p25/p75 değerleri doğrusal interpolasyonla hesaplanır; üç tohumun çeyrekleri güven aralığı değildir.

```powershell
python -m src.scheduling.hot_order_method_comparison --db artifacts/reference/factory.db --baseline-run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --cases examples/g7-hot-order-stress-cases.json --seeds 7 17 42 --methods FULL FIFO EDD SPT --scenario-limit 2 --workers 1 --output artifacts/research/g7-paired-hot-order-methods-2026-10-17.json
```

## Sonuç ve yorum

| Vaka | FULL | FIFO | EDD | SPT |
|---|---:|---:|---:|---:|
| Küçük acil P01 | 0/3 | 3/3 | 3/3 | 3/3 |
| Referans P01 | 0/3 | 3/3 | 3/3 | 3/3 |
| Farklı rota P03 | 0/3 | 3/3 | 3/3 | 3/3 |

`FULL` denemelerinin dokuzunda da 2 saniye içinde ilk geçerli çözüm bulunamadı (`UNKNOWN`/timeout); bunların makespan/gecikmesi karşılaştırılmaz. Sabit sıra adaylarının 27'si de bağımsız denetimde kabul edildi; bu yalnız bu üç sentetik olay için geçerlidir. EDD ve FIFO aynı üç vakada aynı medyan makespan (14.149 dk) verdi. SPT'nin medyan makespan'i 14.320 dk idi; farklı rotalı P03 için ağırlıklı gecikmesi EDD/FIFO'dan düşük, diğer iki vakada yüksekti. Tek bir “en iyi yöntem” sonucu çıkmaz; servis ve kapasite ölçüleri farklı yönde hareket edebilir. Her kabul edilen adımda mevcut 31 görevden 31'inin başlangıç zamanı veya makinesi değişti; bu, bu sentetik başlangıç planında önemli kararlılık maliyetidir, gerçek saha davranışı değildir.

[36 denemenin ham JSON kaydı](../artifacts/research/g7-paired-hot-order-methods-2026-10-17.json) her vakayı, tohum/süre/worker ayarını, kaynak ve kod hash'lerini, solver durumunu, bağımsız denetimi, kabul edilen aday metriklerini ve tüm başarısızlık nedenlerini içerir. `git_sha` koşum öncesi checkout'u gösterir; kod ve manifest SHA-256 değerleri UTF-8/LF satır sonuyla normalize edilir, DB hash'i ham baytlardır. Kaynak DB veya manifest deney sırasında değişmedi.

## Kalan sınır

Bu ilk adım **tek acil siparişin zaman 0'da gelişini** ölçer; ardışık sipariş/arıza izleri, freeze ufku ve karar anında gelecek olay bilgisinin kesilmesi henüz karşılaştırmalı benchmark'a bağlanmadı. FULL için daha uzun eşit bütçe ve farklı yükler de değerlendirilmeden kalite üstünlüğü iddia edilemez. Mevcut baseline'ların sabit makine sırası kısıtı, sahadaki planlayıcı davranışının doğrulanmış temsili değildir. Gerçek fabrika kısıtları, saatlik olay frekansı, planlayıcı kabulü ve teslim/finans actuals'ı bu sonuçtan çıkarılamaz.
