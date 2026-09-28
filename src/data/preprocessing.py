import os
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
from src.config import RAW_DATA_DIR, PROCESSED_DATA_DIR, DB_PATH
from src.utils.db import get_db_connection


class DemandSourceAdapter(ABC):
    """
    Dış sistemlerden (Kaggle CSV, ERP MES, SAP, IFS) gelen sipariş verilerini 
    standart Fabrika Çekme Talebi formatına dönüştüren temel adaptör arayüzü.
    """
    @abstractmethod
    def adapt(self, source_path: Path) -> pd.DataFrame:
        """
        Dönüşüm çıktısı en az şu standart kolonları içermelidir:
        ['order_date', 'product_id', 'order_qty']
        """
        pass


# Statik Fallback Sözlüğü (Geriye dönük uyumluluk ve DB erişimsiz test izolasyonu için)
CANONICAL_ERP_PRODUCT_MAPPING: Dict[Any, str] = {
    1: "P01",
    2: "P02",
    3: "P03",
    4: "P04",
    5: "P05",
}


def get_erp_product_mapping(source_system: str = "KAGGLE", db_path: Optional[str] = None) -> tuple[Dict[Any, str], set]:
    """
    Kurumsal ERP tablosundan:
    - all_mappings: tüm tanınan SKU sözlüğü (item_id -> internal_id)
    - in_scope_ids: sadece üretim kapsamındaki dahili SKU kümesi {'P01'..'P05'}
    döner.
    """
    import src.config as config
    target_db = db_path or os.environ.get("FACTORY_DB_PATH") or getattr(config, "DB_PATH", "data/factory.db")
    
    mapping = {}
    in_scope_ids = set()
    
    if os.path.exists(target_db):
        try:
            conn = sqlite3.connect(target_db)
            cur = conn.cursor()
            cur.execute("""
                SELECT source_product_code, internal_product_id, is_in_scope 
                FROM erp_product_mapping 
                WHERE source_system = ? AND status = 'active'
            """, (source_system,))
            rows = cur.fetchall()
            conn.close()
            for src_code, internal_id, in_scope in rows:
                mapping[src_code] = internal_id
                try:
                    mapping[int(src_code)] = internal_id
                except (ValueError, TypeError):
                    pass
                if in_scope == 1:
                    in_scope_ids.add(internal_id)
            if mapping:
                return mapping, in_scope_ids
        except Exception:
            pass

    # Fallback (Veritabanı yoksa veya test ortamıysa)
    fallback_map = {i: f"P{i:02d}" for i in range(1, 51)}
    fallback_scope = {f"P{i:02d}" for i in range(1, 6)}
    return fallback_map, fallback_scope

class KaggleRetailDemandAdapter(DemandSourceAdapter):
    """
    Kurumsal 3-Seviyeli SKU Scope Yönetimi:
    1. Mapped & In-Scope -> Üretim planına dahil edilir.
    2. Mapped but Out-of-Scope -> Bilinçli olarak filtrelenir ve loglanır.
    3. Unmapped -> Kesinlikle sessizce filtrelenmez; anında FAIL-FAST fırlatılır.
    """
    def __init__(
        self,
        product_mapping: Optional[Dict[Any, str]] = None,
        in_scope_products: Optional[set] = None,
        allow_unmapped: bool = False,
    ):
        mapped_dict, scope_set = get_erp_product_mapping()
        self.product_mapping = product_mapping if product_mapping is not None else mapped_dict
        self.in_scope_products = in_scope_products if in_scope_products is not None else scope_set
        self.allow_unmapped = allow_unmapped
        self.col_date = "date"
        self.col_item = "item"
        self.col_store = "store"
        self.col_sales = "sales"

    def adapt(self, source_path: Path) -> pd.DataFrame:
        df = pd.read_csv(source_path)

        required_cols = {self.col_date, self.col_item, self.col_sales}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Kaynak şema geçersiz. Gerekli kolonlar eksik: {required_cols - set(df.columns)}")

        unique_source_items = set(df[self.col_item].unique())
        mapped_items = set(self.product_mapping.keys())
        unmapped_items = unique_source_items - mapped_items

        # Kural 3: Tanınmayan SKU varsa FAIL-FAST (Sessiz filtreleme YASAKTIR)
        if unmapped_items and not self.allow_unmapped:
            raise ValueError(
                f"[DATA GOVERNANCE FAIL] ERP kataloğunda eşlemesi bulunmayan yabancı kalemler: {sorted(list(unmapped_items))}. "
                f"Sessiz veri kaybını önlemek için pipeline durduruldu."
            )

        # Dahili ERP koduna dönüştür
        df["product_id"] = df[self.col_item].map(self.product_mapping)

        # Kural 1 & 2: Mapped but Out-of-Scope ayrımı (Intentional Scope Exclusion)
        in_scope_mask = df["product_id"].isin(self.in_scope_products)
        out_of_scope_count = (~in_scope_mask).sum()
        if out_of_scope_count > 0:
            out_skus = set(df.loc[~in_scope_mask, "product_id"].unique())
            # Kasıtlı filtreleme loglanır
            # print(f"[INFO] Intentional Scope Exclusion: {len(out_skus)} SKU ({out_of_scope_count} satır) pilot kapsamı dışında bırakıldı: {sorted(list(out_skus))}")

        df_in_scope = df[in_scope_mask].copy()

        df_in_scope[self.col_date] = pd.to_datetime(df_in_scope[self.col_date])
        daily_factory_demand = (
            df_in_scope.groupby([self.col_date, "product_id"])[self.col_sales]
            .sum()
            .reset_index()
        )
        daily_factory_demand.rename(
            columns={self.col_date: "date", self.col_sales: "demand"}, inplace=True
        )

        return daily_factory_demand


