"""
ERP Mapping Service: Harici ERP (SAP/IFS) sistemleri ile dahili fabrika modelleri
arasında çift yönlü kimlik çözümleme ve eşleme sağlar.
"""

from typing import Optional, Dict, Any
import pandas as pd
from src.utils.db import get_db_connection
from src.config import DB_PATH


class ERPService:
    @classmethod
    def get_erp_code(cls, entity_type: str, internal_id: str, erp_system: str = "SAP_S4HANA") -> Optional[str]:
        """Dahili ID'den ERP kodunu döner (örn: P01 -> MAT-10001)."""
        conn = get_db_connection(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT erp_code FROM erp_mapping 
            WHERE entity_type = ? AND internal_id = ? AND erp_system = ? AND is_active = 1
        """, (entity_type, internal_id, erp_system))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    @classmethod
    def get_internal_id(cls, entity_type: str, erp_code: str, erp_system: str = "SAP_S4HANA") -> Optional[str]:
        """ERP kodundan dahili ID'yi döner (örn: MAT-10001 -> P01)."""
        conn = get_db_connection(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT internal_id FROM erp_mapping 
            WHERE entity_type = ? AND erp_code = ? AND erp_system = ? AND is_active = 1
        """, (entity_type, erp_code, erp_system))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    @classmethod
    def get_mapping_table(cls, entity_type: Optional[str] = None) -> pd.DataFrame:
        """Tüm aktif eşlemeleri DataFrame olarak döner."""
        conn = get_db_connection(DB_PATH)
        if entity_type:
            df = pd.read_sql(
                "SELECT * FROM erp_mapping WHERE entity_type = ? AND is_active = 1",
                conn,
                params=(entity_type,),
            )
        else:
            df = pd.read_sql("SELECT * FROM erp_mapping WHERE is_active = 1", conn)
        conn.close()
        return df