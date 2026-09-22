import os
import sqlite3
import pandas as pd
import numpy as np
from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    SYNTHETIC_DATA_DIR,
)

PROCESSED_ORDERS_PATH = PROCESSED_DATA_DIR / "factory_orders.csv"

def analyze_demand_characteristics(orders_df: pd.DataFrame) -> pd.DataFrame:
    daily_product_demand = (
        orders_df.groupby(["order_date", "product_id"])["order_qty"]
        .sum()
        .reset_index()
    )

    stats = (
        daily_product_demand.groupby("product_id")["order_qty"]
        .agg(
            gunluk_ortalama="mean",
            gunluk_std="std",
            min_talep="min",
            max_talep="max",
            toplam_talep="sum"
        )
        .reset_index()
    )

    # Varyasyon Katsayısı (CV = sigma / mu)
    stats["cv_volatilite"] = (stats["gunluk_std"] / stats["gunluk_ortalama"]).round(3)
    stats["talep_profili"] = np.where(
        stats["cv_volatilite"] < 0.5, "Düzenli (Smooth)", "Dalgalı (Erratic)"
    )

    stats["gunluk_ortalama"] = stats["gunluk_ortalama"].round(1)
    stats["gunluk_std"] = stats["gunluk_std"].round(1)

    return stats