def run_preprocessing():
    """
    Veri Ön İşleme Aşaması (Core Business Logic):
    Adaptör aracılığıyla standartlaştırılan sipariş verisine takvim öznitelikleri
    ekler ve üretim veritabanı için hazır hale getirir.
    """
    raw_path = RAW_DATA_DIR / "train.csv"
    fixture_name = os.environ.get("USE_FIXTURE", "demand_fixture.csv")
    if not fixture_name.endswith(".csv"):
        fixture_name = "demand_fixture.csv"
    fixture_path = RAW_DATA_DIR.parent / "fixtures" / fixture_name
    output_path = PROCESSED_DATA_DIR / "factory_orders.csv"

    # Veri kaynağı seçimi (Fail-Fast prensibiyle CI izolasyonu)
    if "USE_FIXTURE" in os.environ:
        if not os.path.exists(fixture_path):
            raise FileNotFoundError(
                f"[CRITICAL CI FAIL-FAST] USE_FIXTURE='{os.environ.get('USE_FIXTURE')}' olarak belirtildi "
                f"ancak fixture dosyası bulunamadı: {fixture_path}. Ham veriye geri düşüş engellendi!"
            )
        data_source = fixture_path
        print(f"[1/3] CI test senaryo fixture kullanılıyor ({fixture_path})...")
    elif os.path.exists(raw_path):
        data_source = raw_path
        print(f"[1/3] Ham veri seti okunuyor ({raw_path})...")
    elif os.path.exists(fixture_path):
        data_source = fixture_path
        print(f"[1/3] Ham veri bulunamadı, varsayılan test fixture kullanılıyor ({fixture_path})...")
    else:
        raise FileNotFoundError(
            f"Ne ham veri ({raw_path}) ne de varsayılan test fixture ({fixture_path}) bulunabildi!"
        )

    # Madde 15: Production path fail-fast güvencesi (Bilinmeyen SKU geldiğinde sessiz filtreleme engellenir)
    # CI/Test ortamında esneklik istenirse ALLOW_UNMAPPED çevre değişkeniyle açılabilir, varsayılan False'tur.
    allow_unmapped_env = os.environ.get("ALLOW_UNMAPPED", "False").lower() in ("true", "1", "yes")
    adapter = KaggleRetailDemandAdapter()
    factory_demand = adapter.adapt(data_source)

    # 1. Tarih kolonunu order_date olarak standartlaştır
    date_col = "order_date" if "order_date" in factory_demand.columns else "date"
    factory_demand["order_date"] = pd.to_datetime(factory_demand[date_col])
    if "date" in factory_demand.columns:
        factory_demand.drop(columns=["date"], inplace=True)

    # 2. Miktar kolonunu order_qty olarak standartlaştır
    qty_col = "order_qty" if "order_qty" in factory_demand.columns else ("demand" if "demand" in factory_demand.columns else "sales")
    factory_demand["order_qty"] = factory_demand[qty_col].astype(int)
    if qty_col != "order_qty" and qty_col in factory_demand.columns:
        factory_demand.drop(columns=[qty_col], inplace=True)

    # 3. Zaman özniteliklerini ekle
    factory_demand["year"] = factory_demand["order_date"].dt.year
    factory_demand["month"] = factory_demand["order_date"].dt.month
    factory_demand["day_of_week"] = factory_demand["order_date"].dt.dayofweek
    factory_demand["is_weekend"] = factory_demand["day_of_week"].isin([5, 6]).astype(int)

    # 4. Tarihi string (YYYY-MM-DD) formatına çevir (SQLite için)
    factory_demand["order_date"] = factory_demand["order_date"].dt.strftime("%Y-%m-%d")

    # 5. Kolon sıralamasını orders tablosu şemasıyla birebir eşle
    expected_cols = ["order_date", "product_id", "order_qty", "year", "month", "day_of_week", "is_weekend"]
    factory_demand = factory_demand[expected_cols]

    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    factory_demand.to_csv(output_path, index=False)

    print(f"[3/3] Konsolide fabrika talebi kaydedildi -> {output_path}")
    print("=" * 65)
    print(f"Toplam Günlük Fabrika Talep Kaydı : {len(factory_demand):,} gün/ürün")
    print(f"Tarih Aralığı                     : {factory_demand['order_date'].min()} -> {factory_demand['order_date'].max()}")
    print("=" * 65)
