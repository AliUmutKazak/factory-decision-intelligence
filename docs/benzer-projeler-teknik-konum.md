# FDI'nin benzer teknik çalışmalara göre konumu

**Tarih:** 8 Ekim 2026. Bu inceleme [birleşik yol haritasının](fdi-roadmap-execution.md) fabrika bağımsız hazırlığını önceliklendirmek içindir. Farklı problem ve veri kullanan araçlar arasında çözüm kalitesi, hız, satış veya saha başarısı sıralaması yapılmaz.

## İncelenen açık ve resmî örnekler

| Örnek | Belgelenmiş kapsam | FDI ile adil çıkarım |
|---|---|---|
| [Google OR-Tools Job Shop örneği](https://developers.google.com/optimization/scheduling/job_shop) | Sabit makineye atanmış görevler, öncüllük, makine çakışmaması ve makespan hedefini gösterir. | FDI aynı CP-SAT ailesini kullanıp taktik plan, MRP, takvim/setup, yeniden çizelgeleme, maliyet ve izlenebilirlik katmanları ekler. Bu, OR-Tools çözücüsünden daha iyi olduğu iddiası değildir. |
| [PyJobShop](https://pyjobshop.org/latest/) ve [esnek job shop örneği](https://pyjobshop.org/latest/examples/flexible_job_shop.html) | Birden çok çizelgeleme ortamı; alternatif makine/işlem modu, setup, mola ve farklı hedefler. Kendi [tanımına](https://pyjobshop.org/stable/setup/intro_to_scheduling.html) göre odağı çizelgelemedir. | FDI'nin bütünleşik karar zinciri ve mühürlü run/audit akışı portföy açısından güçlüdür. Ancak mevcut üretim rotası operasyon başına tek makine seçer; genel FJSP kabiliyeti ve optimumuyla doğrudan kıyas iddia edilemez. |
| [Timefold Task Scheduling](https://docs.timefold.ai/job-scheduling/latest/user-guide/use-cases) ve [solver metrikleri](https://docs.timefold.ai/timefold-solver/latest/running-timefold-solver/service/exposing-metrics) | Ayrık imalatta makine/operatör, changeover, ortak takım ve arıza/acil iş sonrası yeniden planlama örnekleri; servis çıktısında metrikler. | FDI'nin makine, arıza/acil iş ve karar kaydı çekirdeği var. Operatör/kalıp/aparat kısıtları, kabul edilmiş saha kuralları ve ölçülmüş servis davranışı henüz yok. Timefold bir ürün/altyapı olduğundan hız veya kapsam üstünlüğü sonucu çıkarılmaz. |

## Bugünkü dürüst değerlendirme

- **Güçlü taraf:** LP kapasite planı, MRP, CP-SAT çizelge, olay tabanlı yeniden çizelgeleme, enerji/karbon analitiği, API/dashboard ve mühürlü run kanıtı aynı karar akışında. Temiz kurulum ve Docker CI ile [dört OR-Library sabit JSP örneğinde](external-jsp-benchmark.md) bağımsız çizelge denetimi var: üçü `OPTIMAL`, daha büyük `ft10` 30 saniyede `FEASIBLE`. Bu sonuçların kapsamı etiketli sentetik/statik örneklerdir.
- **En belirgin teknik açık:** Alternatif makine seçimi yok. Açık ambalaj verisinin proses-makine, hız/süre, setup ve zaman ekseni kuralları belirsizken bu alanları tahmin ederek genel FJSP sonucu sunmak yanlış olur. [Kaynak profili](open-packaging-data-profile.md) bu sınırı belgeler.
- **İşletim açığı:** G7'de referans yük için p50/p95, timeout ve fallback oranları ile runbook eksik. Yerelde 30 saniyelik bir hot-order senaryosu `UNKNOWN` vermiştir; geçerli önceki ACTIVE korunması önemlidir, fakat kabul edilmiş servis hedefi değildir.
- **Saha açığı:** Gerçek plan/actuals, vendor round-trip, proses uzmanı kabulü ve finans uzlaştırması bulunmadığı için müşteri performansı veya ROI sıralaması yapılamaz.

## Fabrika arayışından önceki iş sırası

1. **G0 ve vitrin:** PR'ların `main` üzerinde kalite/Docker kanıtını sabitle; sürüm etiketi/artifact kararını ver; README, güncel ekran görüntüleri ve kısa demo için aynı commit'i kullan. API yalnız yerel/denetimli ortamda gösterilsin.
2. **G8-T karşılaştırma:** `ft06`, `la01`, `la02` ve `ft10` için aynı problem/kısıt, açık veri kökeni, bağımsız uygunluk denetimi ve optimum/FEASIBLE/bound ayrımı kaydedildi. Daha geniş yük, tekrarlı çalışma, farklı tohum/süre sınırı ve olay replay'iyle dayanıklılığı ölç; FJSP ayrı problem olarak kalsın.
3. **G7 işletim:** Referans yük ve olay replay'inde solve süresi dağılımı, timeout/infeasible, ACTIVE yaşı ve başarısız çözümden geri dönüşü ölç; önceden tanımlı yükte tekrar et. Kısa süreli solver sonucunu optimum diye sunma.
4. **G4-T/G5-T/G6-T veri ve olay:** Kanonik CSV ön kontrolünden açık ret/eşleme raporuna ilerle; kaynak/hesaplanan/varsayım alanlarını ayır. Yerel tekrarlı/geç mesaj ve küçük kesinti/kısmi üretim örneklerini sınayarak veri kaybı veya iki kez sayım riskini araştır.
5. **G2/G3 sınırı:** Yerel demo erişimi ve secret sınırını koru; geri yükleme/run izolasyonu ile eşzamanlı yayın tasarımını güçlendir. Kimlik sağlayıcısı, vendor taşıması ve canlı RTO/RPO sahaya göre belirlenecek; bunları varsayımla kabul etme.

Bu sıra, [paylaşım hazırlık kartındaki](paylasim-hazirlik-karti.md) teknik POC hedefini ve PDF'nin G0-G13 kabul kapılarını korur. **Fabrika bulma/arama işi bu fabrika bağımsız teknik hazırlıkların sonrasındadır.** Erken gelen ilgi kaydedilebilir; gerçek pilot kapsamı, veri izni ve kabulü ancak ilgili tesisle G1'de kararlaştırılır. Bu yaklaşım G9-G12 saha aşamalarını ortadan kaldırmaz.