def validate_master_data(data_dict):
    """
    Kritik Master Data Validasyon Motoru (Fail-Fast).
    Şema, null, tekillik, negatif değer, ilişkisel bütünlük ve BOM/Routing kapsamını doğrular.
    """
    # 1. Zorunlu Kolon Haritası
    required_cols = {
        "machines": ["machine_id", "machine_name", "base_power_kw", "operating_cost_per_hour", "max_daily_hours"],
        "products": ["product_id", "product_name", "family_id"],
        "materials": ["material_id", "material_name"],
        "bom": ["product_id", "material_id", "qty_per_unit"],
        "routing": ["product_id", "operation_seq", "machine_id", "processing_time_min"],
        "changeover_matrix": ["from_product", "to_product", "setup_time_min"]
    }

    # 2. Şema, Null ve Negatif Değer Kontrolleri
    for tbl_name, req_list in required_cols.items():
        df = data_dict[tbl_name]
        missing = [c for c in req_list if c not in df.columns]
        if missing:
            raise ValueError(f"[MASTER DATA ERROR] '{tbl_name}' tablosunda zorunlu sütunlar eksik: {missing}")
        
        # Null kontrolü
        null_counts = df[req_list].isnull().sum()
        if null_counts.any():
            raise ValueError(f"[MASTER DATA ERROR] '{tbl_name}' tablosunda boş (null) değer tespit edildi:\n{null_counts[null_counts > 0]}")

    # 3. Sayısal Alanlarda Negatif Değer Kontrolü
    num_checks = [
        ("machines", ["base_power_kw", "operating_cost_per_hour", "max_daily_hours"]),
        ("bom", ["qty_per_unit"]),
        ("routing", ["processing_time_min"]),
        ("changeover_matrix", ["setup_time_min"])
    ]
    for tbl_name, cols in num_checks:
        df = data_dict[tbl_name]
        for c in cols:
            if (df[c] < 0).any():
                raise ValueError(f"[MASTER DATA ERROR] '{tbl_name}.{c}' alanında negatif değer tespit edildi!")

    # 4. Tekil Anahtar Kontrolü (Duplicate Keys)
    if data_dict["machines"]["machine_id"].duplicated().any():
        dups = data_dict["machines"]["machine_id"][data_dict["machines"]["machine_id"].duplicated()].tolist()
        raise ValueError(f"[MASTER DATA ERROR] 'machines' tablosunda yinelenen machine_id: {dups}")
    
    if data_dict["products"]["product_id"].duplicated().any():
        dups = data_dict["products"]["product_id"][data_dict["products"]["product_id"].duplicated()].tolist()
        raise ValueError(f"[MASTER DATA ERROR] 'products' tablosunda yinelenen product_id: {dups}")

    # 5. İlişkisel Bütünlük (Referential Integrity)
    valid_products = set(data_dict["products"]["product_id"])
    valid_machines = set(data_dict["machines"]["machine_id"])
    valid_materials = set(data_dict["materials"]["material_id"])
    # BOM -> Products & Materials
    bom_products = set(data_dict["bom"]["product_id"])
    bom_materials = set(data_dict["bom"]["material_id"])
    if not bom_products.issubset(valid_products):
        raise ValueError(f"[MASTER DATA ERROR] 'bom' içinde tanımsız product_id: {bom_products - valid_products}")
    if not bom_materials.issubset(valid_materials):
        raise ValueError(f"[MASTER DATA ERROR] 'bom' içinde tanımsız material_id: {bom_materials - valid_materials}")

    # Routing -> Products & Machines
    routing_products = set(data_dict["routing"]["product_id"])
    routing_machines = set(data_dict["routing"]["machine_id"])
    if not routing_products.issubset(valid_products):
        raise ValueError(f"[MASTER DATA ERROR] 'routing' içinde tanımsız product_id: {routing_products - valid_products}")
    if not routing_machines.issubset(valid_machines):
        raise ValueError(f"[MASTER DATA ERROR] 'routing' içinde tanımsız machine_id: {routing_machines - valid_machines}")

    # 6. Kapsama Doğrulamaları (Coverage & Completeness)
    missing_bom = valid_products - bom_products
    if missing_bom:
        raise ValueError(f"[MASTER DATA ERROR] Şu ürünler için BOM tanımı bulunamadı: {missing_bom}")

    missing_routing = valid_products - routing_products
    if missing_routing:
        raise ValueError(f"[MASTER DATA ERROR] Şu ürünler için Rota tanımı bulunamadı: {missing_routing}")

    # Changeover matrix completeness (her ürün çifti matriste tanımlı mı?)
    co_df = data_dict["changeover_matrix"]
    existing_pairs = set(zip(co_df["from_product"], co_df["to_product"]))
    all_pairs = {(p1, p2) for p1 in valid_products for p2 in valid_products}
    missing_pairs = all_pairs - existing_pairs
    if missing_pairs:
        raise ValueError(f"[MASTER DATA ERROR] 'changeover_matrix' eksik ürün geçişleri içeriyor: {missing_pairs}")

    # BOM -> Products & Materials
    bom_products = set(data_dict["bom"]["product_id"])
    bom_materials = set(data_dict["bom"]["material_id"])
    if not bom_products.issubset(valid_products):
        raise ValueError(f"[MASTER DATA ERROR] 'bom' içinde tanımsız product_id: {bom_products - valid_products}")
    if not bom_materials.issubset(valid_materials):
        raise ValueError(f"[MASTER DATA ERROR] 'bom' içinde tanımsız material_id: {bom_materials - valid_materials}")

    # Routing -> Products & Machines
    routing_products = set(data_dict["routing"]["product_id"])
    routing_machines = set(data_dict["routing"]["machine_id"])
    if not routing_products.issubset(valid_products):
        raise ValueError(f"[MASTER DATA ERROR] 'routing' içinde tanımsız product_id: {routing_products - valid_products}")
    if not routing_machines.issubset(valid_machines):
        raise ValueError(f"[MASTER DATA ERROR] 'routing' içinde tanımsız machine_id: {routing_machines - valid_machines}")

    # 6. Kapsama Doğrulamaları (Coverage & Completeness)
    missing_bom = valid_products - bom_products
    if missing_bom:
        raise ValueError(f"[MASTER DATA ERROR] Şu ürünler için BOM tanımı bulunamadı: {missing_bom}")

    missing_routing = valid_products - routing_products
    if missing_routing:
        raise ValueError(f"[MASTER DATA ERROR] Şu ürünler için Rota (Routing) tanımı bulunamadı: {missing_routing}")

    # Changeover matrix completeness (her ikili var mı?)
    co_df = data_dict["changeover_matrix"]
    eexisting_pairs = set(zip(co_df["from_product"], co_df["to_product"]))
    all_pairs = {(p1, p2) for p1 in valid_products for p2 in valid_products}
    missing_pairs = all_pairs - existing_pairs
    if missing_pairs:
        raise ValueError(f"[MASTER DATA ERROR] 'changeover_matrix' eksik ürün geçişleri içeriyor: {missing_pairs}")

