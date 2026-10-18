# G7: çakışan kapalı aralıkların düzeltilmesi

**18 Ekim 2026.** [Önceki üç izlik ölçümde](g7-paired-reschedule-traces-2026-10-18.md) geç M02 kesintisi iki yöntem için de `INFEASIBLE` görünüyordu. Kaynak sentetik çizelgede bu kesinti, dondurulmuş M02 işinin bitiminden sonra 5.716–5.806. dakikalara yerleştiriliyordu; gece kapanışı 5.760. dakikada başlıyordu. Eski model, bakım/kesinti ve takvim kapanışlarını aynı `NoOverlap` listesinde topladığı için **kapalı aralıkların birbirine çakışmasını** da yasaklıyordu. Bu, iş planından bağımsız sahte bir çözümsüzlük yarattı.

## Düzeltme ve kontrol

İşlem ve hazırlık aralıkları takvim kapanışlarıyla birlikte çakışmama kısıtında kalır. Her bakım/kesinti aralığına karşı iş ve hazırlık aralıkları ayrıca korunur. Böylece işler kapanışlarda çalışamaz; iki kapanışın aynı zamana denk gelmesi mümkündür. Sabit ve koşullu gece kapanışı ile iki üst üste bakım aralığı için küçük CP-SAT regresyon testleri bu davranışı doğrular.

Aynı mühürlü sentetik referansın geç olayı, kesinti süresi sıfırken ve 1 dakikayken çözülüyordu; 90 dakikada eski modelin reddi ortaya çıkıyordu. Düzeltilmiş model 90 dakikalık olayı üretim yeniden çizelgeleme yolunda kabul etti ve 31 görevi doğruladı. Bu, olayın bir fabrikada fiilen uygulanabilir olduğunu kanıtlamaz; yalnız yanlış model çelişkisinin giderildiğini gösterir.

Üretim yolunu kullanan [regresyon testi](../tests/test_reschedule_calendar_overlap.py), mühürlü sentetik referansın ayrı kopyasında aynı 90 dakikalık olayı, yeni tek `ACTIVE` sürümü ve kesinti boyunca iş/hazırlık çakışmamasıyla denetler. [Küçük model testleri](../tests/test_schedule_availability_overlap.py) sabit veya koşullu takvim kapanışı ile üst üste bakım aralıklarını kapsar. Eski ham JSON tarihsel hata gözlemi olarak korunur; yöntem başarısızlığı veya fiziki üretim imkânsızlığı kanıtı sayılmaz.

Üç izlik eşlenik deneyin düzeltilmiş modelle kontrollü kaynak yükünde yeniden çalıştırılması gerekir. Bu düzeltme, önceki 4/6 karşılaştırmasını güncel yöntem sonucu hâline getirmez.

## Açık sınır

Tek bir sentetik olayın düzeltilmesi genel yöntem sıralaması, gerçek hata sıklığı, p95 çözüm süresi veya fabrika SLO'su vermez. Gerçek vardiya, actuals, WIP, operatör ve malzeme kuralları ile saha kabulü ayrı kalır.
