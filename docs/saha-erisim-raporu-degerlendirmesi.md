# Saha erişimi araştırması: FDI için karar kaydı

Kaynak: `FDI_Saha_Erisimi_Bilimsel_Degerlendirme.pdf`, v1.0, 8 Ekim 2026, 11 sayfa, SHA-256 `0e5f974d2b9c214cfcf7f4ff02db39c31de345041c24aee69e7289d6a5065a58`. Bu kayıt, [birleşik yol haritasının](fdi-roadmap-execution.md) G4-T ve G8-T teknik hazırlığını ayrıntılandırır; G0-G13 saha kabul kapılarını değiştirmez.

## Karar

**Uygun, koşullu olarak uygulanmalı.** Araştırmanın en yararlı katkısı dış çizelgeleme örnekleriyle veri aktarımını sınamak ve CP-SAT kısıt kodunu kullanmayan ayrı bir uygunluk denetleyicisi kurmaktır. Böylece aynı modelin ürettiği planı aynı modelle tekrar doğrulama riski azalır. Kaynak kökeni, zaman birimleri, gözlenen/hesaplanan/senaryo değerlerin ayrılması ve eşit koşullarda kıyas da mevcut G4-T/G8-T işine doğrudan uyar.

**Kritik uyum bulgusu:** Mevcut `routing` tablosunun anahtarı `(product_id, operation_seq)` ve her satırda tek `machine_id` vardır. Üretim CP-SAT görevleri de bu makineye sabitler. Dolayısıyla üretim çekirdeği genel FJSP'deki **operasyon başına alternatif makine seçimini desteklemiyor**. Mk01'in 10 iş, 6 makine ve 55 operasyonu okunabilse de doğrudan aynı FJSP problemi olarak üretim çözücüsünde çalıştırılamaz. Bu bulgu, rapordaki TU/e Mk01'i *ilk dış aktarım ve bağımsız kontrol örneği* olarak yararlı; *doğrudan algoritma kıyası* olarak koşullu yapar.

Kaynak denetimi: [TU/e araştırma yayını](https://link.springer.com/article/10.1007/s10472-026-10007-3) ve [resmi benchmark deposu](https://github.com/ai-for-decision-making-tue/Job_Shop_Scheduling_Benchmark_Environments_and_Instances) FJSP ve başka varyantları ayrı ele alıyor; depodaki yöntem tablosu CP-SAT için dinamik JSP desteği göstermiyor. [Mendeley Data v1](https://data.mendeley.com/datasets/h66hb89k6z/1) altı Excel dosyası ve CC BY 4.0 lisansı bildiriyor. Dosyaların içerik sayıları ve `Due Dates = Day × 1440` bulgusu bu kayıt için yalnız PDF'nin dosya incelemesine dayanıyor; FDI'nin kendi indirme/hash/alan denetimi tamamlanmadan yeniden doğrulanmış sonuç sayılmaz.

## Projeye uyum ve sınırlar

| Öneri | Uyum | Uygulama sınırı |
|---|---|---|
| TU/e Mk01 gibi dış FJSP örneği | Veri aktarımı/denetim için yüksek, mevcut çözücüyle doğrudan kıyas için düşük | Mk01 alternatif makineleri koruyarak okunup bağımsız denetlenebilir. Üretim modeliyle ilk çözüm kıyası için önce sabit makineli JSP örneği seç veya makine atamasını önceden sabitleyen bir projeksiyonu **ayrı problem** olarak etiketle. Mk01 FJSP optimumuyla kıyas yapma. Takvim, setup, malzeme ve maliyet farklarını da açıkla. |
| Bağımsız çizelge denetleyicisi | G6-T/G8-T için yüksek | Solverın kendi kısıt fonksiyonlarını çağırmadan atama, süre, öncüllük, makine çakışması ve kapsamda olan ek kuralları denetle. Önce küçük elle izlenebilir ve bilerek bozulmuş örneklerle sınanmalı. |
| Açık ambalaj verisi | G4-T için orta | Alan sözlüğü ve ortak zaman ekseniyle küçük veri uyumu denemesi. Kopya Excel sayfalarını birleştirme; hızdan türetilen süreyi **hesaplanmış** diye işaretle. Operasyon actuals, duruş ve fiili maliyet yoksa sonuçları gerçekleşmiş fabrika performansı olarak sunma. |
| TLSP laboratuvar verisi | Şimdilik düşük | Personel ve ekipman kısıtları mevcut FDI kapsamıyla eşleşirse ikinci adım. Eksik `environment.xml` ve belirsiz yeniden dağıtım koşulu çözülmeden tam aktarım iddiası yok. |
| NIST sinyalleri | Şimdilik düşük | Yalnız makine olay aktarımı ihtiyacı doğarsa. Ham sinyali doğrudan arıza veya sipariş tamamlanması sayma. |

İlk dosya pilotunu geçmiş veriyle, dar kapsamda ve salt okunur yürütme önerisi [mevcut referans pilot profiliyle](reference-pilot-profile.md) uyumludur. Bu yol ERP/MES vendor kabulünü, operatör değerlendirmesini veya gerçekleşmiş tasarrufu sağlamaz. Pilot fabrika/veri sahibi hâlâ dış bağımlılıktır.

## Sıralı teknik karar

1. Üretim çekirdeğinin bugünkü **sabit makine rotalı JSP** alt kümesini ve kapsam dışı kısıtları yaz. Eşleştirilecek birincil fiziksel ölçü makespan olsun; üretim maliyeti ayrı kalsın. Alternatif makine seçimi yeni çekirdek işidir, benchmark sonucu için sessizce varsayılmasın.
2. Kaynak sürümü sabit küçük örnek için salt okunur ayrıştırıcı ve dönüşüm raporu oluştur. İş/operasyon/makine sayısını, kimlikleri, süre birimini ve kaynak hash'ini koru.
3. Bağımsız uygunluk denetleyicisi ekle. Olumlu ve bilerek bozulmuş küçük örnekleri, sonra dış örneği sınayarak güven oluştur.
4. Sabit makineli örnek için üretim modelinin ek takvim/setup/malzeme kurallarını nötrleştirmek veya aynı kuralları bağımsız referansa taşımak mümkünse aynı kurallar ve bütçelerle kıyasla. Değilse metrikleri yan yana raporla, üstünlük yüzdesi üretme. Başarısızlık ve zaman aşımını da sakla.
5. Ambalaj verisini ayrı veri uyumu denemesi olarak ele al. Alan anlamı çözülemezse çizelge sonuçlandırma.

**İlk teknik adım:** `src/scheduling/fjsp_reference.py` düz Brandimarte FJSP metnini ayrıştırır ve çizelgeyi üretim solverından bağımsız olarak atama, süre, işlem önceliği ve makine çakışması açısından denetler. Elle kontrol edilen olumlu ve bilerek bozulmuş örnekler test edildi. TU/e deposunun `d088a26582f5cb79c6b4f2ad94f68ac7c50878cb` sürümündeki `data/fjsp/brandimarte/Mk01.fjs` dosyası geçici alanda okundu: SHA-256 `c0bed4ae79833ab73adcc653dd85c7cdfd66bb8c6a9744ae781719d191e6e14d`, 10 iş, 6 makine ve 55 operasyon. Kaynak veri depoya eklenmedi.

**Açık sınır:** Bu, dış örneğin üretim CP-SAT modeline aktarılıp çözüldüğü anlamına gelmez. Denetleyici yalnız düz statik FJSP alt kümesini kapsar; takvim, setup, malzeme, WIP, donmuş işler, maliyet ve dinamik olaylar ayrıca tanımlanıp doğrulanmalıdır. Yerel `pilot_preflight` kanonik sentetik CSV için yapısal ön kontroldür; dış Excel dosyalarını veya üretim çizelgesinin fiziksel uygunluğunu doğrulamaz.
