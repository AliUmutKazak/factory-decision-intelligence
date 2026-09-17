import os
import pandas as pd

# 1. Proje Klasör Ağacını İnşa Et
directories = [
    "data/raw",
    "data/processed",
    "data/synthetic",
    "notebooks",
    "src/data",
    "src/forecasting",
    "src/inventory",
    "src/scheduling",
    "src/energy",
    "src/carbon",
    "src/reporting",
    "dashboard",
    "tests",
]

for directory in directories:
    os.makedirs(directory, exist_ok=True)

# 2. Sentetik Fabrika Ana Verilerini (Master Data) Hazırla

# A. Makineler (Kapasite, Sabit Güç ve Maliyet)
machines_data = {
    "machine_id": ["M01", "M02", "M03"],
    "machine_name": ["CNC Torna & Freze", "Kaynak Robotu", "Yüzey İşlem & Fırın"],
    "base_power_kw": [4.5, 3.2, 8.0],  # Rölanti / taban güç
    "operating_cost_per_hour": [650.0, 520.0, 780.0],  # TL/saat
    "max_daily_hours": [16, 16, 16],  # 2 vardiya planı
}
pd.DataFrame(machines_data).to_csv("data/synthetic/machines.csv", index=False)

# B. Ürünler (5 Endüstriyel Parça)
products_data = {
    "product_id": ["P01", "P02", "P03", "P04", "P05"],
    "product_name": [
        "Şasi Bağlantı Braketi",
        "Flanş Gövdesi",
        "Aks Mili",
        "Hidrolik Valf Kapağı",
        "Rulman Taşıyıcı Gövde",
    ],
    "unit_sale_price": [1250.0, 1850.0, 2400.0, 980.0, 1600.0],
    "holding_cost_per_week": [12.0, 18.0, 25.0, 10.0, 15.0],
    "late_penalty_per_day": [150.0, 220.0, 300.0, 120.0, 200.0],
}
pd.DataFrame(products_data).to_csv("data/synthetic/products.csv", index=False)

# C. Hammaddeler ve Tedarikçi Bilgileri
materials_data = {
    "material_id": ["RAW_STEEL_A", "RAW_STEEL_B", "RAW_ALLOY_ROD", "COATING_POWDER"],
    "material_name": ["Sac Plaka 4mm", "Yapısal Çelik Sac 8mm", "Alaşımlı Çelik Mil", "Elektrostatik Toz Boya"],
    "unit": ["kg", "kg", "kg", "kg"],
    "unit_cost": [38.5, 42.0, 78.0, 160.0],
    "supplier_id": ["SUP_01", "SUP_01", "SUP_02", "SUP_03"],
    "lead_time_days": [7, 7, 12, 4],
    "min_order_qty": [500, 400, 250, 50],
}
pd.DataFrame(materials_data).to_csv("data/synthetic/materials.csv", index=False)

# D. Ürün Ağacı (BOM) — Satış Talebini Hammaddeye Bağlayan Köprü
bom_data = {
    "product_id": ["P01", "P01", "P02", "P02", "P03", "P04", "P05", "P05"],
    "material_id": [
        "RAW_STEEL_A", "COATING_POWDER",
        "RAW_STEEL_B", "COATING_POWDER",
        "RAW_ALLOY_ROD",
        "RAW_STEEL_A",
        "RAW_STEEL_B", "COATING_POWDER",
    ],
    "qty_per_unit": [2.8, 0.15, 4.2, 0.20, 5.5, 1.4, 3.1, 0.18],
}
pd.DataFrame(bom_data).to_csv("data/synthetic/bom.csv", index=False)

# E. Rota, İşlem Süreleri ve Değişken Enerji (Routing & Processing)
routing_data = {
    "product_id": [
        "P01", "P01", "P01",
        "P02", "P02", "P02",
        "P03", "P03",
        "P04", "P04",
        "P05", "P05", "P05",
    ],
    "operation_seq": [1, 2, 3, 1, 2, 3, 1, 2, 1, 2, 1, 2, 3],
    "machine_id": [
        "M01", "M02", "M03",
        "M01", "M02", "M03",
        "M01", "M02",
        "M01", "M03",
        "M01", "M02", "M03",
    ],
    "processing_time_min": [
        18, 12, 15,
        24, 16, 20,
        35, 10,
        14, 12,
        22, 14, 18,
    ],
    "variable_kwh_per_unit": [
        0.65, 0.45, 1.20,
        0.90, 0.60, 1.45,
        1.40, 0.35,
        0.50, 0.95,
        0.80, 0.50, 1.30,
    ],
}
pd.DataFrame(routing_data).to_csv("data/synthetic/routing.csv", index=False)

# F. Sıra Bağımlı Hazırlık Matrisi (Sequence-Dependent Changeover Matrix)
changeover_records = []
products = ["P01", "P02", "P03", "P04", "P05"]
base_changeover = {
    ("P01", "P02"): (25, 300), ("P01", "P03"): (40, 500), ("P01", "P04"): (20, 250), ("P01", "P05"): (30, 350),
    ("P02", "P01"): (25, 300), ("P02", "P03"): (45, 550), ("P02", "P04"): (30, 350), ("P02", "P05"): (20, 250),
    ("P03", "P01"): (40, 500), ("P03", "P02"): (45, 550), ("P03", "P04"): (35, 400), ("P03", "P05"): (35, 400),
    ("P04", "P01"): (20, 250), ("P04", "P02"): (30, 350), ("P04", "P03"): (35, 400), ("P04", "P05"): (25, 300),
    ("P05", "P01"): (30, 350), ("P05", "P02"): (20, 250), ("P05", "P03"): (35, 400), ("P05", "P04"): (25, 300),
}

for f_p in products:
    for t_p in products:
        if f_p == t_p:
            time_m, cost_m = 0, 0.0
        else:
            time_m, cost_m = base_changeover.get((f_p, t_p), (30, 350))
        changeover_records.append({
            "from_product": f_p,
            "to_product": t_p,
            "setup_time_min": time_m,
            "setup_cost": cost_m,
        })

pd.DataFrame(changeover_records).to_csv("data/synthetic/changeover_matrix.csv", index=False)

print("=" * 60)
print("FABRİKA KARAR DESTEK PLATFORMU: ALTYAPI KURULUMU TAMAMLANDI")
print("=" * 60)
print("[OK] Klasör yapısı inşa edildi.")
print("[OK] data/synthetic/ altında 6 ana tablo oluşturuldu:")
print("     - machines.csv, products.csv, materials.csv")
print("     - bom.csv, routing.csv, changeover_matrix.csv")
print("=" * 60)
