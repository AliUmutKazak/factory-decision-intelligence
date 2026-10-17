# TU/e dinamik çizelgeleme benchmark'ı: FDI uyumluluk denetimi

**Denetim tarihi:** 17 Ekim 2026
**Amaç:** TU/e'nin yeni yayımlanan benchmark'ının FDI'nin mevcut üretim çekirdeğiyle karşılaştırılabilir olup olmadığını belirlemek ve yanlış kıyas iddiasını önlemek.

## Karar

Benchmark araştırma ve yöntem referansı olarak değerlidir; mevcut FDI çizelgeleyicisiyle çevrimiçi sonuçları doğrudan karşılaştırmak için uygun değildir. Lisans engeli yoktur: [benchmark deposu MIT lisanslıdır](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances/blob/main/LICENSE), makale [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) ile yayımlanmıştır. Buna rağmen lisans uyumu, aynı problem tanımına sahip olunduğu anlamına gelmez.

Makale JSP, FSP, FJSP, montaj çizelgeleme, sequence-dependent setup ve online iş gelişi çeşitlerini kapsayan açık platformu tanımlar. Depodaki `SimulationEnv.generate_online_job_arrivals` yeni işlerin gelişini üstel aralıkla üretir; her operasyon için her makineye ayrı rastgele süre atar. Bu, FDI'deki mevcut sabit operasyon-makine rotasından farklı olan çevrimiçi FJSP semantiğidir. Kaynak kod [SimulationEnv](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances/blob/main/scheduling_environment/simulationEnv.py) ve [FJSP-DRL ayarlarında](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances/blob/main/configs/FJSP_DRL.toml) görülebilir.

Depodaki statik, sabit makineli JSP örnekleri problem ailesi bakımından daha yakın olsa da FDI'nin OR-Library `ft06`, `la01`, `la02`, `ft10` kıyasıyla örtüşür. Bunları yeni dinamik kanıt gibi sunmak veya farklı ölçüm koşullarındaki sonuçları birleştirmek doğru olmaz. Çevrimiçi FJSP'yi FDI'ye zorla indirgemek de makine uygunluğu kısıtını değiştirip kaynak benchmark'ın anlamını bozar.

## FDI için doğru kullanım

TU/e çalışması benchmark tasarımı ve yöntem kapsamı için kaynak gösterilsin; makalenin ve kodun lisans notları yeniden dağıtımda korunsun. Şimdilik benchmark kodu, SimPy veya öğrenme kütüphaneleri FDI bağımlılıklarına eklenmesin. Bu, bakım yükünü ve semantik olarak yanıltıcı kıyas riskini önler.

FDI için yararlı sonraki deney, yayımlanmış online-FJSP örneğini “kopyalamak” yerine, FDI'nin sabit rotalı sözleşmesine göre **uyarlanmış sentetik olay benchmark'ı** tanımlamaktır:

1. Başlangıç planı, sipariş gelişleri, süreler, arıza/gecikme olayları ve tohumlar sürümlü JSON izlerinde sabitlenir. Her operasyonun tek makinesi ve işlem süresi açıkça verilir; aynı iz bütün yöntemlere uygulanır.
2. Başlangıç planı ve karar anındaki bilgi kesimi bütün yöntemlerde aynıdır. Olaydan sonra yalnız aynı zaman noktasında bilinen veriler kullanılmalı; gelecek olayları çözücüye sızdırılmamalıdır.
3. Baseline yöntemleri ve FDI aynı donanım, zaman bütçesi, başlangıç durumu ve dondurma ufkuyla çalıştırılır. FIFO/EDD/SPT ancak uygulanmış ve doğrulanmış olduklarında tabloya alınır. Sabit statik benchmark'lardaki optimum değerler dinamik yeniden çizelgeleme referansı gibi kullanılmaz.
4. Her koşumda bağımsız fizik/rota denetimi, çözücü durumu, duvar saati, tamamlanma/makespan ve gecikme; plan kararlılığı için değişen operasyon sayısı ve başlangıç saatlerindeki mutlak toplam kayma raporlanır. Geçersiz adayın performansı hesaplanmaz.
5. Önceden belirlenmiş çoklu tohum ve senaryoların tamamı yayımlanır; medyan ve çeyrekler arası aralık verilir. Senaryolar, model varsayımları, kod/veri hash'leri ve başarısız koşumlar kayda alınır.

Protokolün ilk, **tek olaylı** eşlenik yöntemi [sentetik G7 kıyasında](g7-paired-hot-order-methods-2026-10-17.md) uygulandı. Üç vaka × üç tohum × dört yöntem aynı mühürlü bazla ve eşit çözücü sınırıyla ölçüldü; uygunluk ve kararlılık raporlandı. Ardışık olaylar, zaman 0'dan sonraki bilgi kesimi, arıza ve freeze ufku içeren tam dinamik iz matrisi henüz uygulanmadı. Deney, FDI için gerçek fabrika faydası veya ürün üstünlüğü kanıtı değildir. Bu sınırlar ve karar, [17 Ekim küresel/Türkiye denetimine](global-turkey-product-science-audit-2026-10-17.md) işlendi.

**18 Ekim güncellemesi:** [Üç sentetik iki olay dizisinde FULL/EDD kıyası](g7-paired-reschedule-traces-2026-10-18.md) arıza, olay zamanı ve freeze ufkunu kısmen kapsar. Çoklu tohum, temsilî olay dağılımı, gerçek actuals ve TU/e ile aynı problem ailesinde kıyas hâlâ yoktur.

## Kaynaklar

- Reijnen, R. ve ark. (2026). “Job shop scheduling benchmark: environments and instances for learning and non-learning methods.” *Annals of Mathematics and Artificial Intelligence*. [DOI](https://doi.org/10.1007/s10472-026-10007-3), [yayınevi kaydı ve makale](https://link.springer.com/article/10.1007/s10472-026-10007-3).
- [Açık kaynak deposu](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances), [MIT lisansı](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances/blob/main/LICENSE), [dinamik ortam kodu](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances/blob/main/scheduling_environment/simulationEnv.py).
