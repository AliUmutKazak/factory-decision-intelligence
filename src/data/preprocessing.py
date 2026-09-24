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


def get_erp_product_mapping(db_path: Path = DB_PATH) -> Dict[Any, str]:
    """
    ERP Product Master tablosundan ürün listesini dinamik olarak sorgular.
    Eğer veritabanı veya eşleme tablosu henüz ilklendirilmemişse
    standart pilot SKU master eşlemesine geri döner.
    """
    fallback_mapping = {1: "P01", 2: "P02", 3: "P03", 4: "P04", 5: "P05"}
    
    if not os.path.exists(db_path):
        return fallback_mapping

    try:
        with get_db_connection(db_path) as conn:
            products_df = pd.read_sql("SELECT product_id FROM products ORDER BY product_id", conn)
            if not products_df.empty:
                return {idx + 1: pid for idx, pid in enumerate(products_df["product_id"].tolist())}
    except Exception:
        pass

    return fallback_mapping


class KaggleRetailDemandAdapter(DemandSourceAdapter):
    """
    Perakende mağaza talep veri kümesini (Kaggle/Store Item Demand şeması:
    ['date', 'store', 'item', 'sales']) konsolide fabrika çekme talebine 
    dönüştüren prototip adaptör.
    """
    def __init__(self, product_mapping: Optional[Dict[Any, str]] = None):
        self.product_mapping = product_mapping or get_erp_product_mapping()
        self.col_date = "date"
        self.col_item = "item"
        self.col_store = "store"
        self.col_sales = "sales"

    def adapt(self, source_path: Path) -> pd.DataFrame:
        df = pd.read_csv(source_path)

        required_cols = {self.col_date, self.col_item, self.col_sales}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Kaynak şema geçersiz. Gerekli kolonlar eksik: {required_cols - set(df.columns)}")

        pilot_df = df[df[self.col_item].isin(self.product_mapping.keys())].copy()
        pilot_df["product_id"] = pilot_df[self.col_item].map(self.product_mapping)
        pilot_df["order_date"] = pd.to_datetime(pilot_df[self.col_date])

        n_stores = pilot_df[self.col_store].nunique() if self.col_store in pilot_df.columns else 1
        print(f"[2/3] {n_stores} mağaza talebi tek fabrika çekme talebine konsolide ediliyor...")

        factory_demand = (
            pilot_df.groupby(["order_date", "product_id"])[self.col_sales]
            .sum()
            .reset_index()
            .rename(columns={self.col_sales: "order_qty"})
        )
        return factory_demand


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

    if "USE_FIXTURE" in os.environ and os.path.exists(fixture_path):
        data_source = fixture_path
        print(f"[1/3] CI test senaryo fixture kullanılıyor ({fixture_path})...")
    elif os.path.exists(raw_path):
        data_source = raw_path
        print(f"[1/3] Ham veri seti okunuyor ({raw_path})...")
    elif os.path.exists(fixture_path):
        data_source = fixture_path
        print(f"[1/3] Ham veri bulunamadı, CI test fixture kullanılıyor ({fixture_path})...")
    else:
        raise FileNotFoundError(
            f"Ne ham veri ({raw_path}) ne de test fixture ({fixture_path}) bulunabildi!"
        )

    adapter = KaggleRetailDemandAdapter()
    factory_demand = adapter.adapt(data_source)

    factory_demand["year"] = factory_demand["order_date"].dt.year
    factory_demand["month"] = factory_demand["order_date"].dt.month
    factory_demand["day_of_week"] = factory_demand["order_date"].dt.dayofweek
    factory_demand["is_weekend"] = factory_demand["day_of_week"].isin([5, 6]).astype(int)

    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    factory_demand.to_csv(output_path, index=False)

    print(f"[3/3] Konsolide fabrika talebi kaydedildi -> {output_path}")
    print("=" * 65)
    print(f"Toplam Günlük Fabrika Talep Kaydı : {len(factory_demand):,} gün/ürün")
    print(f"Tarih Aralığı                     : {factory_demand['order_date'].min().date()} -> {factory_demand['order_date'].max().date()}")
    print("=" * 65)
    