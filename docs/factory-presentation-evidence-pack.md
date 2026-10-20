# FDI fabrika görüşmesi için kanıt ve anlatım paketi

**Sürüm bağlamı:** 21 Ekim 2026; son doğrulanmış sürüm `v0.1.9-lab`, commit `a18a2a5df7af4017467b9313a45fd78230aa3bf2`, [CI 39510744264](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/39510744264) ve [temiz Windows klonu](clean-demo-v019-2026-10-21.md). Yeni commit veya demo görseli kullanılırsa kanıtı yeniden eşleştir. Bilimsel ve pazar dayanağı: [güncel uluslararası denetim](global-evidence-audit-2026-10-15.md) ve [Türkiye/dünya kaynak denetimi](tr-global-science-market-audit-2026-10-11.md). Kapı durumu: [G0–G13 kayıtları](fdi-roadmap-execution.md). [Pillow danışma istisnası](dependency-security-2026-10-11.md) nedeniyle internete açık servis sunumu kapsam dışıdır.

**17 Ekim tarihsel plan denetimi:** `77a5f13809730513a81557183454b1a5afd7d757` için [CI başarılıdır](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/39037061869). [Mühürlü sentetik referansta](plan-schedule-gap-audit-2026-10-17.md) ilk hafta LP hedefi 8.400 adet, hafta bitiminde son operasyonu tamamlanan miktar 6.100 adettir; 2.300 adet sonraya sarkar. Sert ilk hafta bitiş koşulu aynı modelde `INFEASIBLE` çıktı. Bu bulguyu gizleme veya gerçekleşmiş fabrika performansı ya da güncel sürüm ölçümü gibi sunma.

Küresel/Türkiye APS ve bilimsel kaynak karşılaştırması için [17 Ekim ürün/bilim boşluk denetimine](global-turkey-product-science-audit-2026-10-17.md) bak. Bu taramadaki ticari ürün özellikleri üretici beyanıdır; eşit veri ve kısıtlarda bağımsız performans kıyası değildir.

## 30 saniyelik tanım

“FDI, üretim talebi, kapasite, malzeme ve sabit makineli operasyon sırasını tek bir izlenebilir karar akışında birleştiren laboratuvar karar destek prototipidir. Plan değiştiğinde öneriyi, mevcut plana etkisini ve model varsayımlarını gösterir. Şu ana kadarki sonuçlar sentetik/açık veridedir. İlk tesis incelemesi, canlı sisteme yazmadan, dar kapsamlı dosyalarla mevcut planla aynı koşulda karşılaştırma olarak tasarlanır.”

## Görüşmede gösterilecek akış

