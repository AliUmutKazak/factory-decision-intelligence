# G7-T: acil sipariş adayının bağımsız denetimi

**Tarih:** 8 Ekim 2026. Bu laboratuvar adımı, [mevcut planla acil sipariş oynatmasının](g7-active-baseline-replay.md) ürettiği hızlı adayları çözücünün `OPTIMAL`/`FEASIBLE` etiketi dışında kontrol eder. [OR-Tools job-shop tanımı](https://developers.google.com/optimization/scheduling/job_shop) işlem öncüllüğü ve makine çakışmamasını temel uygunluk kuralları olarak açıklar. [Kovács ve diğerlerinin CP 2021 endüstriyel çalışması](https://doi.org/10.4230/LIPIcs.CP.2021.36) hızlı sıralama/başlangıç çözümünü optimizasyonla birlikte değerlendirir. FDI'nin denetimi kendi veri sözleşmesine göre ayrı kodda yazılmıştır; bu kaynakların sonuçları FDI performansı olarak aktarılmaz.

## Ne denetlendi?

`src/scheduling/hot_order_schedule_audit.py` üretim çözücüsünü veya onun kısıt kurucularını çağırmaz. Mühürlü referans veritabanını salt okunur açar ve aday çizelgenin şu özelliklerini kaynak plan, rota, setup matrisi ve makine başlangıç durumuyla karşılaştırır:

- Ürün bazında planlanan ve çizelgelenen birim sayısı; acil siparişin parti boyuna yuvarlanan ek miktarı.
- Her lotta rota operasyonlarının tamlığı, doğru makine, parti/süre hesabı ve işlem sırası.
- Benzersiz görev kimliği; işlem ve setup zaman aralıklarının tutarlılığı, makine çakışmaması.
- Acil siparişin ürün, teslim zamanı ve öncelik kimliği.

Önceki solver içi plan–çizelge görüntüsü aynı ürüne eklenen acil sipariş satırını ürün toplamına çevirmediği için yanlış miktar alarmı veriyordu. Toplam ürün bazında alınacak şekilde düzeltildi. Bağımsız denetim ayrıca yanlış miktar, yanlış makine, eksik operasyon, yanlış setup ve makine çakışması eklenmiş kopyaları reddeden testlerden geçti.

## Tekrarlanabilir sonuç

[Ham JSON](../artifacts/research/g7-hot-order-independent-audit-edd-2s.json) kaynak DB SHA-256, kod/commit hash'leri, beş ayrı geçici kopya ve her denemenin denetim sonucunu içerir. `P01` için 51 adetlik sentetik acil sipariş, kabul edilmiş `ACTIVE` baz ve `EDD` sabit sıra ile 2 saniye solver sınırında **5/5 aday** üretti. Her adayın 34 görevi bağımsız denetimde **0 ihlalle kabul edildi**; replay p50/p95 **0,2338 / 0,2726 saniye** ölçüldü. Kaynak dosya ve geçici `ACTIVE` sürüm değişmedi.

Bu denetimin kapsamı **miktar, rota, işlem aralığı, setup, öncüllük ve makine işgali** ile sınırlıdır. Takvim vardiyası, MRP malzeme zamanı, hafta bazlı fazla mesai bütçesi, ekonomik hedef ve gerçek ERP/MES karşılaştırması bağımsız olarak burada doğrulanmadı. `EDD` sonucu `OPTIMAL` olsa bile bu yalnız sabit sıra alt problemindedir. Beş sentetik tekrar saha güvenilirliği veya hizmet süresi hedefi değildir. Bu adaylar API'nin varsayılan yayınına alınmadı.

## Sonraki kapı

G7 için takvim/MRP/OT bağımsız uygunluk kapsamı, farklı sipariş/arıza olayları, çözüm kalitesi kabul eşiği, eşzamanlı API yükü, `ACTIVE` yaşı ve operatöre görünür timeout/fallback davranışı açık. Gerçek tesis kuralları ve müşteri SLO'su daha sonraki saha aşamalarında belirlenecek.
