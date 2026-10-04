"""Madde 26: ISA-95 Semantic Alignment & Enterprise Integration Adapters.

MESA International B2MML (Business To Manufacturing Markup Language) standardı,
tarihsel ve operasyonel olarak bir XML implementasyonudur.

Bu modül:
1. İç Sistem Sözleşmesi (Internal Canonical Contract): Pydantic modelleri
2. Semantik Hizalama (ISA-95 Alignment): ANSI/ISA-95 Part 2 & Part 3 nesneleri
3. Adaptör Katmanı (Optional Adapters):
   - JSON API Payload Adapter
   - B2MML / XML Serialization Adapter
   - Vendor-Specific ERP / MES Normalizer
"""

from typing import Any
import xml.etree.ElementTree as ET

from src.contracts.schemas import (
    MESActual,
    ProductionOrder,
    ProductionScheduleTask,
    ScheduleResult,
)


class ISA95Adapter:
    """Enterprise Canonical Model ile ISA-95 / B2MML arasında çift yönlü adaptör."""

    @staticmethod
    def order_to_isa95_dict(order: ProductionOrder) -> dict[str, Any]:
        """ERP ProductionOrder nesnesini ISA-95 OperationsSchedule / ProductionOrder yapısına dönüştürür."""
        return {
            "OperationsRequest": {
                "ID": order.order_id,
                "ProductProductionRule": order.product_id,
                "TargetQuantity": {
                    "QuantityString": str(order.quantity),
                    "UnitOfMeasure": "units",
                },
                "RequestedCompletionTime": str(order.due_date),
                "Priority": order.priority,
                "CustomerTier": order.customer_tier,
                "HierarchyScope": "Enterprise/Site/Area",
            }
        }

    @staticmethod
    def mes_actual_to_b2mml_xml(mes: MESActual) -> str:
        """MES Actual üretim kaydını ISA-95 ProductionPerformance B2MML uyumlu XML çıktısına dönüştürür."""
        root = ET.Element("ProductionPerformance")
        root.set("xmlns", "http://www.mesa.org/xml/B2MML-V0600")

        resp = ET.SubElement(root, "ProductionResponse")
        ET.SubElement(resp, "ID").text = f"RESP-{mes.lot_id}-{mes.operation_seq}"
        ET.SubElement(resp, "WorkCenterID").text = mes.machine_id

        actual_time = ET.SubElement(resp, "ActualTimeRange")
        ET.SubElement(actual_time, "StartTimeMin").text = str(mes.actual_start_min)
        ET.SubElement(actual_time, "EndTimeMin").text = str(mes.actual_end_min)

        prod_data = ET.SubElement(resp, "MaterialProducedActual")
        ET.SubElement(prod_data, "QuantityProduced").text = str(mes.produced_qty)
        ET.SubElement(prod_data, "QuantityScrap").text = str(mes.scrap_qty)

        return ET.tostring(root, encoding="utf-8").decode("utf-8")

    @staticmethod
    def schedule_result_to_b2mml_xml(result: ScheduleResult) -> str:
        """ScheduleResult çıktısını ISA-95 ProductionSchedule B2MML uyumlu XML çıktısına dönüştürür."""
        root = ET.Element("ProductionSchedule")
        root.set("xmlns", "http://www.mesa.org/xml/B2MML-V0600")

        header = ET.SubElement(root, "Header")
        ET.SubElement(header, "Status").text = result.status
        ET.SubElement(header, "MakespanHours").text = str(result.makespan_hours)
        ET.SubElement(header, "TotalCostEUR").text = str(result.total_cost_eur)

        tasks_elem = ET.SubElement(root, "ScheduledWorkOrders")
        for t in result.tasks:
            wo = ET.SubElement(tasks_elem, "WorkOrder")
            ET.SubElement(wo, "TaskID").text = t.task_id
            ET.SubElement(wo, "LotID").text = t.lot_id
            ET.SubElement(wo, "ProductID").text = t.product_id
            ET.SubElement(wo, "WorkCenterID").text = t.machine_id
            ET.SubElement(wo, "Sequence").text = str(t.operation_seq)
            ET.SubElement(wo, "ScheduledStartMin").text = str(t.start_min)
            ET.SubElement(wo, "ScheduledEndMin").text = str(t.end_min)

        return ET.tostring(root, encoding="utf-8").decode("utf-8")
