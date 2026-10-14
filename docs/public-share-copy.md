# FDI kamuya açık kısa anlatım taslağı

**Bağlam:** Son doğrulanmış laboratuvar sürümü `v0.1.7-lab`; [sürüm/CI/artifact kaydı](evidence-register.json) ve [iddia sicili](factory-presentation-evidence-pack.md) bu metnin sayısal sınırıdır. Yeni bir sürüm yayımlanırsa bağlantı ve test sayısı paylaşım öncesi güncellenir. Bu dosya yayımlanmış LinkedIn gönderisi değildir.

## Kısa paylaşım

> Üretim planlama kararlarında talep, kapasite, malzeme ve makine sırası birbirini etkiliyor. Factory Decision Intelligence projemde bu kararları izlenebilir tek bir akışta birleştiren, tek sunuculu bir karar destek prototipi geliştirdim. LP/MRP/CP-SAT planları, olay sonrası yeniden çizelgeleme ve karar kayıtları sentetik verilerle çalıştırılabiliyor. Sabit makineli açık job-shop örneklerinde aday çizelgeler ayrıca bağımsız fizik denetiminden geçiyor. İlk saha adımı için üretim sistemine yazmayan, izinli CSV/XLSX verisiyle dar bir karşılaştırma öneriyorum. Gerçek fabrika, ERP/MES ve ekonomik etki doğrulaması henüz yapılmadı. Doğrulanmış kod etiketi `v0.1.7-lab`; proje ve güncel kanıt belgeleri: https://github.com/AliUmutKazak/factory-decision-intelligence

## CV için kısa proje satırı

**Factory Decision Intelligence | Python, OR-Tools CP-SAT, PuLP, FastAPI, Streamlit.** Sentetik/açık veriyle tekrar üretilebilen üretim planlama ve makine çizelgeleme karar destek POC'si; sürüm kimliği, otomatik testler, Docker demo ve bağımsız sabit makineli çizelge denetimi. Gerçek tesis kabulü ayrı aşamadır.

## Paylaşım öncesi kontrol

1. Linki ve paylaşılacak tag'i aç; [G0 kaydındaki](fdi-roadmap-execution.md#g0-g13-kapı-matrisi) commit, CI ve artifakt kimliğiyle eşleştir.
2. Grafik veya ekran görüntüsü kullanılacaksa üzerinde `SYNTHETIC` ya da `OPEN BENCHMARK`, kaynak run, birim/ufuk ve solver statüsü görünür olsun. Eski görsel güncel sürüm kanıtı gibi kullanılmaz.
3. Müşteri tasarrufu, doğrulanmış karbon azaltımı, ERP/MES uyumu, üretim hazırlığı veya rakiplerden üstünlük iddiası ekleme. `ft10` 30 saniyelik kalite değişkenliğini sorulursa açıkça göster.