def initialize_database(force_recreate: bool = False):
    """
    Veritabanını SSOT (Single Source of Truth) ilkelerine uygun şekilde başlatır ve eşitler.
    Dosyayı tamamen silmek yerine idempotent tablo senkronizasyonu yapar ve
    her icra için 'pipeline_runs' denetim kaydı oluşturur.
    """
    import uuid
    from datetime import datetime
    import gc
    gc.collect()

    if force_recreate and os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            conn_temp = sqlite3.connect(DB_PATH)
            cur = conn_temp.cursor()
            cur.execute("PRAGMA writable_schema = 1;")
            cur.execute("DELETE FROM sqlite_master WHERE type IN ('table', 'index', 'trigger');")
            cur.execute("PRAGMA writable_schema = 0;")
            conn_temp.commit()
            cur.execute("VACUUM;")
            conn_temp.close()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 0. SSOT Denetim Çizelgesi (Pipeline Run Audit Log)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            trigger_source TEXT NOT NULL,
            orders_count INTEGER NOT NULL,
            status TEXT NOT NULL
        )
    """)
    conn.commit()

    # 1. İşlenmiş sipariş verisini aktar
    if not os.path.exists(PROCESSED_ORDERS_PATH):
        raise FileNotFoundError(f"Missing mandatory order data: {PROCESSED_ORDERS_PATH}")
    orders_df = pd.read_csv(PROCESSED_ORDERS_PATH)
    orders_df.to_sql("orders", conn, index=False, if_exists="replace")

    # Yeni çalıştırmayı audit tablosuna kaydet
    run_id = str(uuid.uuid4())[:8]
    cursor.execute(
        "INSERT INTO pipeline_runs (run_id, timestamp, trigger_source, orders_count, status) VALUES (?, ?, ?, ?, ?)",
        (run_id, datetime.now().isoformat(), "pipeline_execution", len(orders_df), "INITIALIZED")
    )
    conn.commit()

    # 2. Sentetik fabrika ana veri tablolarını oku ve fail-fast doğrula
    synthetic_tables = [
        "machines",
        "products",
        "materials",
        "bom",
        "routing",
        "changeover_matrix",
    ]

    loaded_data = {}
    for table in synthetic_tables:
        csv_file = SYNTHETIC_DATA_DIR / f"{table}.csv"
        if not os.path.exists(csv_file):
            raise FileNotFoundError(f"Missing mandatory master data: {table}.csv")
        loaded_data[table] = pd.read_csv(csv_file)

    # Master-data bütünlük denetimi (Fail-Fast)
    validate_master_data(loaded_data)

    for table, tdf in loaded_data.items():
        tdf.to_sql(table, conn, index=False, if_exists="replace")

    conn.commit()

    # 3. EDA Özet Tablosu
    eda_summary = analyze_demand_characteristics(orders_df)

    print("=" * 75)
    print("           FABRİKA VERİTABANI & TALEP EDA RAPORU           ")
    print("=" * 75)
    print(eda_summary.to_string(index=False))
    print("-" * 75)

    # 4. Veritabanı Doğrulama
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    print("SQLITE VERİTABANI DOĞRULAMASI:")
    print(f"Konum: {DB_PATH}")
    print(f"Yüklenen Tablolar ({len(tables)} adet): {', '.join(tables)}")

    for t in tables:
        count = cursor.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  - {t:<20}: {count:>6} satır")

    conn.close()
    print("Not: Master data iktisadi öznitelikleri (operating_cost, unit_sale_price vb.)")
    print("     kurumsal şema uyumu ve çok amaçlı genişletmeler için rezerve edilmiştir.")
    print("=" * 75)

if __name__ == "__main__":
    initialize_database()
    