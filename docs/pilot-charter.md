# G1 pilot kapsamı ve kabul sözleşmesi — taslak

Durum: **Bekliyor**. Proje sahibi 7 Ekim 2026'da henüz pilot fabrika, temsilî müşteri verisi ve ERP/MES test erişimi olmadığını bildirdi. Bu form, `FDI_Nihai_Birlesik_Yol_Haritasi.pdf` G1 kararlarını tek yerde toplar. Fabrika planlama ve IT/MES sahipleri doldurup onaylamadan pilot kapsamı kabul edilmiş sayılmaz. Bilinmeyen alanlar varsayımla doldurulmaz.

## 1. Kapsam ve yetki

| Karar | Kaydedilecek yanıt | Durum / karar sahibi |
|---|---|---|
| Pilot tesis, hat ve ürün aileleri | Tesis/hat kimliği, dahil ve hariç ürünler | Bekliyor — pilot sahibi |
| Planlama ufku ve çevrim | Ufuk, yeniden planlama sıklığı, saat dilimi | Bekliyor — planlamacı |
| Çalışma modu | Yalnız öneri/gölge; üretim talimatı göndermeme sınırı; kontrollü üretime geçiş ayrı G10 | Bekliyor — fabrika sahibi |
| Plan onayı ve geri dönüş | Onaylayan rol, ret/override nedeni, son doğrulanmış plana dönüş sorumlusu | Bekliyor — planlamacı + IT/OT |
| Freeze ve başlamış iş | Dondurulmuş ufuk, kısmi üretim, kesinti, taşıma, setup ve rework kuralları | Bekliyor — proses uzmanı |
| Hizmet hedefleri | Solve süresi p50/p95, veri tazeliği, API/job hata ve alarm tepkisi | Bekliyor — pilot sahibi + platform |
| Veri saklama ve erişim | Kimlik sağlayıcı, yetkiler, saklama süresi, backup ve geri yükleme sahibi | Bekliyor — IT/MES + veri sahibi |

## 2. Sistem ve veri sahipliği

ERP ve MES için vendor/sürüm, test tenant, endpoint/transport, sözleşme ve irtibat kişisi kaydedilecek. Aşağıdaki her alanın yetkili kaynağı, birimi, kimlik eşlemesi ve gecikme beklentisi yazılacak:

- Sipariş, lot, ürün ve öncelik; miktar/birim, due date ve planlama anında bilinen değişiklikler.
- Çok seviyeli BOM, routing/operasyon sırası, alternatif makine, işlem ve setup süreleri.
- Vardiya, mola, bakım, stok, açık satın alma, lead time ve MOQ; fiziksel gerekiyorsa operatör/kalıp/aparat ve WIP sınırları.
- MES actuals: planlandı, başladı, kısmen tamamlandı, kesildi, devam etti, tamamlandı; hurda ve rework ayrı. Her olayda lot/operasyon kimliği, olay zamanı, miktar ve kaynak bulunacak.

Geçersiz referans, negatif veya sonlu olmayan değer, birim/zaman dilimi uyuşmazlığı, BOM/routing döngüsü, duplicate/geç/sırasız actuals ve kaynak gecikmesi ayrı reject gerekçesiyle kaydedilir. Sentetik kayıt gerçek müşteri verisi yerine geçirilmez.

## 3. KPI ve karşılaştırma sözleşmesi

Her satır için **eşik, dönem, kapsam, pay/payda, veri kaynağı, sorumlu ve kaynak run kimliği** G1'de belirlenecek. Mevcut kod veya demo sayıları fabrika hedefi değildir.

| KPI | Ölçüm kararı / kabul sahibi |
|---|---|
| Forecast SKU/aile WAPE, bias ve drift | Rolling-origin dönemleri, basit baseline, seyrek/sıfır talep yorumu — veri sahibi + planlamacı |
| Fiziksel plan doğruluğu | Makine/kaynak çakışması, routing, malzeme, vardiya, freeze: kabul edilen planda sıfır ihlal — proses uzmanı |
| Solver işletimi | p50/p95 süre, timeout/infeasible/fallback oranı ve çözüm statüsü — platform + planlamacı |
| Hizmet | API/job hatası, ACTIVE yaşı, actuals gecikmesi, alarm tepki süresi — IT/MES |
| Gölge pilot | İncelemeye uygun önerilerde kabul/ret/kısmi kabul/override, gerekçeler, plan-actual sapması ve nervousness — pilot sahibi |
| Maliyet | Solver objective'den bağımsız maliyet hesabı, tolerans ve actuals/finans uzlaştırması — finans |
| Kurtarma | Restore süresi, veri kaybı penceresi, rollback ve manuel işletim — IT/OT + fabrika |

Fabrikanın fiilî planı ana karşılaştırmadır. FDI ve fiilî plan aynı bilgi kesiti, siparişler, kaynaklar, fiziksel kurallar ve ufukla değerlendirilir. FIFO/EDD/SPT yardımcı referanslardır. `FEASIBLE` global optimum olarak sunulmaz. Gölge pilotta öneri, insan kararı, uygulanmış plan ve actuals ayrı saklanır; uygulanmayan önerinin teorik kazanımı gerçekleşmiş ROI değildir.

## 4. Kabul ve açık sorular

- Pilot sahibi / planlama onayı: **bekliyor**.
- IT/MES veri, test erişimi ve güvenlik onayı: **bekliyor**.
- Finans ölçüm dönemi ve maliyet yöntemi: **bekliyor**.
- İlk veri snapshot'ı ve gerçek plan örneği: **bekliyor**.
- G1 kabul tarihi, kabul veren kişiler ve karar kaydı: **bekliyor**.

G1 tamamlandıktan sonra G2-G8 işlerinin eşikleri ve eforu bu kayıt üzerinden yeniden hesaplanır. Bu taslağın varlığı G1'in geçtiği anlamına gelmez.
