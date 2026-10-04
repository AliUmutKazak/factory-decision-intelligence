"""Tests for Schedule Solver Contracts, Status Enums, and Determinism Metadata (Faz 3 - Madde 1 & 2)."""

import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from pydantic import ValidationError

from src.contracts.schemas import ScheduleSolverMetadata, SolverStatus
from src.scheduling.schedule_cpsat import run_cpsat_scheduling


def test_solver_status_enum_values():
    """Çözücü durum kodlarının beklenen değerleri içerdiğini ve StrEnum olduğunu doğrular."""
    assert SolverStatus.OPTIMAL == "OPTIMAL"
    assert SolverStatus.FEASIBLE == "FEASIBLE"
    assert SolverStatus.INFEASIBLE == "INFEASIBLE"
    assert SolverStatus.MODEL_INVALID == "MODEL_INVALID"
    assert SolverStatus.UNKNOWN == "UNKNOWN"


def test_schedule_solver_metadata_valid_optimal():
    """OPTIMAL durumundaki geçerli bir metadata modelinin hatasız doğrulandığını test eder."""
    metadata = ScheduleSolverMetadata(
        run_id="RUN-20261004-OPT",
        status=SolverStatus.OPTIMAL,
        proven_optimal=True,
        wall_time_seconds=1.45,
        objective_value=12500.0,
        best_objective_bound=12500.0,
        random_seed=42,
        num_search_workers=4,
        time_limit_seconds=30.0,
    )
    assert metadata.status == SolverStatus.OPTIMAL
    assert metadata.proven_optimal is True
    assert metadata.objective_value == 12500.0
    assert metadata.num_search_workers == 4


def test_schedule_solver_metadata_valid_feasible_with_gap():
    """FEASIBLE durumundaki metadata modelinde gap ve sınırların tutulduğunu doğrular."""
    metadata = ScheduleSolverMetadata(
        run_id="RUN-20261004-FEAS",
        status=SolverStatus.FEASIBLE,
        proven_optimal=False,
        wall_time_seconds=30.01,
        objective_value=14200.0,
        best_objective_bound=12000.0,
        random_seed=42,
        num_search_workers=8,
        time_limit_seconds=30.0,
    )
    assert metadata.status == SolverStatus.FEASIBLE
    assert metadata.proven_optimal is False
    assert metadata.objective_value > metadata.best_objective_bound


def test_schedule_solver_metadata_invalid_workers():
    """Arama işçisi sayısı 1'den küçük olduğunda ValidationError fırlatılmalıdır."""
    with pytest.raises(ValidationError):
        ScheduleSolverMetadata(
            run_id="RUN-ERR",
            status=SolverStatus.OPTIMAL,
            proven_optimal=True,
            wall_time_seconds=0.5,
            num_search_workers=0,  # ge=1 kısıtına takılmalı
            time_limit_seconds=10.0,
        )


def test_schedule_solver_metadata_invalid_time_limit():
    """Zaman limiti 0 veya negatif olduğunda ValidationError fırlatılmalıdır."""
    with pytest.raises(ValidationError):
        ScheduleSolverMetadata(
            run_id="RUN-ERR",
            status=SolverStatus.OPTIMAL,
            proven_optimal=True,
            wall_time_seconds=0.5,
            num_search_workers=2,
            time_limit_seconds=0.0,  # gt=0 kısıtına takılmalı
        )


def test_run_cpsat_scheduling_returns_valid_solver_metadata():
    """run_cpsat_scheduling fonksiyonunun ScheduleSolverMetadata döndürdüğünü ve DB'ye mühürlediğini doğrular."""
    from src.config import DB_PATH

    # Gerçek DB'yi in-memory klonlayarak tam şema ve veri izolasyonu sağlıyoruz
    disk_conn = sqlite3.connect(DB_PATH)
    mem_conn = sqlite3.connect(":memory:")
    disk_conn.backup(mem_conn)
    disk_conn.close()

    # run_cpsat_scheduling içindeki conn.close() çağrısının DB'yi kapatmasını engelleyen wrapper
    class NoCloseConnectionWrapper:
        def __init__(self, target):
            self._target = target

        def close(self):
            pass

        def __getattr__(self, name):
            return getattr(self._target, name)

    wrapped_conn = NoCloseConnectionWrapper(mem_conn)
    test_run_id = "RUN-TEST-CONTRACT-001"

    try:
        with (
            patch("src.scheduling.schedule_cpsat.get_db_connection", return_value=wrapped_conn),
            patch("src.scheduling.schedule_cpsat.CPSAT_TIME_LIMIT_SECONDS", 2),
        ):
            result = run_cpsat_scheduling(run_id=test_run_id)

            # 1. Sözleşme tipi ve alan doğrulaması
            assert isinstance(result, ScheduleSolverMetadata)
            assert result.run_id == test_run_id
            assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
            assert result.wall_time_seconds >= 0.0
            assert result.objective_value is not None

            # 2. SQLite veritabanına mühürlenme denetimi
            df_meta = pd.read_sql(
                f"SELECT * FROM schedule_solver_metadata WHERE run_id = '{test_run_id}'",
                mem_conn,
            )
            assert not df_meta.empty
            assert df_meta.iloc[0]["run_id"] == test_run_id
            assert df_meta.iloc[0]["status"] in ["OPTIMAL", "FEASIBLE"]
    finally:
        mem_conn.close()

    # 1. Sözleşme tipi ve alan doğrulaması
    assert isinstance(result, ScheduleSolverMetadata)
    assert result.run_id == test_run_id
    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert result.wall_time_seconds >= 0.0
    assert result.objective_value is not None

    # Faz 3 - Madde 4: Çok amaçlı metrik denetimi
    assert result.makespan_min is not None and result.makespan_min > 0
    assert result.total_setup_min is not None and result.total_setup_min >= 0
    assert result.total_tardiness_min is not None and result.total_tardiness_min >= 0
