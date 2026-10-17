# 17 Ekim 2026 bilimsel raporunun bağımsız denetimi

Kaynak: kullanıcının sağladığı `FDI_Bilimsel_Inceleme_ve_Gelistirme_Raporu.pdf`, SHA-256 `45ad846f5e46995fdf597f35de902880a171be5ad4d10aff62913887bd3e1d71`. Raporun incelenen commit'i `454f42b`. Rapordaki öneriler uygulama talimatı veya doğrulama kanıtı kabul edilmedi; mevcut kod, mühürlü sentetik referans, testler ve aşağıdaki birincil kaynaklarla karşılaştırıldı.

## Doğrulanan ve düzeltilenler

| Bulgu | Denetim kararı | Bu turdaki işlem / sınır |
|---|---|---|
| F1 tek işçi ve çözüm boşluğu | **Doğru gözlem, neden kanıtlanmadı.** `FEASIBLE` optimum demek değildir; işçi sayısı ile gevşek alt sınırın payı ayrıştırılmadı. | İşçi/tohum parametresi yalnız açık deney çağrısında değiştirilebilir. Ayrı süreçte çökmeyi de kaydeden, SHA-256 ile girdi doğrulayan koşucu eklendi. Üretim varsayılanı 1 işçidir. |
| F2 iki ayrı stok hesabı | **Doğru ve sunumda yanıltıcı.** Günlük RMSE çarpanı malzeme tedarik süresi stoku değildir. Dört planlı haftanın dağılımından %95 servis düzeyi çıkmaz. | Kullanılmayan `recommended_safety_stock` yeni tahminlerden kaldırıldı. Tahmin satırlarına `interval_calibrated=false` ve yöntem; MRP çıktısına `safety_stock_method=planned_requirement_dispersion_heuristic_uncalibrated` eklendi. Panel ve sözlük düzeltildi. Kalibre edilmiş stok formülü iddia edilmez. |
| F7 dar benchmark | **Doğru.** Önceki 3 tekrar ve tek tohum yalnız ham gözlemdir. `p95` hesaplanabilir ama n=3 ile kuyruk performansını güvenilir ölçmez. | Yeni çoklu tohum/işçi koşucusu ham adayları, çıkış kodunu, fizik denetimini ve medyanı kaydeder; küçük örnek için kuyruk yüzdeliği raporlamaz. Genel ölçek eğrisi henüz yoktur. |
| F4 LP–çizelge farkı | **Ölçülebilir önemli boşluk.** Referans LP hedefi ile aynı hedefin haftanın sonuna dek çizelgelenen bitişi farklıdır. | [Salt okunur KPI](../artifacts/research/plan-schedule-consistency-2026-10-17.json): 8.400 planlı adet, 6.100 adet haftanın 10.080. dakikasına kadar bitiş, 2.300 adet sonrası. Bu bir *çizelgelenen* bitiş ölçüsüdür; fiili üretim değildir. %10 tamponu tek örneğe göre yeniden ayarlanmadı. [Ayrıntılı neden ve görünürlük denetimi](plan-schedule-gap-audit-2026-10-17.md). |
| F14 maliyet sunumu | **Mutlak fark doğru, yüzdelik önerisi seçici olabilir.** Demo CP-SAT ve EDD aynı 1.845.155 € malzeme, 6.821,67 € temel işçilik ve 600 € expedite varsayar. | 3.820,89 € modellenmiş farkın bileşenleri: gecikme 3.255 €, stok tutma 477,57 €, setup 63,33 €, enerji 16,76 €, karbon 5,31 €, fazla mesai 2,91 €. Bunlar *aynı sentetik snapshot'ta modellenmiş maliyet farklarıdır*; yeni bir “değişken maliyet tasarrufu yüzdesi” veya gerçekleşmiş ROI üretilmez. |

## Rapordaki diğer öneriler için karar

