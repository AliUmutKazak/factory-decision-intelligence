"""Tests for Schedule Output Contracts (Faz 3 - Madde 6)."""

import pytest
from pydantic import ValidationError

from src.contracts.schemas import ScheduleOutputTask


def test_schedule_output_task_valid():
    """Geçerli bir çizelge çıktısının başarıyla doğrulanmasını test eder."""
    out = ScheduleOutputTask(
        run_id="RUN-01",
        task_id="T01",
        product_id="P01",
        machine_id="M01",
        start_min=60,
        end_min=120,
        duration_min=60,
        due_date_min=1440,
        tardiness_min=0,
    )
    assert out.start_min == 60
    assert out.end_min == 120
    assert out.tardiness_min == 0


def test_schedule_output_task_rejects_end_before_start():
    """Bitiş zamanının başlangıçtan önce olması durumunda doğrulama hatası fırlatılmasını test eder."""
    with pytest.raises(ValidationError):
        ScheduleOutputTask(
            run_id="RUN-01",
            task_id="T01",
            product_id="P01",
            machine_id="M01",
            start_min=100,
            end_min=50,  # Geçersiz: start'tan küçük
            duration_min=50,
            due_date_min=1440,
            tardiness_min=0,
        )


def test_schedule_output_task_rejects_negative_tardiness():
    """Negatif gecikme değerinin engellenmesini test eder."""
    with pytest.raises(ValidationError):
        ScheduleOutputTask(
            run_id="RUN-01",
            task_id="T01",
            product_id="P01",
            machine_id="M01",
            start_min=0,
            end_min=60,
            duration_min=60,
            due_date_min=1440,
            tardiness_min=-10,  # Geçersiz: negatif olamaz
        )
