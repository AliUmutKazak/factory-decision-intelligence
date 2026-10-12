# 12 Ekim kalan işler raporu - uygulama izi

Kaynak: kullanıcı tarafından sağlanan `FDI_Tum_Kalan_Isler_ve_Yol_Haritasi_v1.0.pdf`, 10 sayfa, SHA-256 `82f08be89442d0a4ae8cba01f6058625d03041356e30348c3068a6237fb7c248`. Bu tablo raporun A1-A6/B1-B8 işlerini repo kanıtına bağlar; [G0-G13 kabul durumunun tek kayıt yeri](evidence-register.json) ve saha karar sahipleri değişmez. Kaynak PDF depoya kopyalanmadı. Durum bu branştaki işlere aittir; henüz main CI onayı veya yeni sürüm etiketi anlamına gelmez.

| İş | Depodaki sonuç | Kalan sınır |
|---|---|---|
| A1 sürüm uyuşmazlığı | [G0 matrisi](fdi-roadmap-execution.md#g0-g13-kapı-matrisi) ve paylaşım kartı `v0.1.2-lab` commit/CI/digest'ine bağlandı; `v0.1.0-lab` tarihsel kaldı | Sonraki kaynak commit'i için ayrı CI/tag gerekir |
| A2 tek kanıt envanteri | [JSON kayıt](evidence-register.json) ve CI'da [uyuşmazlık denetimi](../scripts/verify_evidence_register.py) | Saha kabulünde gerçek sahip/imza sonradan girilir |
| A3 paylaşım metni | README, [sunum iddia sicili](factory-presentation-evidence-pack.md), [kamuya açık metin taslağı](public-share-copy.md) güncel etikete bağlandı | Dış gönderim yapılmadı; yeni tag olursa metin güncellenir |
| A4 temiz demo | [Yeni klon provası](clean-demo-rehearsal-2026-10-12.md) pipeline, ACTIVE ve dosya örneklerini geçti | Bu branştaki yeni Docker USER kontrolü main/PR CI bekler |
| A5 pilot dosya paketi | [Sentetik örnek, kaynak/hash/ret ve veri işleme sınırı](../examples/pilot-package/README.md) var | Gerçek saklama süresi, izin ve anonimleştirme kararı G1/G4'te |
| A6 G8 kanıtı | [Son kodla JSP tekrarları](external-jsp-benchmark.md#v012-lab-koduyla-12-ekim-yeniden-ölçüm) ve [sentetik forecast geri testi](forecast-v012-lab-evidence.md) | `ft10` süre/kalite riski ve saha baseline'ı açık |
| B1 G1-T | [Referans profil](reference-pilot-profile.md) varsayımlı | Fabrika KPI/sahip kabulü G1'de |
| B2 G2-lab | Yerel ayrı roller, negatif testler, bağımlılık taraması; Docker image ayrıcalıksız kullanıcıya geçirildi | Yeni Docker/secret-log CI kanıtı bekler; IdP/TLS/IT kabulü sahada |
| B3 G3 tek host | [Bundle/ACTIVE restore provası](g3-active-restore-rehearsal.md), izolasyon ve kilit kanıtı | Canlı RTO/RPO ve çok host ancak saha mimarisiyle |
| B4 G4-T | [CSV/XLSX preflight](../examples/pilot-package/README.md) ve [dar solver alt kümesi](../examples/pilot-solve/README.md) | Müşteri mapping/birim/zaman izni ve gerçek veri bekler |
| B5 G5-T | [Yerel kalıcı dispatcher](g5-reschedule-dispatcher.md) ve inbox/outbox replay | Vendor round-trip/ACK bekler |
| B6 G6-T | [Sentetik execution replay](g6-synthetic-execution-replay.md) | Gerçek WIP/rework ve proses uzmanı kabulü bekler |
| B7 G7-lab | [Referans yük, üç olay ve timeout negatif kontrolü](g7-v012-lab-envelope.md) p50/p95, hata ve ACTIVE koruma ile kayıtlı | Gerçek SLO/alarm/yük dağılımı bekler |
| B8 G8-T | [JSP fizik kıyası](external-jsp-benchmark.md#v012-lab-koduyla-12-ekim-yeniden-ölçüm), [rolling-origin/Naive tahmin kıyası](forecast-v012-lab-evidence.md) ve maliyet-senaryo iddia sınırı | Gerçek plan, actuals ve finans kabulü G8/G11'de |

Saha G1, G4-G8, G9-G12 için fabrika, yetkili veri sahibi, proses, IT/MES ve finans kanıtı hâlâ gereklidir. G13 ayrı karar olarak kapsam dışıdır. Bu listenin laboratuvar satırı “Kabul edildi” işareti vermez.
