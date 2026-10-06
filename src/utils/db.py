"""Shared SQLite runtime utilities and run-scope safeguards."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from src.config import DB_PATH

_SQLITE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def resolve_db_path(db_path: str | os.PathLike | None = None) -> Path:
    """Resolve an explicit DB path or the current runtime DB path."""
    env_db = os.environ.get("FACTORY_DB_PATH")
    if db_path is None:
        return Path(env_db if env_db else DB_PATH)

    requested = Path(db_path)
    canonical = Path(DB_PATH)
    if env_db and requested.resolve() == canonical.resolve():
        return Path(env_db)
    return requested


def get_db_connection(db_path=None):
    """Open a SQLite connection with foreign-key enforcement enabled."""
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_active_run_id(conn: sqlite3.Connection) -> str:
    """Return the sole ACTIVE pipeline run; fail fast when none exists."""
    row = conn.execute(
        "SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("[RUN GOVERNANCE] ACTIVE run bulunamadı.")
    return str(row[0])


def persist_run_scoped_dataframe(
    conn: sqlite3.Connection,
    table_name: str,
    df,
    run_id: str,
) -> None:
    """Persist exactly one run version without destroying historical runs.

    The first write is allowed to create the table. Subsequent writes replace
    only rows for the requested run_id, never rows belonging to other runs.
    """
    if not run_id:
        raise ValueError(f"[RUN GOVERNANCE] {table_name}: run_id zorunludur.")
    if df is None:
        raise ValueError(f"[RUN GOVERNANCE] {table_name}: DataFrame None olamaz.")
    if not _SQLITE_IDENTIFIER.fullmatch(str(table_name)):
        raise ValueError(f"[RUN GOVERNANCE] Geçersiz tablo adı: {table_name!r}")
    if "run_id" not in df.columns:
        raise ValueError(f"[RUN GOVERNANCE] {table_name}: run_id kolonu zorunludur.")

    scoped = df.copy()
    scoped["run_id"] = scoped["run_id"].astype(str)
    if not (scoped["run_id"] == str(run_id)).all():
        raise ValueError(f"[RUN GOVERNANCE] {table_name}: DataFrame birden fazla run_id içeriyor.")

    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()

    if not table_exists:
        scoped.to_sql(table_name, conn, index=False, if_exists="append")
        return

    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if "run_id" not in columns:
        raise ValueError(
            f"[RUN GOVERNANCE] {table_name}: mevcut tablo run_id kolonu taşımıyor; migration gerekli."
        )

    conn.execute("SAVEPOINT persist_run_scope")
    try:
        conn.execute(f"DELETE FROM {table_name} WHERE run_id = ?", (str(run_id),))
        scoped.to_sql(table_name, conn, index=False, if_exists="append")
        conn.execute("RELEASE SAVEPOINT persist_run_scope")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT persist_run_scope")
        conn.execute("RELEASE SAVEPOINT persist_run_scope")
        raise


def table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return column_name in {row[1] for row in rows}
