# G7-T: acil sipariş adayının bağımsız denetimi

**Tarih:** 8 Ekim 2026. Bu laboratuvar adımı, [mevcut planla acil sipariş oynatmasının](g7-active-baseline-replay.md) ürettiği hızlı adayları çözücünün `OPTIMAL`/`FEASIBLE` etiketi dışında kontrol eder. [OR-Tools job-shop tanımı](https://developers.google.com/optimization/scheduling/job_shop) işlem öncüllüğü ve makine çakışmamasını temel uygunluk kuralları olarak açıklar. [Kovács ve diğerlerinin CP 2021 endüstriyel çalışması](https://doi.org/10.4230/LIPIcs.CP.2021.36) hızlı sıralama/başlangıç çözümünü optimizasyonla birlikte değerlendirir. FDI'nin denetimi kendi veri sözleşmesine göre ayrı kodda yazılmıştır; bu kaynakların sonuçları FDI performansı olarak aktarılmaz.

## Ne denetlendi?

`src/scheduling/hot_order_schedule_audit.py` üretim çözücüsünü veya onun kısıt kurucularını çağırmaz. Mühürlü referans veritabanını salt okunur açar ve aday çizelgenin şu özelliklerini kaynak plan, rota, setup matrisi ve makine başlangıç durumuyla karşılaştırır:

- Ürün bazında planlanan ve çizelgelenen birim sayısı; acil siparişe ayrılan lotların parti boyuna yuvarlanan ek miktarı.
- Her lotta rota operasyonlarının tamlığı, doğru makine, parti/süre hesabı ve işlem sırası.
- Benzersiz görev kimliği; işlem ve setup zaman aralıklarının tutarlılığı, makine çakışmaması.
- Acil siparişin ürün, teslim zamanı, öncelik ve kendisine ayrılan miktar kimliği.

Önceki solver içi plan–çizelge görüntüsü aynı ürüne eklenen acil sipariş satırını ürün toplamına çevirmediği için yanlış miktar alarmı veriyordu. Toplam ürün bazında alınacak şekilde düzeltildi. Bağımsız denetim ayrıca yanlış miktar, acil siparişe fazla lot atama, yanlış makine, eksik operasyon, yanlış setup ve makine çakışması eklenmiş kopyaları reddeden testlerden geçti.

## Tekrarlanabilir sonuç

[Ham JSON](../artifacts/research/g7-hot-order-independent-audit-edd-2s.json) kaynak DB SHA-256, kod/commit hash'leri, beş ayrı geçici kopya ve her denemenin denetim sonucunu içerir. `P01` için 51 adetlik sentetik acil sipariş, kabul edilmiş `ACTIVE` baz ve `EDD` sabit sıra ile 2 saniye solver sınırında **5/5 aday** üretti. Her adayın 34 görevi bağımsız denetimde **0 ihlalle kabul edildi**; replay p50/p95 **0,2166 / 0,2263 saniye** ölçüldü. Kaynak dosya ve geçici `ACTIVE` sürüm değişmedi.

Bu denetim üretim çözücüsünden ayrı kodla **miktar, rota, işlem aralığı, setup, öncüllük, makine çakışması, bakım çakışması, kapanış günü, tanımlı laboratuvar takvimi, W1 fazla mesai bütçesi ve sentetik MRP malzeme serbest bırakmasını** kontrol eder. Kapsamı hâlâ sınırlıdır: haftalık sentetik takvim politikasını kullanır; vardiya/gün istisnalarını ve her makine takviminin tam tarihsel kuralını kapsamaz. Reschedule freeze/FLEXIBLE bağlamı, gerçek ERP/MES actuals ve ekonomik hedef bu G7 hot-order denetiminde bağımsız doğrulanmaz. `EDD` sonucu `OPTIMAL` olsa bile bu yalnız sabit sıra alt problemindedir. Beş sentetik tekrar saha güvenilirliği veya hizmet süresi hedefi değildir. Bu adaylar API'nin varsayılan yayınına alınmadı.

**18 Ekim makine kapsamı düzeltmesi:** Hazırlık matrisinde yalnız `ALL` genel kuraldır. Başka bir makine adına kayıtlı satır, adayda o makine kullanılmıyorsa diğer makinelere yayılmaz. Denetçi bu ayrımı çözücüden bağımsız olarak uygular. Yukarıdaki beş tekrar daha eski kaynak sürümünün tarihsel kanıtıdır; yeni makine kapsamı regresyonu ayrı test ve CI ile doğrulanır.

## Sonraki kapı

G7 hot-order adayında temel takvim, bakım, W1 OT ve sentetik MRP serbest bırakma denetimi mevcut. Kalan laboratuvar işi farklı olayların daha geniş benchmark'ı, değişken günlük takvim ve freeze/FLEXIBLE koşullarının bağımsız yeniden kurulması, önceden seçilmiş çözüm kalitesi ölçütleri, eşzamanlı API yükü, `ACTIVE` yaşı ve operatöre görünen timeout/fallback davranışıdır. Gerçek tesis kuralları ve müşteri SLO'su daha sonraki saha aşamalarında belirlenecek.
