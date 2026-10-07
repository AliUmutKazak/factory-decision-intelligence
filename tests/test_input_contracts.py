"""Tests for Schedule Input Contracts and Pre-Solver Validation Shield (Faz 3 - Madde 3)."""

import sqlite3
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config import DB_PATH
from src.contracts.schemas import ScheduleInputPayload, ScheduleTaskInput
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.utils.db import clone_run_inputs, get_active_run_id


def test_schedule_task_input_valid():
    """Geçerli bir görev girdisinin başarıyla doğrulanmasını test eder."""
    task = ScheduleTaskInput(
        task_id="T01",
        product_id="P01",
        machine_id="M01",
        duration_min=45,
        due_date_min=1440,
        weight=2.5,
        earliest_start_min=120,
        sequence_family="FAM_A",
    )
    assert task.task_id == "T01"
    assert task.duration_min == 45


def test_schedule_task_input_rejects_non_positive_duration():
    """İşlem süresi 0 veya negatif olan görevlerin reddedilmesini test eder."""
    with pytest.raises(ValidationError):
        ScheduleTaskInput(
            task_id="T02",
            product_id="P01",
            machine_id="M01",
            duration_min=0,  # Sıfır veya negatif süre olamaz (gt=0)
            due_date_min=1440,
        )


def test_schedule_input_payload_rejects_empty_task_list():
    """Boş görev listesiyle çizelgeleme başlatılmasını engeller."""
    with pytest.raises(ValidationError):
        ScheduleInputPayload(
            tasks=[],  # min_length=1 kuralı
            time_limit_seconds=10.0,
            random_seed=42,
        )


def test_run_cpsat_scheduling_rejects_corrupted_task_duration():
    """Veritabanında süresi sıfır/negatif bozuk görev olduğunda çözücünün erken durmasını test eder."""
    disk_conn = sqlite3.connect(DB_PATH)
    mem_conn = sqlite3.connect(":memory:")
    disk_conn.backup(mem_conn)
    disk_conn.close()

    clone_run_inputs(mem_conn, get_active_run_id(mem_conn), "RUN-TEST-CORRUPT")

    # Bozucu veri enjeksiyonu: routing tablosundaki işlem sürelerinden birini 0 yapıyoruz
    mem_conn.execute("UPDATE routing SET processing_time_min = 0 WHERE operation_seq = 1")
    mem_conn.commit()

    class NoCloseConnectionWrapper:
        def __init__(self, target):
            self._target = target

        def close(self):
            pass

        def __getattr__(self, name):
            return getattr(self._target, name)

    wrapped_conn = NoCloseConnectionWrapper(mem_conn)

    try:
        with (
            patch("src.scheduling.schedule_cpsat.get_db_connection", return_value=wrapped_conn),
            patch("src.scheduling.schedule_cpsat.CPSAT_TIME_LIMIT_SECONDS", 2),
        ):
            with pytest.raises(ValidationError):
                run_cpsat_scheduling(run_id="RUN-TEST-CORRUPT")
    finally:
        mem_conn.close()
