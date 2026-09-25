# Cizelgeleme Amac Fonksiyonu ve Operasyonel Yol Haritasi (Audit Madde 16)

## 1. Mevcut Mimari Durum (Faz 1)
- **Amac Fonksiyonu:** Salt Makespan Minimizasyonu (min C_max).
- **Yurutme Politikasi:** CROSS_WEEK_SPILLOVER_ALLOWED (cross_week_execution_allowed = 1).
- **Kapsam:** Siparislerin en erken surede tamamlanmasi hedeflenir; haftalik ufkun asilmasina izin verilir.

## 2. Operasyonel Bosluk ve Fabrika Ihtiyaci
Gercek uretim ortaminda salt makespan minimizasyonu su operasyonel dinamikleri dikkate almaz:
1. **Musteri Termin Tarihi (Due Date):** Siparisin erken bitmesinden ziyade terminine yetismesi esastir.
2. **Gecikme (Tardiness / Lateness):** Ceza maliyetleri minimize edilmelidir.
3. **Fazla Mesai (Overtime Cost):** Gece vardiyasi ve hafta sonu fazla mesai primleri agirliklandirilmalidir.
4. **Siraya Bagli Ayar Sureleri (Sequence-Dependent Setup Times):** Tezgah ayar/kalip degisim sureleri minimize edilmelidir.
5. **Oncelik ve Malzeme Hazirligi (Priority & Material Availability):** Kritik musteri siparisleri ve hammadde varis pencereleri gozetilmelidir.

## 3. Hedef Cok Amacli Fonksiyon (Faz 2 Modelleme)
Sonraki buyuk modelleme fazinda CP-SAT cozucusu icin agirlikli cok amacli hedef fonksiyonu kurgulanacaktir:

min [ alpha * C_max + beta * Sum(w_i * Tardiness_i) + gamma * Sum(Cost_OT_m) + delta * Sum(Setup_Time_jk) ]