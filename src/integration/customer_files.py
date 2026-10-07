"""Customer CSV boundary with explicit field/identifier maps.

Normalizes a supplied ERP order or MES actual file without synthetic identifiers
or silent fallback. Transport to a vendor endpoint is customer-specific and is
not represented by this read-only interchange adapter.
"""

import csv
import math
from pathlib import Path

from src.contracts.schemas import MESActual, ProductionOrder


class CustomerFileAdapter:
    def __init__(self, *, order_fields, actual_fields, product_ids, machine_ids):
        self.order_fields = dict(order_fields)
        self.actual_fields = dict(actual_fields)
        self.product_ids = dict(product_ids)
        self.machine_ids = dict(machine_ids)

    @staticmethod
    def _rows(path, fields):
        with Path(path).open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            missing = set(fields.values()) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Customer file missing columns: {sorted(missing)}")
            return [{canonical: row[external] for canonical, external in fields.items()} for row in reader]

    @staticmethod
    def _identifier(value, mapping, kind):
        if value not in mapping:
            raise ValueError(f"Unmapped customer {kind}: {value}")
        return mapping[value]

    @staticmethod
    def _finite(models):
        for model in models:
            for value in model.model_dump().values():
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Customer numeric inputs must be finite.")
        return models

    def read_orders(self, path):
        rows = self._rows(path, self.order_fields)
        orders = []
        for row in rows:
            row["product_id"] = self._identifier(row["product_id"], self.product_ids, "product")
            orders.append(ProductionOrder(**row))
        if len({order.order_id for order in orders}) != len(orders):
            raise ValueError("Duplicate customer order IDs.")
        return self._finite(orders)

    def read_actuals(self, path):
        rows = self._rows(path, self.actual_fields)
        actuals = []
        for row in rows:
            row["machine_id"] = self._identifier(row["machine_id"], self.machine_ids, "machine")
            actuals.append(MESActual(**row))
        if len({(actual.lot_id, actual.operation_seq) for actual in actuals}) != len(actuals):
            raise ValueError("Duplicate customer lot/operation actuals.")
        return self._finite(actuals)
