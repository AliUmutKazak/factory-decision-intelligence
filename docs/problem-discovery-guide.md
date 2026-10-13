# FDI problem keşfi: görüşme rehberi ve kayıt şablonu

**Durum:** Görüşme hazırlığı; henüz pilot fabrika, müşteri verisi veya görüşme bulgusu yok. Bu rehber [strateji kararının](validated-strategy-2026-10-14.md) ikinci adımını somutlaştırır. G1 pilot kabulü ancak [pilot sözleşmesindeki](pilot-charter.md) yetkili kişilerle yapılır. Bugünkü çalışma herhangi bir kişiye ulaşmayı veya veri istemeyi içermez.

## Her görüşmenin amacı

Bir **gerçek karar anını** tanımla: kim, ne zaman, hangi mevcut plan ve verilerle, hangi fiziksel sınırlar altında, hangi alternatifi seçiyor? Çözüm veya tasarruf anlatmadan önce mevcut iş akışını ve başarısızlık maliyetini öğren. Aynı cevap farklı rollerden geldiğinde uyuşmazlığı saklama.

| Rol | Sorulacak somut sorular | Kaydedilecek kanıt |
|---|---|---|
| Planlamacı | Son plan değişikliği hangi olayla başladı? Karar anında hangi plan ve veri sürümü vardı? Excel/APS üzerinde hangi kısıtları elle düzelttiniz? Freeze, setup, alternatif makine, WIP ve yeniden işleme nasıl yönetiliyor? | Örnek karar sırası, kullanılan veri alanları, bilinmeyen kurallar, mevcut planın sahibi |
| Üretim/proses sorumlusu | Plan uygulanınca hangi işler başladı, durdu veya kısmen tamamlandı? Hangi makine, işçilik, kalıp, bakım ve malzeme sınırı asla ihlal edilemez? Hangi öneriyi fiziksel olarak reddedersiniz? | Fizik kuralı, olay/actuals tanımı, ret gerekçesi, güvenli geri dönüş |
| IT/MES/veri sahibi | Sipariş, routing, vardiya, stok, mevcut plan ve actuals hangi sistemde ve hangi zaman damgasıyla bulunur? İzinli dosya örneği, kimlik eşlemesi, birim/saat dilimi, veri gecikmesi, saklama ve silme sınırı nedir? | Kaynak/sahip matrisi, veri izni durumu, güvenlik ve vendor bağımlılıkları |
| Pilot sahibi/finans | Hangi karar daha iyi sayılır? KPI'nın payı, paydası, birimi, dönemi ve maliyet kaynağı nedir? Mevcut planı ve uygulanan sonucu kim onaylar? Kabul/ret eşiğini kim belirler? | Karar sahibi, olası ölçüm planı ve maliyet varsayımları; onay henüz yok |

## Tek görüşme kayıt formu

Gerçek kişi veya müşteri adı ve ham dosya bu depoya yazılmaz. İzinli notlar yetkili yerde tutulur; burada yalnız anonim, paylaşım izni verilmiş özet bulunabilir.

| Alan | Doldurulacak içerik |
|---|---|
| Görüşme kimliği / tarih / rol | Takma kimlik; kurum ve kişi bilgisi ayrı, yetkili kayıtta |
| İzin ve paylaşım sınırı | Görüşme, not, örnek dosya ve alıntı için ayrı izin durumu |
| Karar tetikleyicisi ve sıklığı | Son somut örnek; sayı bilinmiyorsa `bilinmiyor` |
| Mevcut akış ve araç | Karar anındaki snapshot, mevcut plan ve onay yolu |
| Sert ve yumuşak kısıtlar | Her kuralın sahibi; belirsiz veya çelişen cevaplar |
| Kullanılabilir veri | Kaynak, birim, zaman dilimi, gecikme, izin ve saklama |
| Başarı ölçüsü | Formül, pay/payda, dönem, baseline, actuals ve kabul sahibi |
| Model uyumu | `uyumlu`, `eşleme gerekir`, `kapsam dışı` veya `bilinmiyor`; gerekçe |
| Açık hipotez / karşı kanıt | Duyulan ihtiyaç ile gözlenen davranışı ayır; olumsuz örneği koru |
| Sonraki karar | Yeni görüşme, yalnız veri profili, dar dosya denemesi veya durdurma |

## Dar kullanım senaryosu seçme kuralı

Bir senaryo ancak karar sahibi belli, mevcut plan yeniden üretilebilir, girdilerin sahibi ve izin yolu belirli, en az bir fiziksel ret kuralı açıklanabilir ve aynı bilgi anında karşılaştırma mümkün görünüyorsa **pilot adayı** olur. Mevcut sabit makine/tam sipariş/tek ortak vardiya profiline uymuyorsa önce [ön kontrol ve ret raporu](../examples/pilot-package/README.md) yapılır; desteklenmeyen kural sessizce solver'a taşınmaz. Ticari büyüklük veya ROI tahmini seçim için kanıt yerine kullanılmaz. Bilinmeyenler G1'de açık kalır.

Görüşme sayısı veya puan eşiği şimdiden uydurulmaz. Bulgular birbirinden bağımsız roller ve gerçek karar örnekleriyle tutarlı hale gelmeden “pazar doğrulandı” denmez. Fabrika arayışı, kullanıcı tercihine göre laboratuvar paketi tamamlandıktan sonraki ayrı aşamadır.
