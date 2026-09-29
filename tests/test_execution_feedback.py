from src.integration.rescheduler import ClosedLoopRescheduler


def test_execution_feedback_within_tolerance():
    rescheduler = ClosedLoopRescheduler()
    # Planlanan ile gerceklesen arasindaki fark tolerans (20 dk) altinda
    feedback = rescheduler.record_execution_feedback(
        job_id="JOB_001",
        machine_id="CNC-01",
        planned_runtime_min=120.0,
        actual_runtime_min=125.0,
        planned_downtime_min=0.0,
        actual_downtime_min=5.0,
        planned_scrap_rate=0.0,
        actual_scrap_rate=0.01,
        tolerance_delay_min=20.0,
    )
    assert feedback["replan_required"] is False
    assert feedback["total_time_deviation_min"] == 10.0
    assert feedback["reschedule_result"] is None


def test_execution_feedback_triggers_replan_on_excessive_deviation():
    rescheduler = ClosedLoopRescheduler()
    # Ornek: 120 planlandi -> 147 gerceklesti (+27 dk)
    # 0 planned downtime -> 37 actual downtime (+37 dk)
    # 0 scrap -> %4 scrap (+0.04)
    feedback = rescheduler.record_execution_feedback(
        job_id="JOB_002",
        machine_id="CNC-01",
        planned_runtime_min=120.0,
        actual_runtime_min=147.0,
        planned_downtime_min=0.0,
        actual_downtime_min=37.0,
        planned_scrap_rate=0.0,
        actual_scrap_rate=0.04,
        tolerance_delay_min=20.0,
    )
    assert feedback["replan_required"] is True
    assert feedback["runtime_deviation_min"] == 27.0
    assert feedback["downtime_deviation_min"] == 37.0
    assert feedback["total_time_deviation_min"] == 64.0
    assert feedback["scrap_deviation"] == 0.04