| Kod | Karar ve gerekçe |
|---|---|
| F3 | Daha fazla origin ve aday model araştırma deneyi olabilir. 365 günlük sentetik seri, 28 günlük çakışan ufuklar ve tek holdout ile DM/HLN anlamlılık testi veya yıllık mevsimsellik üstünlüğü ilan edilmez. Mevcut seçim/holdout ayrımı korunur. |
| F5 | Belirsizlik altında simülasyon yöntemsel olarak uygun; arıza ve işlem süresi dağılımı için actuals yok. Keyfi dağılımı tesis dayanıklılığı gibi sunmayacağız. |
| F6 | Olay dizisi üzerinde politika kıyası uygun sonraki deneydir; gerçek olay sıklığı ve planlamacı maliyetleri yok. G7 üç sentetik vakayı genel güvenilirlik olarak büyütmeyiz. |
| F8 | Alternatif makine/endüstriyel beceri yeteneği değerli ama makine uygunluğu, işlem süresi ve kaynak kuralları sahada doğrulanmalıdır. Düz JSP sonucunu FJSP'ye genellemeyiz. |
| F9 | Zaman dilimli tarife için doğrulanmış tesis sözleşmesi ve zaman etiketli enerji verisi gerek. Genel bir Türkiye tarifesini müşteriye atamayız. |
| F10 | Telemetri olmadan arıza olasılığı veya RUL modeli eğitilmez; sırf özellik listesi için boş risk tablosu eklenmez. |
| F11 | Karar defteri ve mevcut ACTIVE akışı gerçektir; ayrı insan onayı yoktur. Onay rolü ve yayımlama semantiği G9/G10'da işletme sahibiyle tanımlanmalıdır. Bugünkü laboratuvar token'ı insan onayı sayılmaz. |
| F12 | KPI sözlüğü yararlı; ilk somut tanım bu turdaki `scheduled_completion_share` formülüdür: son operasyonu 7 günlük sınırda veya öncesinde biten planlı birim / hafta 1 planlı birim. OEE için fiili durum ve duruş verisi gerekir. |
| F13 | Tahminin karar değerini ölçmek geçerli bir araştırma sorusu. Ancak “mükemmel öngörü” yalnız geçmişe dönük oracle alt sınırıdır; operasyonel rakip olamaz. LP/MRP'de aynı bilgi kesimi, aynı fiziksel kısıt ve gerçekleşen talep maliyeti tanımlanmadan sayısal sonuç üretmeyiz. |
| F15 | Ağırlık taraması laboratuvar incelemesi olabilir; öncelikler ve plan değişim maliyeti planlamacı tarafından kabul edilmeden tek “en iyi” Pareto seçimi yapılamaz. |

Rapordaki “çoğu yayından/üründen daha titiz”, ayırt edicilik/benzersizlik ve bütün dünya ürünlerini kapsama iddiaları hedefli taramadan çıkmaz. Üretici sayfaları özellik beyanıdır; eş kısıtlı performans karşılaştırması değildir. `0/50` çökme de çökme olasılığının sıfır olduğunu göstermez (yaklaşık %95 üst sınır %6). Raporun önerdiği `≥20 origin`, `±0,05 kapsama` ve işçi ayarını yükseltme eşikleri proje için önceden doğrulanmış standartlar değil, deney taslaklarıdır.

## Ölçülen işçi deneyi ve karar

[Açık `ft10` ham matrisi](../artifacts/research/scientific-worker-ft10-2026-10-17.json) OR-Library kaynağını SHA-256 ile sabitler. Aynı 10 tohumda, 5 saniye ve 20 mantıksal CPU'lu Windows makinede sonuç:

| İşçi | Bağımsız fizik denetimi ve düz JSP karşılaştırılabilirliği | Ham karşılaştırılabilir makespan | Çökme |
|---:|---:|---|---:|
| 1 | 3/10 | 930, 949, 958 | 0 |
| 2 | 6/10 | 933, 943, 944, 945, 954, 959 | 0 |
| 4 | 10/10 | 930, 930, 930, 930, 930, 930, 930, 939, 943, 949 | 0 |

