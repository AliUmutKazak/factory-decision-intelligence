import sqlite3

import pytest

from src.config import DB_PATH
from src.utils.lineage import generate_run_id, record_input_source_lineage


def test_input_source_lineage_recording():
    """Girdi veri setlerinin veritabanına SHA-256 ile kaydedildiğini doğrular."""
    test_run_id = f"test_lineage_{generate_run_id()}"

    count = record_input_source_lineage(test_run_id, db_path=DB_PATH)
    assert count > 0

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT source_name, sha256, source_type FROM input_source_lineage WHERE run_id = ?", (test_run_id,))
    rows = cursor.fetchall()

    # Temizlik
    cursor.execute("DELETE FROM input_source_lineage WHERE run_id = ?", (test_run_id,))
    conn.commit()
    conn.close()

    assert len(rows) == count
    for name, sha, s_type in rows:
        assert sha is not None
        assert len(sha) == 64  # Geçerli SHA-256 uzunluğu