1. **Problem (1 dk):** Sipariş/termin, kapasite, malzeme ve makine takviminin birbirine bağlı olduğu tek bir karar anını tarif et; müşterinin gerçek kuralını bildiğimizi varsayma.
2. **Girdi ve sınır (1 dk):** Demo veri sınıfını “sentetik” veya “açık benchmark” diye göster. Sabit makine, tek ortak vardiya, tam sipariş ve boş WIP/actuals sınırını açıkça söyle.
3. **Karar (3 dk):** [Demo komutları](demo-and-customer-pilot.md) ile aynı snapshot için mevcut plan ve solver adayını; feasible/optimal durumunu, termin, takvim, setup, enerji ve plan kararlılığı raporlarını göster.
4. **İnsan kontrolü (1 dk):** Dosya pilotu öneri üretir ve üretim emri göndermez. Laboratuvar `reschedule` çağrısı ise başarılı adayı doğrudan ACTIVE yapar; ayrı planlamacı kabul/ret kapısı uygulanmamıştır. Sahada böyle bir kapı G9/G10 kapsamında tasarlanıp kabul edilmelidir.
5. **Kanıt (2 dk):** Güncel sürümün aynı commit'teki test/CI ve mühürlü run artifact'i, [temiz klon provası](clean-demo-v019-2026-10-21.md) ve [ayrı holdout'lu sentetik tahmin incelemesi](global-evidence-audit-2026-10-15.md) açılır. [Sabit makineli dış benchmark](external-jsp-benchmark.md#v012-lab-koduyla-12-ekim-yeniden-ölçüm) 12 Ekim kaynak sürümünün tarihsel deneyidir; güncel commit sonucu diye sunulmaz. [Dosya pilotu örneği](../examples/pilot-solve/README.md) ayrıca gösterilebilir. `FEASIBLE` ile `OPTIMAL` ayrılır.
6. **İlk pilot isteği (2 dk):** Tek hat/ürün ailesi, tek karar sahibi ve okuma amaçlı CSV/XLSX ile G1/G4–G8 kapsamı birlikte belirlenir. Gerçek veri izni gelmeden tasarruf/ROI sözü verilmez.

## İddia sicili

| Sunulabilir ifade | Gösterilecek kanıt | Söylenmeyecek sonuç |
|---|---|---|
| “Tek sunuculu, tekrar üretilebilir laboratuvar POC” | Release tag/commit + aynı commit CI kalite/Docker ve artifact digest; [sürüm kanıtı ve saha kabul sınırı](release-evidence-and-field-boundary.md) | Üretim servisi veya çok tesisli güvenilirlik kabulü |
| “Açık/sentetik örneklerde fiziksel çizelge denetimi var” | [OR-Library bağımsız audit](external-jsp-benchmark.md); solver statüsü ve zaman sınırı | Rakip APS'den hızlı/iyi veya genel FJSP ispatı |
| “Aynı model girdisinde plan politikaları karşılaştırılabilir” | [Business case demo](../artifacts/demo/business-case.md), aynı snapshot ve maliyet varsayımları | Müşteri tasarrufu, nakit fayda veya pozitif ROI |
| “LP miktar hedefi ile ilk hafta fiziksel bitiş ayrı ölçülür” | [17 Ekim referans denetimi](plan-schedule-gap-audit-2026-10-17.md): 8.400 hedef, 6.100 zamanında tamamlanan, 2.300 sonraya sarkan; sert teslim fizibilitesi deneyi | `%100 miktar mutabakatı`nı `%100 zamanında teslim` veya gerçek tesis kapasitesi diye yorumlamak |
| “Tahmin modelleri zaman sıralı backtest ile seçilir” | [15 Ekim yöntem ve sentetik koşum kaydı](global-evidence-audit-2026-10-15.md): ilk üç fold seçim, son fold ayrı holdout; WAPE/RMSE/bias ve Naive kıyası. [12 Ekim geri testi](forecast-v012-lab-evidence.md) tarihsel eski protokoldür | P10/P90'nın kalibre %80 aralığı, safety stock'un %90 servis garantisi veya gerçek müşteri doğruluğu |
| “Enerji/karbon model senaryosu hesaplanır” | Simüle kWh, varsayılan yakıt/şebeke katsayısı ve model girdileri | GHG Protocol uyumlu kurumsal envanter, gerçek karbon azaltımı |
| “Dar dosya pilotu teknik olarak denenebilir” | [CSV/XLSX ön kontrolü](../examples/pilot-package/README.md) ve [bellek içi çözüm](../examples/pilot-solve/README.md) | ERP/MES entegrasyonu, her proses tipi için hazır solver |

## Her sayı için beş alan

Sunum tablosuna konan her KPI veya grafik için **veri türü**, **snapshot/run ve tarih**, **hesap formülü/birim/ufuk**, **karşılaştırma koşulu**, **solver statüsü veya belirsizlik sınırı** yaz. ISO 22400'ün KPI tanım yaklaşımı bu disiplin için referanstır; [resmî ISO açıklaması](https://www.iso.org/standard/54497.html). Sayı dış müşteriye aitse veri sahibi izni ve anonimleştirme kuralı ayrıca belirlenir.

## İlk tesisle netleştirilecek yedi karar

1. Hat/ürün ailesi, planlama ufku ve karar sahibi.
2. Aynı karar anındaki mevcut plan ve ne zaman “uygulanmış plan” sayıldığı.
3. Sipariş, rota, işlem süresi, uygun makine, vardiya/duruş ve setup veri sözlüğü; boş/mükerrer alan davranışı.
4. WIP, kısmi iş, rework, hurda, operatör/kalıp/aparat ve malzeme çıkışının gerçek kuralları.
5. Önceden kararlaştırılmış termin, değişim, enerji, fazla mesai ve hizmet ölçütleri; veri dönemi ve hesap sahibi.
6. Salt okunur veri izni, güvenli aktarım, silme/saklama ve yetki sınırı.
7. Kabul/ret/override kaydı, gölge gözlem süresi ve durdurma koşulu.

Bu yanıtlar gelene kadar ürünün [G1 pilot sözleşmesi](pilot-charter.md) taslaktır. İlk görüşmenin amacı [problem keşfi rehberiyle](problem-discovery-guide.md) sahadan öğrenmek ve [ölçüm protokolüne](pilot-measurement-protocol.md) uygun dar bir çevrimdışı kıyas kurmaktır. G9 gölge pilotu ve G10–G11 saha/finans kabulü daha sonraki ayrı kararlardır.

[Metodolojik savunma raporu değerlendirmesindeki](methodological-defense-review-2026-10-14.md) edge-first, sabit %2,4 gap ve kuruş bazında kazanç içeren “resmî ifade” bu iddia sicilini aşar; sunum metni olarak kullanılmaz. Gölge gözlem A/B testi olarak tanıtılmaz.
