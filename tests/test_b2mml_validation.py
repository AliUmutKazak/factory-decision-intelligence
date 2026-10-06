import hashlib
import json
from datetime import UTC, datetime, timezone

import pytest
from lxml import etree

from src.contracts.b2mml import SCHEMA_DIR, mes_from_xml, mes_to_xml, schedule_from_xml, schedule_to_xml, validate_xml
from src.contracts.schemas import MESActual, ProductionScheduleTask, ScheduleResult

ORIGIN = datetime(2026, 10, 5, tzinfo=UTC)


def test_vendored_schemas_are_unmodified_official_dependency_closure():
    source = json.loads((SCHEMA_DIR / "SOURCE.json").read_text())
    for name, expected in source["sha256"].items():
        assert hashlib.sha256((SCHEMA_DIR / name).read_bytes()).hexdigest() == expected


def test_mes_xsd_validated_roundtrip_preserves_scrap_and_timezone():
    actual = MESActual(
        lot_id="LOT<&1",
        machine_id="WC-2",
        operation_seq=10,
        actual_start_min=480.5,
        actual_end_min=500.25,
        produced_qty=11.5,
        scrap_qty=2.5,
    )
    xml = mes_to_xml(actual, origin=ORIGIN)
    validate_xml(xml)
    assert mes_from_xml(xml, origin=ORIGIN) == actual
    with pytest.raises(etree.DocumentInvalid):
        validate_xml(xml.replace("<ID>", "<WrongID>").replace("</ID>", "</WrongID>"))


def test_schedule_validated_roundtrip_preserves_lot_route_and_economics():
    result = ScheduleResult(
        status="FEASIBLE",
        makespan_hours=12.5,
        total_cost_eur=125.2,
        tasks=[
            ProductionScheduleTask(
                task_id="T1",
                lot_id="L1",
                product_id="P01",
                machine_id="M01",
                operation_seq=10,
                start_min=480,
                end_min=530,
                duration_min=50,
            )
        ],
    )
    assert schedule_from_xml(schedule_to_xml(result, origin=ORIGIN, schedule_id="VER-1"), origin=ORIGIN) == result
    with pytest.raises(ValueError, match="Monday"):
        schedule_to_xml(result, origin=ORIGIN.replace(tzinfo=None), schedule_id="VER-1")
    with pytest.raises(ValueError, match="at least one"):
        schedule_to_xml(result.model_copy(update={"tasks": []}), origin=ORIGIN, schedule_id="EMPTY")


def test_dtd_messages_rejected():
    with pytest.raises(ValueError, match="DTD"):
        validate_xml(
            '<!DOCTYPE OperationsPerformance [<!ENTITY x "external">]><OperationsPerformance xmlns="http://www.mesa.org/xml/B2MML"/>'
        )
