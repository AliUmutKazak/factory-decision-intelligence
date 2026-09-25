# MRP ve Cizelgeleme Entegrasyon Mimarisi (Audit Madde 17)

## 1. Mevcut Mimari: Analitik Coupling (Prototip Fazı)
Mevcut platformda MRP ile CP-SAT cizelgeleyici arasindaki iliski **analitik baglama (analytical coupling)** prensibine dayanir:
- **Zaman Donusumu:** `lead_time_days -> weeks -> release_week` uzerinden kaba haftalik cizelgeye indirgenir.
- **Dinamik Gecikme Modeli:** MRP 1. haftada acil tedarik (`EXPEDITE (Past Due)`) gerektiren malzemeler icin:
  `delay_min = 480 + max(0, -rel_week) * 480`
  kuraliyla cizelgeye malzeme serbest kalma ofseti (release offset) enjekte edilir.

## 2. Gercek ERP / MES Coupling Icin Gereken Operasyonel Alanlar
Endustriyel olcekteki bir ERP/MES entegrasyonunda kaba hafta ve sabit vardiya ofsetleri yerine su operasyonel varliklar yonetilmelidir:
1. **planned_receipt & planned_release:** Siparis acilis ve planlanan kabul tarih damgalari.
2. **supplier_calendar:** Tedarikcinin resmi tatil, calisma gunleri ve lojistik transit sureleri.
3. **material_available_datetime:** Malzemenin kalite kontrol (`IQC - Incoming Quality Control`) sonrasi rafa/uretim bandina fiziki inis ani.
4. **open PO (Acik Satin Alma Siparisleri):** Fiili tedarikci siparis teyitleri ve vadesi gelen siparisler.
5. **goods receipt & supplier capacity:** Mal kabul fisleri, tedarikci kapasite kotalari ve kisitlari.

## 3. Mimari Durus
Mevcut analitik modelleme karar destek prototipi olarak tutulmakta; endustriyel MES/ERP veri kontrati sonraki buyuk entegrasyon fazi icin backlog kapsaminda izlenmektedir.