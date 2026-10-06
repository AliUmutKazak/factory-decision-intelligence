import pandas as pd
import pytest

from src.config import DB_PATH, OBJECTIVE_POLICIES, SchedulingObjectivePolicy
from src.scheduling.schedule_cpsat import run_cpsat_scheduling
from src.utils.db import clone_run_inputs, get_db_connection


def test_unknown_policy_is_rejected_before_any_solve():
    with pytest.raises(ValueError, match="UNKNOWN_COST_POLICY"):
        run_cpsat_scheduling(policy="UNKNOWN_COST_POLICY", persist_outputs=False)


def test_objective_policies_configuration():
    """Tüm politikaların eksiksiz tanımlandığını ve ağırlık hiyerarşisini doğrular."""
    assert SchedulingObjectivePolicy.BALANCED in OBJECTIVE_POLICIES
    assert SchedulingObjectivePolicy.SERVICE_LEVEL_FIRST in OBJECTIVE_POLICIES
    assert SchedulingObjectivePolicy.THROUGHPUT_MAX in OBJECTIVE_POLICIES
    assert SchedulingObjectivePolicy.OPERATIONAL_BALANCED in OBJECTIVE_POLICIES
    assert SchedulingObjectivePolicy.COST_OPTIMIZED in OBJECTIVE_POLICIES

    # Servis seviyesi politikasında gecikme ağırlığı Makespan'e baskın olmalıdır
    service_weights = OBJECTIVE_POLICIES[SchedulingObjectivePolicy.SERVICE_LEVEL_FIRST]
    assert service_weights.tardiness_weight > service_weights.makespan_weight

    # Throughput odaklı politikada setup ve gecikme cezası sıfırlanmalıdır
    throughput_weights = OBJECTIVE_POLICIES[SchedulingObjectivePolicy.THROUGHPUT_MAX]
    assert throughput_weights.setup_weight == 0
    assert throughput_weights.tardiness_weight == 0


def test_cpsat_dynamic_policy_execution(ensure_full_pipeline_database):
    """Farklı politikalarla CP-SAT fonksiyonunun aktif run_id ile başarıyla çalıştığını doğrular."""
    with get_db_connection(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE' ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
        active_run_id = row[0] if row else "TEST-POLICY-RUN"

        sku_plan_real = pd.read_sql(
            "SELECT * FROM sku_production_plan WHERE run_id = (SELECT run_id FROM pipeline_runs WHERE status = 'ACTIVE') AND period_week = 1",
            conn,
        )

    with get_db_connection(DB_PATH) as conn:
        clone_run_inputs(conn, active_run_id, "POLICY_BALANCED")
        clone_run_inputs(conn, active_run_id, "POLICY_SERVICE")

    # 1. Varsayılan (BALANCED) Politika ile Koşum
    run_cpsat_scheduling(
        sku_plan=sku_plan_real,
        run_id="POLICY_BALANCED",
        persist_outputs=False,
        policy=SchedulingObjectivePolicy.BALANCED,
    )
    with get_db_connection(DB_PATH) as conn:
        df_balanced = pd.read_sql(
            "SELECT * FROM production_schedule WHERE run_id = ?",
            conn,
            params=("POLICY_BALANCED",),
        )

    assert not df_balanced.empty
    assert "start_min" in df_balanced.columns
    assert "end_min" in df_balanced.columns

    # 2. Servis Seviyesi Odaklı Politika ile Koşum (aynı aktif koşum altında güncellenir)
    run_cpsat_scheduling(
        sku_plan=sku_plan_real,
        run_id="POLICY_SERVICE",
        persist_outputs=False,
        policy=SchedulingObjectivePolicy.SERVICE_LEVEL_FIRST,
    )
    with get_db_connection(DB_PATH) as conn:
        df_service = pd.read_sql(
            "SELECT * FROM production_schedule WHERE run_id = ?",
            conn,
            params=("POLICY_SERVICE",),
        )

    assert not df_service.empty
    assert len(df_service) == len(df_balanced)
