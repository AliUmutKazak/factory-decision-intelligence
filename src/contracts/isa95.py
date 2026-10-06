"""Madde 26: ISA-95 Semantic Alignment & Enterprise Integration Adapters.

MESA International B2MML (Business To Manufacturing Markup Language) standardı,
tarihsel ve operasyonel olarak bir XML implementasyonudur.

Bu modül:
1. İç Sistem Sözleşmesi (Internal Canonical Contract): Pydantic modelleri
2. Semantik Hizalama (ISA-95 Alignment): ANSI/ISA-95 Part 2 & Part 3 nesneleri
3. Adaptör Katmanı (Optional Adapters):
   - JSON API Payload Adapter
   - XSD-validated B2MML 0701 XML Adapter
   - Vendor-Specific ERP / MES Normalizer
"""

from datetime import datetime
from typing import Any

from src.contracts.b2mml import mes_from_xml, mes_to_xml, schedule_from_xml, schedule_to_xml, validate_xml
from src.contracts.schemas import (
    MESActual,
    ProductionOrder,
    ScheduleResult,
)


class ISA95Adapter:
    """ISA-95 JSON semantics and XSD-validated B2MML 0701 factory profile.

    Schedule and MES round trips are supported. A particular customer/vendor
    endpoint still requires acceptance testing with that endpoint.
    """

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
    def mes_actual_to_b2mml_xml(mes: MESActual, *, origin: datetime) -> str:
        return mes_to_xml(mes, origin=origin)

    @staticmethod
    def schedule_result_to_b2mml_xml(result: ScheduleResult, *, origin: datetime, schedule_id: str) -> str:
        return schedule_to_xml(result, origin=origin, schedule_id=schedule_id)

    mes_actual_from_b2mml_xml = staticmethod(mes_from_xml)
    schedule_result_from_b2mml_xml = staticmethod(schedule_from_xml)
    validate_b2mml_xml = staticmethod(validate_xml)
