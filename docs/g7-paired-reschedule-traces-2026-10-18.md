# G7: eşlenik ardışık kesinti dizileri

**18 Ekim 2026.** Bu deney, [tek izlik provayı](g7-two-event-freeze-rehearsal-2026-10-18.md) üç sentetik iki olay dizisine genişletir. Amaç, aynı dondurma ve çizelge doğrulama yolunda iki sevk kuralının davranışını ve başarısızlıkları kaydetmektir. Gerçek fabrika olayı, gerçekleşen üretim veya hizmet düzeyi ölçümü değildir.

## Protokol

- Her yöntem, SHA-256 özeti `8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf` olan aynı mühürlü sentetik referans veritabanının ayrı geçici kopyasından başlar; baz koşum `RUN-20261006-00a0d3` olur. Kaynak değişmez.
- [İlk](../examples/g7-reschedule-event-trace.json), [orta](../examples/g7-reschedule-moderate-event-trace.json) ve [geç](../examples/g7-reschedule-late-event-trace.json) dizilerin her birinde iki zaman sıralı makine kesintisi vardır. İkinci olay, ilk olayın yeni `ACTIVE` sürümü doğrulanıp yayımlandıktan sonra yönteme ulaşır. İlk olay başarısızsa ikinci olay denenmez ve paydada işaretlenir.
- `FULL` serbest sıralama, `EDD` ise teslim tarihi sırasını sabitleyen **aynı sabit rotalı CP-SAT fizik modelidir**. İki yöntem de yerel onarımı kapatır; 30 saniye çözücü bütçesi, tek worker ve seed 42 kullanır. Yöntem sırası izler arasında döndürülür. Adaylar aynı bağımsız yeniden çizelgeleme denetiminden ve kalıcı yayın yolundan geçer.
- İlk olaydan sonraki `ACTIVE` sürümleri yöntemlere göre ayrışabilir. Dolayısıyla ikinci olayın giriş çizelgeleri aynı değildir; ikinci satır koşullu **politika yörüngelerini** karşılaştırır. Eşit kaynak ve ayarlar, yöntem üstünlüğü veya nedensel saha etkisi kanıtlamaz.

```powershell
python -m scripts.compare_reschedule_event_traces --db artifacts/reference/factory.db --sha256 8ae3219733c07e7bc10d01f82d9524c0d6c328b78205dc57c4a8774272af0caf --baseline-run-id RUN-20261006-00a0d3 --traces examples/g7-reschedule-event-trace.json examples/g7-reschedule-moderate-event-trace.json examples/g7-reschedule-late-event-trace.json --methods FULL EDD --output artifacts/research/g7-paired-reschedule-traces-2026-10-18.json
```

## Gözlem ve sınır

| Sentetik dizi | İki yöntemin de kabul edildiği olay çifti | İkinci olaydan sonra FULL / EDD makespan | İkinci olayda FULL / EDD yeri değişen görev |
|---|---:|---:|---:|
| İlk | 2/2 | 12.709 / 14.144 dk | 28 / 0 |
| Orta | 2/2 | 12.709 / 14.144 dk | 22 / 0 |
| Geç | 0/2 | Yok | Yok |

Toplam **4/6 planlanan olay çiftinde** iki yöntem de kabul edildi. Geç dizide iki yöntem de ilk olayda modelin `INFEASIBLE` durumuyla reddedildi; ikinci olay her iki yöntem için `NOT_ATTEMPTED_AFTER_PRIOR_FAILURE` olarak saklandı. FULL'ün ilk iki izde daha düşük son makespan üretmesi, EDD'nin ikinci olayda hiç görev oynatmamasının kararlılık açısından farklı bir sonuç vermesi ve geç izdeki ortak başarısızlık birlikte değerlendirilmelidir. Bu üç seçilmiş dizi genel yöntem üstünlüğü göstermez.

Ham [eşlenik kayıt](../artifacts/research/g7-paired-reschedule-traces-2026-10-18.json) her giriş izinin ve kodun özetini, yöntem sırasını, her denemenin çözüm ve kararlılık ölçülerini, başarısızlık nedenini ve denenmeyen olayları taşır. Başarı hesabı yalnız iki yöntemin de kabul edildiği olay çiftine uygulanır; başarısız olaylar kayıttan çıkarılmaz. Geç dizide ilk olayın model durumu `INFEASIBLE` ise bu, verili sentetik model ve dondurma kısıtları içindir; gerçek bir fabrikanın fiziksel olarak üretim yapamayacağı anlamına gelmez.

İzlerin sayısı ve çeşitliliği genel yöntem sıralaması, timeout sıklığı, p95 gecikme veya saha SLO'su çıkarmaya yetmez. Özellikle EDD'nin sabit sırası farklı bir arama uzayını çözer; bu alt uzaydaki `OPTIMAL`, `FULL` modelin optimumu değildir. Başlamış işlerin gerçek miktarı, WIP, operatör ve malzeme durumu ile fabrika olay sıklığı hâlâ saha verisi ve kabulü gerektirir.
