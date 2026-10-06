"""Validated B2MML 0701 schedule/performance interchange.

The Business To Manufacturing Markup Language (B2MML) is used courtesy of
MESA International. This is an explicit factory profile of the standard; XSD
validity is not evidence of interoperability with an untested vendor endpoint.
Relative minutes require a caller-supplied timezone-aware Monday epoch.
"""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from lxml import etree

from src.contracts.schemas import MESActual, ProductionScheduleTask, ScheduleResult

NS = "http://www.mesa.org/xml/B2MML"
SCHEMA_DIR = Path(__file__).parent / "xsd" / "b2mml-0701"


def _element(parent, name, value=None):
    child = etree.SubElement(parent, f"{{{NS}}}{name}")
    if value is not None:
        child.text = str(value)
    return child


def _origin(origin):
    if origin.tzinfo is None or origin.utcoffset() is None or origin.weekday() != 0:
        raise ValueError("Factory time origin must be a timezone-aware Monday.")
    return origin


def _time(origin, minutes):
    return (_origin(origin) + timedelta(minutes=minutes)).isoformat()


def _minutes(origin, timestamp):
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Interchange timestamps must carry a timezone.")
    return (value - _origin(origin)).total_seconds() / 60


@lru_cache(maxsize=2)
def _schema(root_name):
    if root_name not in {"OperationsSchedule", "OperationsPerformance"}:
        raise ValueError("Unsupported B2MML root.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.XMLSchema(etree.parse(str(SCHEMA_DIR / f"B2MML-{root_name}.xsd"), parser))


def validate_xml(xml):
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(xml.encode() if isinstance(xml, str) else xml, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("B2MML messages cannot contain a DTD.")
    name = etree.QName(root)
    if name.namespace != NS:
        raise ValueError("Expected the B2MML 0701 namespace.")
    _schema(name.localname).assertValid(root)
    return root


def _serialize(root):
    xml = etree.tostring(root, encoding="unicode")
    validate_xml(xml)
    return xml


def _text(root, path):
    values = root.xpath(path, namespaces={"b": NS})
    if len(values) != 1 or values[0].text is None:
        raise ValueError(f"Factory interchange profile requires exactly one {path}.")
    return values[0].text


def _parameter(parent, kind, name, value, unit=None):
    parameter = _element(parent, kind)
    _element(parameter, "ID", name)
    data = _element(parameter, "Value")
    _element(data, "ValueString", value)
    if unit:
        _element(data, "UnitOfMeasure", unit)


def schedule_to_xml(result: ScheduleResult, *, origin: datetime, schedule_id: str):
    if not result.tasks or not schedule_id:
        raise ValueError("B2MML schedules require an ID and at least one task.")
    root = etree.Element(f"{{{NS}}}OperationsSchedule", nsmap={None: NS})
    _element(root, "ID", schedule_id)
    _element(
        root,
        "Description",
        json.dumps(
            {
                "profile": "factory-v1",
                "status": result.status,
                "makespan_hours": result.makespan_hours,
                "total_cost_eur": result.total_cost_eur,
            }
        ),
    )
    _element(root, "OperationsType", "Production")
    for task in result.tasks:
        request = _element(root, "OperationsRequest")
        _element(request, "ID", task.lot_id)
        segment = _element(request, "SegmentRequirement")
        _element(segment, "ID", task.task_id)
        _element(segment, "EarliestStartTime", _time(origin, task.start_min))
        _element(segment, "LatestEndTime", _time(origin, task.end_min))
        _element(segment, "ProcessSegmentID", task.operation_seq)
        _element(segment, "OperationsDefinitionID", task.product_id)
        _element(segment, "OperationsSegmentID", task.operation_seq)
        _parameter(segment, "SegmentParameter", "duration_min", task.duration_min, "minute")
        equipment = _element(segment, "EquipmentRequirement")
        _element(equipment, "ID", task.machine_id)
        _element(equipment, "EquipmentID", task.machine_id)
    return _serialize(root)


def schedule_from_xml(xml, *, origin: datetime):
    root = validate_xml(xml)
    if etree.QName(root).localname != "OperationsSchedule":
        raise ValueError("Expected OperationsSchedule.")
    details = json.loads(_text(root, "b:Description"))
    if details.pop("profile", None) != "factory-v1":
        raise ValueError("Schedule is not the declared factory-v1 interchange profile.")
    tasks = []
    for request in root.findall(f"{{{NS}}}OperationsRequest"):
        for segment in request.findall(f"{{{NS}}}SegmentRequirement"):
            tasks.append(
                ProductionScheduleTask(
                    task_id=_text(segment, "b:ID"),
                    lot_id=_text(request, "b:ID"),
                    product_id=_text(segment, "b:OperationsDefinitionID"),
                    machine_id=_text(segment, "b:EquipmentRequirement/b:EquipmentID"),
                    operation_seq=int(_text(segment, "b:OperationsSegmentID")),
                    start_min=_minutes(origin, _text(segment, "b:EarliestStartTime")),
                    end_min=_minutes(origin, _text(segment, "b:LatestEndTime")),
                    duration_min=float(_text(segment, "b:SegmentParameter[b:ID='duration_min']/b:Value/b:ValueString")),
                )
            )
    return ScheduleResult(**details, tasks=tasks)


def mes_to_xml(actual: MESActual, *, origin: datetime):
    root = etree.Element(f"{{{NS}}}OperationsPerformance", nsmap={None: NS})
    _element(root, "ID", f"ACTUAL-{actual.lot_id}-{actual.operation_seq}")
    response = _element(root, "OperationsResponse")
    _element(response, "ID", f"RESP-{actual.lot_id}-{actual.operation_seq}")
    _element(response, "OperationsRequestID", actual.lot_id)
    segment = _element(response, "SegmentResponse")
    _element(segment, "ID", f"{actual.lot_id}-{actual.operation_seq}")
    _element(segment, "ActualStartTime", _time(origin, actual.actual_start_min))
    _element(segment, "ActualEndTime", _time(origin, actual.actual_end_min))
    _element(segment, "ProcessSegmentID", actual.operation_seq)
    _element(segment, "OperationsRequestID", actual.lot_id)
    _parameter(segment, "SegmentData", "scrap_qty", actual.scrap_qty, "units")
    equipment = _element(segment, "EquipmentActual")
    _element(equipment, "ID", actual.machine_id)
    _element(equipment, "EquipmentID", actual.machine_id)
    material = _element(segment, "MaterialActual")
    _element(material, "ID", actual.lot_id)
    _element(material, "MaterialLotID", actual.lot_id)
    _element(material, "MaterialUse", "Produced")
    quantity = _element(material, "Quantity")
    _element(quantity, "QuantityString", actual.produced_qty)
    _element(quantity, "UnitOfMeasure", "units")
    return _serialize(root)


def mes_from_xml(xml, *, origin: datetime):
    root = validate_xml(xml)
    if etree.QName(root).localname != "OperationsPerformance":
        raise ValueError("Expected OperationsPerformance.")
    # Single-operation MESActual contract: reject ambiguous multi-response input.
    segments = root.xpath("b:OperationsResponse/b:SegmentResponse", namespaces={"b": NS})
    if len(segments) != 1:
        raise ValueError("MESActual requires exactly one segment response.")
    segment = segments[0]
    if _text(segment, "b:MaterialActual/b:Quantity/b:UnitOfMeasure") != "units":
        raise ValueError("Factory MESActual expects quantities in units.")
    return MESActual(
        lot_id=_text(segment, "b:MaterialActual/b:MaterialLotID"),
        machine_id=_text(segment, "b:EquipmentActual/b:EquipmentID"),
        operation_seq=int(_text(segment, "b:ProcessSegmentID")),
        actual_start_min=_minutes(origin, _text(segment, "b:ActualStartTime")),
        actual_end_min=_minutes(origin, _text(segment, "b:ActualEndTime")),
        produced_qty=float(_text(segment, "b:MaterialActual/b:Quantity/b:QuantityString")),
        scrap_qty=float(_text(segment, "b:SegmentData[b:ID='scrap_qty']/b:Value/b:ValueString")),
    )