`exit_code=2` olan denemeler solver çökmesi değildir: aday fiziksel olarak geçerli `FEASIBLE` olsa da nötr ilk vardiyayı aştığı için düz JSP ile aynı problem koşulunda kıyaslanamaz. Tekrarlanabilir komut: `python -m scripts.scientific_solver_probe tmp/jobshop1.txt --sha256 7f36d103332f94cfdeb76358e40927a57cfa7a426ebeaabd4de666350c69f028 --instances ft10 --workers 1 2 4 --seeds 11 17 23 31 42 53 67 73 89 97 --time-limit 5 --output <yeni-dosya.json>`; kaynak [OR-Library](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/jobshop1.txt) adresinden alınır. Bu deney genel ölçek eğrisi veya saha servis süresi değildir.

[Sentetik FDI referans matrisi](../artifacts/research/scientific-reference-workers-2026-10-17.json) aynı mühürlü run ve `BALANCED` tam üretim modeliyle, kabul edilmiş adayın bileşik amaç değerini ve alt sınırı ayrı kaydeder. 10 saniyede işçi 1 için iki tohumun amaçları 1.327.445 ve 1.305.225; işçi 4 için ikisi 1.365.425'tir (**daha kötü aday**). 30 saniyede tek tohum 42 için işçi 1: 1.327.445 / alt sınır 907.450; işçi 4: 1.184.975 / alt sınır 1.077.400 (**daha iyi aday ve alt sınır**). Tüm bu çözümler `FEASIBLE`; optimumluk kanıtı yok. Dört işçili ayarı bu az örnekten genel varsayılan yapmak bilimsel olarak erken olur. Önceki “paralel portföy çöktü” yorumunun kök nedeni de bu denemelerde yeniden üretilmedi; bu nedenle yorum kanıtlanmış arıza açıklaması sayılmaz.

Referans tekrarı için `python -m src.scheduling.reference_load_probe --db artifacts/reference/factory.db --baseline-run-id RUN-20261006-00a0d3 --expected-sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --repeats 1 --time-limit 10 --num-workers 4 --random-seed 42 --output <yeni-dosya.json>` kullanılır. Bu tam üretim modelinde henüz bağımsız aday denetçisi çalıştırılmadı; test edilen açık JSP alt kümesinde çalıştırıldı. Varsayılan işçi sayısı ve ACTIVE yayın yolu aynıdır.

## Yöntem ve kalan kanıt

- [OR-Tools CP-SAT durumları](https://developers.google.com/optimization/cp/cp_solver) ve [parametre tanımı](https://github.com/google/or-tools/blob/stable/ortools/sat/sat_parameters.proto): `FEASIBLE` optimumluk kanıtı değildir; işçi sayısı problem ve ortam üzerinde ölçülür.
- [Hyndman ve Athanasopoulos, ileri zamanlı doğrulama](https://otexts.robjhyndman.com/fpp3/tscv.html) ve [tahmin aralıkları](https://otexts.robjhyndman.com/fpp2/prediction-intervals.html): ufka göre hata dağılımı gerekir; tek RMSE'nin tüm günlere uygulanması kalibrasyon sağlamaz.
- [Prak, Teunter ve Syntetos, tahminli talepte güvenlik stoğu](https://pure.rug.nl/ws/files/77757714/On_the_calculation_of_safety_stocks_when_demand_is_forecasted.pdf): tedarik süresi boyunca tahmin hataları ve bağımlılık stok hesabını etkiler. Günlük tahmin çarpanını doğrudan MRP'ye bağlamak yöntemsel düzeltme olmaz.
- [Elmachtoub ve Grigas, karar odaklı tahmin](https://pubsonline.informs.org/doi/pdf/10.1287/mnsc.2020.3922): tahmin hatası ile karar maliyeti ayrı ölçülür. Makaledeki sayısal kazanımlar FDI'ye taşınmaz.

Yeni koşumlar açık JSP veya sentetik referanstır. Müşteri verisi, ERP/MES kabulü, üretim actuals, hizmet düzeyi kalibrasyonu ve finansal getiri kanıtı yoktur. Mühürlü eski artefaktlar değiştirilmedi; yeni kodun yayımlanabilir sürüm sayılması için kendi CI ve temiz kurulum kanıtı gerekir.
