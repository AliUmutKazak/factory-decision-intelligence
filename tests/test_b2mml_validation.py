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


def test_multiple_operations_share_one_lot_request_and_keep_unique_segments():
    first = ProductionScheduleTask(
        task_id="T1",
        lot_id="LOT1",
        product_id="P01",
        machine_id="M01",
        operation_seq=1,
        start_min=480,
        end_min=500,
        duration_min=20,
    )
    second = first.model_copy(
        update={
            "task_id": "T2",
            "machine_id": "M02",
            "operation_seq": 2,
            "start_min": 500,
            "end_min": 550,
            "duration_min": 50,
        }
    )
    result = ScheduleResult(status="FEASIBLE", makespan_hours=10, total_cost_eur=10, tasks=[first, second])
    xml = schedule_to_xml(result, origin=ORIGIN, schedule_id="MULTI-OP")
    root = validate_xml(xml)
    namespace = {"b": "http://www.mesa.org/xml/B2MML"}
    assert len(root.xpath("b:OperationsRequest", namespaces=namespace)) == 1
    assert len(root.xpath("b:OperationsRequest/b:SegmentRequirement", namespaces=namespace)) == 2
    assert schedule_from_xml(xml, origin=ORIGIN) == result
    with pytest.raises(ValueError, match="unique"):
        schedule_to_xml(result.model_copy(update={"tasks": [first, first]}), origin=ORIGIN, schedule_id="DUP")


def test_mes_import_rejects_conflicting_units_references_and_nonfinite_quantity():
    actual = MESActual(
        lot_id="L1",
        machine_id="M01",
        operation_seq=1,
        actual_start_min=480,
        actual_end_min=500,
        produced_qty=10,
        scrap_qty=1,
    )
    xml = mes_to_xml(actual, origin=ORIGIN)
    for wrong in (
        xml.replace("<OperationsRequestID>L1", "<OperationsRequestID>OTHER"),
        xml.replace("<UnitOfMeasure>units", "<UnitOfMeasure>kg"),
        xml.replace("<QuantityString>10.0", "<QuantityString>Infinity"),
    ):
        with pytest.raises(ValueError):
            mes_from_xml(wrong, origin=ORIGIN)
    with pytest.raises(ValueError, match="midnight"):
        mes_to_xml(actual, origin=ORIGIN.replace(hour=12))
