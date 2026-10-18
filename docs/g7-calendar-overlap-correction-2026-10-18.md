# G7: çakışan kapalı aralıkların düzeltilmesi

**18 Ekim 2026.** [Önceki üç izlik ölçümde](g7-paired-reschedule-traces-2026-10-18.md) geç M02 kesintisi iki yöntem için de `INFEASIBLE` görünüyordu. Kaynak sentetik çizelgede bu kesinti, dondurulmuş M02 işinin bitiminden sonra 5.716–5.806. dakikalara yerleştiriliyordu; gece kapanışı 5.760. dakikada başlıyordu. Eski model, bakım/kesinti ve takvim kapanışlarını aynı `NoOverlap` listesinde topladığı için **kapalı aralıkların birbirine çakışmasını** da yasaklıyordu. Bu, iş planından bağımsız sahte bir çözümsüzlük yarattı.

## Düzeltme ve kontrol

İşlem ve hazırlık aralıkları takvim kapanışlarıyla birlikte çakışmama kısıtında kalır. Her bakım/kesinti aralığına karşı iş ve hazırlık aralıkları ayrıca korunur. Böylece işler kapanışlarda çalışamaz; iki kapanışın aynı zamana denk gelmesi mümkündür. Sabit ve koşullu gece kapanışı ile iki üst üste bakım aralığı için küçük CP-SAT regresyon testleri bu davranışı doğrular.

Aynı mühürlü sentetik referansın geç olayı, kesinti süresi sıfırken ve 1 dakikayken çözülüyordu; 90 dakikada eski modelin reddi ortaya çıkıyordu. Düzeltilmiş model 90 dakikalık olayı üretim yeniden çizelgeleme yolunda kabul etti ve 31 görevi doğruladı. Bu, olayın bir fabrikada fiilen uygulanabilir olduğunu kanıtlamaz; yalnız yanlış model çelişkisinin giderildiğini gösterir.

Üretim yolunu kullanan [regresyon testi](../tests/test_reschedule_calendar_overlap.py), mühürlü sentetik referansın ayrı kopyasında aynı 90 dakikalık olayı, yeni tek `ACTIVE` sürümü ve kesinti boyunca iş/hazırlık çakışmamasıyla denetler. [Küçük model testleri](../tests/test_schedule_availability_overlap.py) sabit veya koşullu takvim kapanışı ile üst üste bakım aralıklarını kapsar. Eski ham JSON tarihsel hata gözlemi olarak korunur; yöntem başarısızlığı veya fiziki üretim imkânsızlığı kanıtı sayılmaz.

## Düzeltilmiş modelle bağımsız tekrar

[Üç dizinin ham eşlenik kaydı](../artifacts/research/g7-paired-reschedule-traces-corrected-2026-10-18.json), yoğun başka bir yerel hesaplamanın çözüm sürelerini bozma riskinden dolayı ayrı bir Ubuntu 24.04 GitHub Actions koşucusunda üretildi ([koşum 39126807050](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/39126807050), koşum commit'i `0e2b2734ef45cc20173b9021e8cd5e475f480c5f`; doğrulanan kaynak kod commit'i `8a27462d9960be1cc0499a89fe96b899f3d9fb89`). [Tekrarlanabilir iş akışı](../.github/workflows/g7-paired-reschedule-replay.yml) mühürlü sentetik veritabanını ve kilitli Linux bağımlılıklarını, aralarında OR-Tools 9.15.6755'i, kullanır. İki yönteme de her olayda 30 saniye, tek worker ve seed 42 verilir. Veritabanı özeti `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf` olarak doğrulandı; koşum sonucu ve mevcut kaynak dosyalarının normalleştirilmiş özetleri eşleşti. GitHub kaynak izleri LF satır sonuyla sakladığı için ham olay dosyası özetleri Git blob'larıyla karşılaştırıldı. Ham JSON'un SHA-256 özeti kanıt kaydındadır.

| Sentetik iki olay dizisi | İki yöntemce kabul edilen olay çifti | Son FULL / EDD makespan (dk) | İkinci olayda FULL / EDD yeri değişen görev |
|---|---:|---:|---:|
| İlk | 2/2 | 12.230 / 14.144 | 26 / 0 |
| Orta | 2/2 | 12.625 / 14.144 | 25 / 0 |
| Geç | 2/2 | 12.709 / 12.704 | 0 / 0 |

Toplam **6/6 planlanan olay çiftinde** iki yöntem de bağımsız aday denetiminden geçip her yöntemin kendi tek `ACTIVE` sürümünü yayımladı. FULL ilk ve orta dizilerde daha kısa son makespan üretti; geç dizide EDD beş dakika daha kısaydı. İlk ve orta dizilerde FULL'ün ikinci olayda daha fazla görevi oynatması, kararlılık ile makespan arasında karar verilmesi gerektiğini gösterir; seçim eşiği önceden saha sahibiyle belirlenmelidir. FULL'ün ilk/orta olaylarının üçü yalnız `FEASIBLE`, EDD'nin altısı sabit sıra alt probleminde `OPTIMAL` durumundadır. Bu durumlar genel modelde yöntem üstünlüğü veya küresel optimum anlamına gelmez.

Eski 4/6 sonucu geçersiz tarihsel kayıttır. Yeni 6/6 yalnız **üç seçilmiş sentetik dizi, bir tohum ve tek koşum** içindir. İkinci olay her yöntemin kendi ilk olay sonucundan başladığı için eşlenik satırlar ortak ikinci baz planı paylaşmaz. Ayrı koşucu yerel yük çakışmasını giderse de çözüm süresi dağılımı, hata olasılığı, p95, müşteri yükü veya fabrika SLO'su çıkarılamaz.

## Açık sınır

Tek bir sentetik olayın düzeltilmesi genel yöntem sıralaması, gerçek hata sıklığı, p95 çözüm süresi veya fabrika SLO'su vermez. Gerçek vardiya, actuals, WIP, operatör ve malzeme kuralları ile saha kabulü ayrı kalır.
