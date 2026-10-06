"""Shared SQLite runtime utilities and run-scope safeguards."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import pandas as pd

from src.config import DB_PATH, get_runtime_paths

_SQLITE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def resolve_db_path(db_path: str | os.PathLike | None = None) -> Path:
    """Resolve an explicit DB path or the current runtime DB path."""
    runtime = get_runtime_paths()
    runtime_db = Path(runtime["db_path"])
    default_db = Path(runtime["base_dir"]) / "data" / "factory.db"
    env_db = str(runtime_db) if os.environ.get("FACTORY_DB_PATH") or runtime_db != default_db else None
    if db_path is None:
        return runtime_db

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
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_runs'").fetchone():
        raise RuntimeError("[RUN GOVERNANCE] ACTIVE run bulunamadı: pipeline_runs tablosu yok.")
    rows = conn.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' LIMIT 2").fetchall()
    if not rows or not rows[0][0]:
        raise RuntimeError("[RUN GOVERNANCE] ACTIVE run bulunamadı.")
    if len(rows) != 1:
        raise RuntimeError("[RUN GOVERNANCE] Multiple ACTIVE runs; refusing to select a version.")
    return str(rows[0][0])


def clone_run_inputs(conn, source_run_id: str, target_run_id: str, tables=None) -> None:
    """Explicitly copy one run's inputs into a new isolated version."""
    if source_run_id == target_run_id:
        raise ValueError("Source and target run IDs must differ.")
    has_registry = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_runs'").fetchone()
    if has_registry:
        conn.execute(
            "INSERT INTO pipeline_runs (run_id, timestamp, trigger_source, orders_count, git_sha, config_hash, data_source, status) "
            "SELECT ?, datetime('now'), 'INPUT_CLONE', orders_count, git_sha, config_hash, data_source, 'RUNNING' "
            "FROM pipeline_runs WHERE run_id = ? AND NOT EXISTS (SELECT 1 FROM pipeline_runs WHERE run_id = ?)",
            (target_run_id, source_run_id, target_run_id),
        )
    tables = tables or (
        "orders",
        "forecast_demand",
        "forecast_model_lineage",
        "aggregate_plan",
        "sku_production_plan",
        "machine_capacity_plan",
        "mrp_plan",
        "machine_state_snapshot",
        "mes_order_tracking",
    )
    for table in tables:
        if not _SQLITE_IDENTIFIER.fullmatch(table):
            raise ValueError(f"Invalid table: {table}")
        info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        if "run_id" not in {row[1] for row in info}:
            continue
        columns = [row[1] for row in info if not (row[5] == 1 and row[2].upper() == "INTEGER")]
        df = pd.read_sql(f'SELECT * FROM "{table}" WHERE run_id = ?', conn, params=(source_run_id,))
        df = df[columns].copy()
        df["run_id"] = target_run_id
        persist_run_scoped_dataframe(conn, table, df, target_run_id)
    conn.commit()


def _sqlite_value(value):
    """Convert a pandas/numpy scalar to a sqlite3-compatible Python value."""
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "item"):
        try:
            value = value.item()
        except (AttributeError, ValueError):
            pass

    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        try:
            return value.isoformat()
        except (AttributeError, TypeError, ValueError):
            pass
    return value


def persist_run_scoped_dataframe(
    conn: sqlite3.Connection,
    table_name: str,
    df,
    run_id: str,
) -> None:
    """Persist exactly one run version without destroying historical runs.

    The first write is allowed to create the table. Subsequent writes replace
    only rows for the requested run_id. Existing-table writes use sqlite3
    directly so pandas ``to_sql`` cannot implicitly commit and invalidate the
    savepoint guarding the delete+insert operation.
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

    table_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if "run_id" not in table_columns:
        raise ValueError(f"[RUN GOVERNANCE] {table_name}: mevcut tablo run_id kolonu taşımıyor; migration gerekli.")

    frame_columns = [str(column) for column in scoped.columns]
    invalid_columns = [column for column in frame_columns if not _SQLITE_IDENTIFIER.fullmatch(column)]
    if invalid_columns:
        raise ValueError(f"[RUN GOVERNANCE] {table_name}: geçersiz kolon adları: {invalid_columns}")

    unknown_columns = set(frame_columns) - table_columns
    if unknown_columns:
        raise ValueError(
            f"[RUN GOVERNANCE] {table_name}: tablo şeması yeni kolonları içermiyor: {sorted(unknown_columns)}"
        )

    quoted_columns = ", ".join(f'"{column}"' for column in frame_columns)
    placeholders = ", ".join("?" for _ in frame_columns)
    insert_sql = f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'
    rows = [tuple(_sqlite_value(value) for value in row) for row in scoped.itertuples(index=False, name=None)]

    conn.execute("SAVEPOINT persist_run_scope")
    try:
        conn.execute(f'DELETE FROM "{table_name}" WHERE run_id = ?', (str(run_id),))
        if rows:
            conn.executemany(insert_sql, rows)
        conn.execute("RELEASE SAVEPOINT persist_run_scope")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT persist_run_scope")
        conn.execute("RELEASE SAVEPOINT persist_run_scope")
        raise


def table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return column_name in {row[1] for row in rows}


def migrate_schedule_commitments(conn) -> None:
    """Add explicit due-date/priority fields to pre-existing schedule history."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(production_schedule)")}
    if columns:
        for column in ("due_date_min", "priority_weight"):
            if column not in columns:
                conn.execute(f"ALTER TABLE production_schedule ADD COLUMN {column} INTEGER")
