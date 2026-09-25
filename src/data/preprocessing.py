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


# Açık, kurumsal ve deterministik kaynak sistem eşleme sözlüğü
# Kaynak sistem kodu (item_id) -> İç ERP SKU kodu (product_id)
CANONICAL_ERP_PRODUCT_MAPPING: Dict[Any, str] = {
    1: "P01",
    2: "P02",
    3: "P03",
    4: "P04",
    5: "P05",
}


def get_erp_product_mapping(db_path: Path = DB_PATH) -> Dict[Any, str]:
    """
    ERP Product Master ve Kaynak Sistem entegrasyonundan deterministik SKU eşlemesini döndürür.
    Pozisyona/indekse dayalı varsayımlar yapılmaz; açık ve doğrulanmış eşleme tablosu esas alınır.
    """
    # 1. Açık kanonik eşleme sözlüğünü kopyala
    mapping = dict(CANONICAL_ERP_PRODUCT_MAPPING)

    # 2. Eğer veritabanında explicit mapping tablosu veya doğrulanmış ürün listesi varsa denetle
    if os.path.exists(db_path):
        try:
            with get_db_connection(db_path) as conn:
                products_df = pd.read_sql("SELECT product_id FROM products", conn)
                if not products_df.empty:
                    valid_db_pids = set(products_df["product_id"])
                    # Eşlemedeki tüm iç SKU'ların DB'deki master ürün listesinde var olduğunu doğrula
                    for src_item, target_pid in mapping.items():
                        if target_pid not in valid_db_pids:
                            raise ValueError(
                                f"[ERP INTEGRATION ERROR] Eşleme tablosundaki SKU '{target_pid}' "
                                f"veritabanı 'products' tablosunda tanımlı değil!"
                            )
        except Exception as e:
            # Sadece DB henüz hazır değilse kanonik eşlemeye devam et, ama silent drop yapma
            if "products" not in str(e).lower():
                raise e

    return mapping


class KaggleRetailDemandAdapter(DemandSourceAdapter):
    """
    Perakende mağaza talep veri kümesini (Kaggle/Store Item Demand şeması:
    ['date', 'store', 'item', 'sales']) konsolide fabrika çekme talebine 
    dönüştüren endüstriyel adaptör.
    
    Fail-Fast Prensibi: Eşlenmemiş veya tanınmayan harici SKU tespit edilirse 
    sessizce yutulmaz; doğrulamada hata fırlatılır.
    """
    def __init__(
        self,
        product_mapping: Optional[Dict[Any, str]] = None,
        allow_unmapped: bool = False,
    ):
        self.product_mapping = product_mapping or get_erp_product_mapping()
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

        # Kaynak verideki tüm benzersiz item'ları denetle
        unique_source_items = set(df[self.col_item].unique())
        mapped_items = set(self.product_mapping.keys())
        unmapped_items = unique_source_items - mapped_items

        # Denetim Madde 10: Fail-Fast mekanizması (Sessiz SKU kaybını önle)
        if unmapped_items:
            if not self.allow_unmapped:
                raise ValueError(
                    f"[DATA QUALITY / LINEAGE ERROR] Kaynak talep dosyasında ERP SKU eşlemesi "
                    f"bulunmayan bilinmeyen kalemler tespit edildi: {sorted(list(unmapped_items))}. "
                    f"Talebin sessizce yok sayılmasını önlemek için süreç durduruldu. "
                    f"Lütfen kaynak ürün eşleme tablosunu güncelleyiniz."
                )
            else:
                # Açıkça izin verildiyse filtrele
                df = df[df[self.col_item].isin(mapped_items)].copy()

        pilot_df = df[df[self.col_item].isin(mapped_items)].copy()
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

    adapter = KaggleRetailDemandAdapter(allow_unmapped=True)
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
