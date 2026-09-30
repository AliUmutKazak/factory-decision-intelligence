import os

import numpy as np
import pandas as pd

from src.config import (
    DB_PATH,
    PROCESSED_DATA_DIR,
    SYNTHETIC_DATA_DIR,
)
from src.utils.db import get_db_connection

PROCESSED_ORDERS_PATH = PROCESSED_DATA_DIR / "factory_orders.csv"


def analyze_demand_characteristics(orders_df: pd.DataFrame) -> pd.DataFrame:
    daily_product_demand = orders_df.groupby(["order_date", "product_id"])["order_qty"].sum().reset_index()

    stats = (
        daily_product_demand.groupby("product_id")["order_qty"]
        .agg(gunluk_ortalama="mean", gunluk_std="std", min_talep="min", max_talep="max", toplam_talep="sum")
        .reset_index()
    )

    # Varyasyon Katsayısı (CV = sigma / mu)
    stats["cv_volatilite"] = (stats["gunluk_std"] / stats["gunluk_ortalama"]).round(3)
    stats["talep_profili"] = np.where(stats["cv_volatilite"] < 0.5, "Düzenli (Smooth)", "Dalgalı (Erratic)")

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
        "changeover_matrix": ["from_product", "to_product", "setup_time_min"],
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
            raise ValueError(
                f"[MASTER DATA ERROR] '{tbl_name}' tablosunda boş (null) değer tespit edildi:\n{null_counts[null_counts > 0]}"
            )

    # 3. Sayısal Alanlarda Negatif Değer Kontrolü
    num_checks = [
        ("machines", ["base_power_kw", "operating_cost_per_hour", "max_daily_hours"]),
        ("bom", ["qty_per_unit"]),
        ("routing", ["processing_time_min"]),
        ("changeover_matrix", ["setup_time_min"]),
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
        raise ValueError(
            f"[MASTER DATA ERROR] 'routing' içinde tanımsız product_id: {routing_products - valid_products}"
        )
    if not routing_machines.issubset(valid_machines):
        raise ValueError(
            f"[MASTER DATA ERROR] 'routing' içinde tanımsız machine_id: {routing_machines - valid_machines}"
        )

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
        raise ValueError(
            f"[MASTER DATA ERROR] 'routing' içinde tanımsız product_id: {routing_products - valid_products}"
        )
    if not routing_machines.issubset(valid_machines):
        raise ValueError(
            f"[MASTER DATA ERROR] 'routing' içinde tanımsız machine_id: {routing_machines - valid_machines}"
        )

    # 6. Kapsama Doğrulamaları (Coverage & Completeness)
    missing_bom = valid_products - bom_products
    if missing_bom:
        raise ValueError(f"[MASTER DATA ERROR] Şu ürünler için BOM tanımı bulunamadı: {missing_bom}")

    missing_routing = valid_products - routing_products
    if missing_routing:
        raise ValueError(f"[MASTER DATA ERROR] Şu ürünler için Rota (Routing) tanımı bulunamadı: {missing_routing}")

    # Changeover matrix completeness
    co_df = data_dict["changeover_matrix"]
    existing_pairs = set(zip(co_df["from_product"], co_df["to_product"]))
    all_pairs = {(p1, p2) for p1 in valid_products for p2 in valid_products}
    missing_pairs = all_pairs - existing_pairs
    if missing_pairs:
        raise ValueError(f"[MASTER DATA ERROR] 'changeover_matrix' eksik ürün geçişleri içeriyor: {missing_pairs}")


def initialize_database(force_recreate=False, run_id=None):
    """
    Veritabanını SSOT (Single Source of Truth) ilkelerine uygun şekilde başlatır ve eşitler.
    Dosyayı tamamen silmek yerine idempotent tablo senkronizasyonu yapar ve
    her icra için 'pipeline_runs' denetim kaydı oluşturur.
    """
    import gc
    from datetime import datetime

    gc.collect()

    if force_recreate and os.path.exists(DB_PATH):
        conn_temp = get_db_connection(DB_PATH)
        cur = conn_temp.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        # pipeline_runs hariç diğer tabloları temizle (denetim hafızasını koru)
        cur.execute(
            "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'view') "
            "AND name NOT LIKE 'sqlite_%' AND name != 'pipeline_runs';"
        )
        objects_to_drop = cur.fetchall()
        for obj_type, obj_name in objects_to_drop:
            cur.execute(f'DROP {obj_type.upper()} IF EXISTS "{obj_name}";')
        conn_temp.commit()
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("VACUUM;")
        conn_temp.close()

    conn = get_db_connection(DB_PATH)
    cursor = conn.cursor()
    # P0 Çözümü: Downstream tablolar pipeline başlangıcında DROP EDİLMEZ.
    # Önceki başarılı koşumun (RUN_ACTIVE) fiziksel verisi korunur.
    # Yeni koşum tamamlanıp doğrulanana kadar eski canlı veri lekelenmez.

    # 0. SSOT Merkezi Denetim Şeması (pipeline_runs)
    from src.config import CONFIG_PATH
    from src.utils.lineage import (
        compute_file_hash,
        generate_run_id,
        get_git_sha,
        init_pipeline_runs_table,
    )

    init_pipeline_runs_table(conn)

    # 1. İşlenmiş sipariş verisini aktar
    try:
        orders_df = pd.read_csv(PROCESSED_ORDERS_PATH)
        if orders_df.empty:
            raise pd.errors.EmptyDataError("Dosya bos")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        from src.data.preprocessing import run_preprocessing

        run_preprocessing()
        orders_df = pd.read_csv(PROCESSED_ORDERS_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_date TEXT NOT NULL,
            product_id TEXT NOT NULL,
            order_qty INTEGER NOT NULL,
            year INTEGER,
            month INTEGER,
            day_of_week INTEGER,
            is_weekend INTEGER
        );
    """)
    cursor.execute("DELETE FROM orders;")
    conn.commit()

    # -------------------------------------------------------------
    # ERP / MES ENTEGRASYON VE YÜRÜTME TABLOLARI
    # -------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mes_execution_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            task_id INTEGER,
            machine_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_timestamp_min REAL NOT NULL,
            actual_duration_min REAL,
            delay_reason TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
        );
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mes_order_tracking (
            task_id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL,
            lot_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            scheduled_start_min REAL NOT NULL,
            scheduled_end_min REAL NOT NULL,
            actual_start_min REAL,
            actual_end_min REAL,
            status TEXT DEFAULT 'SCHEDULED',
            variance_min REAL DEFAULT 0.0,
            last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
        );
        """)
    conn.commit()

    orders_df.to_sql("orders", conn, index=False, if_exists="append")

    # 2. Tek ve Standart Run ID Kaydı (INITIALIZED)
    if not run_id:
        run_id = generate_run_id()

    git_sha = get_git_sha()
    cfg_hash = compute_file_hash(CONFIG_PATH)

    cursor.execute(
        """
        INSERT OR REPLACE INTO pipeline_runs
        (run_id, timestamp, trigger_source, orders_count, git_sha, config_hash, data_source, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            run_id,
            datetime.now().isoformat(),
            "pipeline_execution",
            len(orders_df),
            git_sha,
            cfg_hash,
            "factory_orders.csv",
            "INITIALIZED",
        ),
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
        if table == "changeover_matrix":
            if "machine_id" not in loaded_data[table].columns:
                loaded_data[table]["machine_id"] = "ALL"
            else:
                loaded_data[table]["machine_id"] = loaded_data[table]["machine_id"].fillna("ALL")

    # Master data tablolarını açık kısıtlarla oluştur
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS machines (
            machine_id TEXT PRIMARY KEY,
            machine_name TEXT NOT NULL,
            base_power_kw REAL,
            operating_cost_per_hour REAL,
            max_daily_hours REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            unit_sale_price REAL,
            holding_cost_per_week REAL,
            late_penalty_per_day REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            material_id TEXT PRIMARY KEY,
            material_name TEXT NOT NULL,
            unit TEXT,
            unit_cost REAL,
            supplier_id TEXT,
            lead_time_days REAL,
            min_order_qty REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bom (
            product_id TEXT NOT NULL,
            material_id TEXT NOT NULL,
            qty_per_unit REAL NOT NULL,
            PRIMARY KEY (product_id, material_id),
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            FOREIGN KEY (material_id) REFERENCES materials(material_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS routing (
            product_id TEXT NOT NULL,
            operation_seq INTEGER NOT NULL,
            machine_id TEXT NOT NULL,
            processing_time_min REAL NOT NULL,
            variable_kwh_per_unit REAL,
            PRIMARY KEY (product_id, operation_seq),
            FOREIGN KEY (product_id) REFERENCES products(product_id),
            FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
        )
    """)

    # P0 Şema Çözümü: SQLite composite PK içinde NULL uniqueness zafiyetini önleme.
    # Genel (global) hazırlık kuralları için machine_id = 'ALL' kullanılır, NULL kesinlikle yasaktır.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS changeover_matrix (
            machine_id TEXT NOT NULL DEFAULT 'ALL',
            from_product TEXT NOT NULL,
            to_product TEXT NOT NULL,
            setup_time_min REAL NOT NULL,
            setup_cost REAL,
            PRIMARY KEY (machine_id, from_product, to_product),
            FOREIGN KEY (from_product) REFERENCES products(product_id),
            FOREIGN KEY (to_product) REFERENCES products(product_id)
        )
    """)

    # Denetim Madde 21: Runtime Snapshot / MES Tezgâh Başlangıç Durumu Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS machine_state (
            machine_id TEXT PRIMARY KEY,
            last_product_id TEXT NOT NULL,
            state_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (machine_id) REFERENCES machines(machine_id),
            FOREIGN KEY (last_product_id) REFERENCES products(product_id)
        )
    """)
    # Denetim Madde 30: Machine State Run-Scoped Snapshot Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS machine_state_snapshot (
            run_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            last_product_id TEXT NOT NULL,
            state_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            source_system TEXT DEFAULT 'MES_DATABASE',
            PRIMARY KEY (run_id, machine_id),
            FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
        )
    """)
    # Denetim Madde 31: Machine Calendar (Vardiya, Bakım ve Duruş Takvimi)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS machine_calendar (
            calendar_id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT NOT NULL,
            day_of_week INTEGER NOT NULL,
            shift_id TEXT DEFAULT 'SHIFT_REGULAR',
            start_minute INTEGER DEFAULT 480,
            end_minute INTEGER DEFAULT 1440,
            available_hours REAL DEFAULT 16.0,
            exception_type TEXT DEFAULT 'REGULAR',
            is_available INTEGER DEFAULT 1,
            FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
        )
    """)
    conn.commit()

    # P1-1: ERP Mapping Table (External System Reconciliation)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS erp_mapping (
            mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,          -- 'SKU', 'MACHINE', 'RAW_MATERIAL'
            internal_id TEXT NOT NULL,          -- 'P01', 'M01', 'RM_STEEL_01'
            erp_system TEXT NOT NULL,           -- 'SAP_S4HANA', 'IFS_APPS'
            erp_code TEXT NOT NULL,             -- 'MAT-100234', 'WC-CNC-01'
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_type, erp_system, erp_code),
            UNIQUE(entity_type, erp_system, internal_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_erp_mapping_lookup ON erp_mapping(entity_type, internal_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_erp_mapping_reverse ON erp_mapping(erp_system, erp_code)")

    # Master-data bütünlük denetimi (Fail-Fast)
    validate_master_data(loaded_data)
    # Veritabanını temizlerken ve master datayı yeniden yüklerken foreign key kontrollerini
    # geçici olarak durduruyoruz; yükleme tamamlandığında tekrar aktif hale getiriyoruz.
    cursor.execute("PRAGMA foreign_keys = OFF;")
    for table, tdf in loaded_data.items():
        cursor.execute(f"DELETE FROM {table}")
        tdf.to_sql(table, conn, index=False, if_exists="append")

    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON;")

    # -------------------------------------------------------------------------
    # P0 Çözümü: MES Runtime Snapshot Bütünlüğü
    # Eğer tabloda sahadan/önceki koşumdan gelen tezgâh durumları varsa EZİLMEZ (overwrite edilmez).
    # Sadece tablo tamamen boşsa (Cold-Start / Initial Setup) varsayılan değerlerle tohumlanır.
    # -------------------------------------------------------------------------
    cursor.execute("SELECT COUNT(*) FROM machine_state")
    existing_state_count = cursor.fetchone()[0]

    if existing_state_count == 0 or force_recreate:
        initial_states = [
            ("M01", "P01"),
            ("M02", "P02"),
            ("M03", "P04"),
        ]
        cursor.executemany(
            """
            INSERT OR REPLACE INTO machine_state (machine_id, last_product_id)
            VALUES (?, ?)
        """,
            initial_states,
        )
        conn.commit()

    # -------------------------------------------------------------------------
    # P1-1: ERP Mapping Seed Data (Cold-Start & External Reconciliation)
    # -------------------------------------------------------------------------
    cursor.execute("SELECT COUNT(*) FROM erp_mapping")
    existing_erp_count = cursor.fetchone()[0]

    if existing_erp_count == 0 or force_recreate:
        erp_seed_data = [
            # Ürünler (SKU)
            ('SKU', 'P01', 'SAP_S4HANA', 'MAT-10001', 'Endüstriyel Vana Gövdesi DN50'),
            ('SKU', 'P02', 'SAP_S4HANA', 'MAT-10002', 'Flanş Bağlantı Parçası F10'),
            ('SKU', 'P03', 'SAP_S4HANA', 'MAT-10003', 'Hidrolik Silindir Mili 25mm'),
            ('SKU', 'P04', 'SAP_S4HANA', 'MAT-10004', 'Pnömatik Dağıtıcı Blok'),
            ('SKU', 'P05', 'SAP_S4HANA', 'MAT-10005', 'Hassas Dişli Çark Modül 2'),
            # Makineler (Work Centers)
            ('MACHINE', 'M01', 'SAP_S4HANA', 'WC-CNC-5AX', '5 Eksen CNC İşleme Merkezi'),
            ('MACHINE', 'M02', 'SAP_S4HANA', 'WC-LATHE-01', 'CNC Torna Tezgahı'),
            ('MACHINE', 'M03', 'SAP_S4HANA', 'WC-MILL-02', 'Dikey İşleme Merkezi'),
            ('MACHINE', 'M04', 'SAP_S4HANA', 'WC-GRIND-01', 'Silindirik Taşlama'),
            # Hammaddeler (Raw Materials)
            ('RAW_MATERIAL', 'RM_STEEL_01', 'SAP_S4HANA', 'RAW-ST52-01', 'Çelik Çubuk ST-52'),
            ('RAW_MATERIAL', 'RM_ALUM_02', 'SAP_S4HANA', 'RAW-AL6061', 'Alüminyum Kütük 6061'),
            ('RAW_MATERIAL', 'RM_BRASS_01', 'SAP_S4HANA', 'RAW-MS58', 'Pirinç Profil MS-58')
        ]
        cursor.executemany("""
            INSERT OR REPLACE INTO erp_mapping (entity_type, internal_id, erp_system, erp_code, description)
            VALUES (?, ?, ?, ?, ?)
        """, erp_seed_data)
        conn.commit()    

    # P1-2: Input Source Lineage Tablosu (Audit & Provenance)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS input_source_lineage (
            lineage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL,          -- 'RAW_FILE', 'FIXTURE', 'MASTER_DATA'
            source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            row_count INTEGER,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id, source_name)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_input_lineage_run ON input_source_lineage(run_id)")

    # P2-2: MES Production Actuals & Execution Tracking (Closed-Loop Replanning)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mes_production_actuals (
            actual_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            task_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            planned_start_hour REAL,
            planned_end_hour REAL,
            actual_start_hour REAL NOT NULL,
            actual_end_hour REAL NOT NULL,
            actual_units INTEGER NOT NULL,
            scrap_units INTEGER DEFAULT 0,
            downtime_hours REAL DEFAULT 0.0,
            status TEXT DEFAULT 'COMPLETED',
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mes_actuals_run ON mes_production_actuals(run_id)")
    conn.commit()

    # Madde 31: machine_calendar tablosu boşsa machines verisinden tohumla
    cursor.execute("SELECT COUNT(*) FROM machine_calendar")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO machine_calendar (machine_id, day_of_week, shift_id, start_minute, end_minute, available_hours, exception_type, is_available)
            SELECT machine_id, d.day_idx, 'SHIFT_REGULAR', 480, 480 + CAST(max_daily_hours * 60 AS INTEGER), max_daily_hours, 'REGULAR', 1
            FROM machines
            CROSS JOIN (
                SELECT 0 AS day_idx UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3
                UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6
            ) d
        """)
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
