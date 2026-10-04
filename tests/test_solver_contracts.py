"""Tests for Schedule Solver Contracts, Status Enums, and Determinism Metadata (Faz 3 - Madde 1 & 2)."""

import pytest
from pydantic import ValidationError

from src.contracts.schemas import ScheduleSolverMetadata, SolverStatus


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
