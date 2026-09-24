import sqlite3
import os
from src.config import DB_PATH

def get_db_connection(db_path=None):
    """
    Tüm pipeline ve testler için merkezi SQLite bağlantı sağlayıcısı.
    Her bağlantıda 'PRAGMA foreign_keys = ON;' çalıştırılarak
    ilişkisel bütünlük kısıtları garanti altına alınır.
    """
    path = db_path if db_path is not None else DB_PATH
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn