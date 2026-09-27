import sqlite3
import os
from pathlib import Path
from src.config import DB_PATH

def get_db_connection(db_path=None):
    """
    Tüm pipeline ve testler için merkezi SQLite bağlantı sağlayıcısı.
    Eğer çalışma zamanında FACTORY_DB_PATH (staging izolasyonu) tanımlanmışsa
    ve çağrı varsayılan DB_PATH üzerinden yapılıyorsa, bağlantıyı dinamik olarak
    staging veritabanına yönlendirir (Split-Brain koruması).
    """
    env_db = os.environ.get("FACTORY_DB_PATH")
    if db_path is None:
        path = env_db if env_db else DB_PATH
    else:
        # Alt modüller import anındaki sabit DB_PATH'i gönderse bile
        # aktif bir staging (FACTORY_DB_PATH) varsa oraya yönlendir:
        if env_db and Path(db_path).resolve() == Path(DB_PATH).resolve():
            path = env_db
        else:
            path = db_path

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn