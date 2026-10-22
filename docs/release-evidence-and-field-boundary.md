# Sürüm kanıtı ve saha kabul sınırı

**Durum:** 22 Ekim 2026. Bu kart, [G0–G13 uygulama kaydındaki](fdi-roadmap-execution.md) kabul kapılarını değiştirmez. Son doğrulanmış sürüm `v0.1.10-lab` (`57e2ebcba171a2533b78601ec580177f3d779b05`); aynı commit'teki [CI 39772987004](https://github.com/AliUmutKazak/factory-decision-intelligence/actions/runs/39772987004) 416 test ve Docker işlerinde başarılıdır. Artifakt SHA-256 değeri [G0 kaydında](fdi-roadmap-execution.md#g0-g13-kapı-matrisi) tutulur. [Temiz Windows klonu](clean-demo-v010-2026-10-22.md) ayrıca geçti. Sonraki kaynak commit'i bu sürüm kanıtını devralmaz. [Uluslararası yöntem denetimi](global-evidence-audit-2026-10-15.md), [Türkiye/dünya denetimi](tr-global-science-market-audit-2026-10-11.md) ve [sunum paketi](factory-presentation-evidence-pack.md) iddia sınırını günceller.

## Paylaşılabilir teknik sürüm için kabul listesi

| Kontrol | Bugünkü kanıt veya açık iş | Kabul ölçüsü |
|---|---|---|
| Açık ürün tanımı | README, demo ve yol haritası POC sınırını anlatıyor | İlk sayfada amaç, tek sunuculu kapsam, sentetik/açık veri ve yapılmamış saha kabulü görünür |
| Tekrarlanabilirlik | `v0.1.10-lab` main CI'ında kalite/test ve Docker başlangıç/yeniden başlatma başarılı; [aynı commit'in temiz klon provasında](clean-demo-v010-2026-10-22.md) uçtan uca run, ACTIVE doğrulama ve iki sentetik dosya örneği geçti | Paylaşılacak **aynı commit** üzerinde iki CI işi başarılı; temiz klonda kurulum ve `verify_active_run.py` başarılı |
| Gösterim | Ölçülmüş sentetik benchmark ve [demo rehberi](demo-and-customer-pilot.md) var; eski ekran görüntüleri güncel commit kanıtı değildir | İzleyici örneği çalıştırabilir; sonuçlar veri türü ve solver sınırıyla birlikte okunur; kullanılacak görseller güncel sürümden alınır |
| Güvenli kullanım | [G2 sınırı](security-boundary.md): API ve panel varsayılan kapalı; ayrık yerel erişim anahtarları var, Compose portları yerel adrese bağlı. [Pillow danışma istisnası](dependency-security-2026-10-11.md) açık ve süreli | Demo yalnız yerel/denetimli ortamda gösterilir; internetten API veya dashboard erişimi açılmaz |
| Lisans ve kaynaklar | Proje kodu için kök `LICENSE` ve MESA şemaları için kendi lisans dosyası | README lisans beyanı gerçek dosyalara bağlanır; üçüncü taraf şemalar MIT kapsamı gibi sunulmaz |
| Sürüm kaydı | Başarılı main CI, 30 gün tutulan run artifact'i ve digest'ini üretir; container image ve ayrı GitHub Release sayfası yayımlanmıyor | G0 teknik kanıtı için tag aynı başarılı main commit'ine bağlanır; sürüm numarası, commit, test/CI bağlantısı ve artifact kimliği belirtilir. Kamuya açık kurulum kod/tag üzerinden yapılır. |

Bu liste tamamlanınca kullanılacak ifade **“teknik olarak gösterilebilir karar destek POC”** olabilir. “Fabrikada doğrulandı”, “ERP/MES ile uyumlu”, “üretime hazır”, “tasarruf/ROI sağladı” ifadeleri için G1 ve ilgili G4–G11 saha kanıtları gerekir. Açık benchmark'ta çözülen sabit makineli alt problem, esnek atölye veya müşteri problemiyle eşdeğer gösterilmez.

## Fabrika bulunduğunda ayrı kabul yolu

1. **G1:** Tek tesis/hat/ürün ailesi, planlama sahibi, veri izni, karşılaştırma ölçüsü ve karar rollerini [pilot sözleşmesinde](pilot-charter.md) belirle.
2. **G4–G8:** Gerçek dosyaların alan, birim, zaman, rota ve makine kurallarını doğrula; mevcut fabrika planıyla aynı karar anında çevrimdışı karşılaştır.
3. **G9:** FDI önerisi ile insan kararını ve uygulanmış planı actuals'a bağlayan gölge gözlemi yap; üretim sistemine otomatik talimat gönderme.
4. **G10–G11:** Yalnız kabul edilen kapsamda kontrollü işletim, geri dönüş ve finans tarafından uzlaştırılmış gerçekleşmiş faydayı ölç.

Fabrika bağlantısı olmaması kodu, CI'ı, bağımsız kıyası veya demo açıklığını geliştirmeyi durdurmaz. Fabrika arayışı [fabrika bağımsız teknik hazırlıkların](scheduler-scope-comparison.md) sonrasına bırakılır. Paylaşım sırasında erken ilgi gelirse kaydedilir; ilgi başlı başına pilot kabulü sayılmaz. G1 görüşmesinde gerçek tesis, kapsam ve izinler ayrıca kararlaştırılır. [problem keşfi rehberi](problem-discovery-guide.md) ilk görüşmede sorulacak bilgileri listeler.
