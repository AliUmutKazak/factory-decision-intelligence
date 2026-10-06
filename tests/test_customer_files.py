import pytest

from src.integration.customer_files import CustomerFileAdapter


def adapter():
    return CustomerFileAdapter(
        order_fields={"order_id": "Order", "product_id": "Item", "quantity": "Qty", "due_date": "Due"},
        actual_fields={
            "lot_id": "Lot",
            "machine_id": "WC",
            "operation_seq": "Op",
            "actual_start_min": "Start",
            "actual_end_min": "End",
            "produced_qty": "Good",
            "scrap_qty": "Scrap",
        },
        product_ids={"ERP-100": "P01"},
        machine_ids={"WC-1": "M01"},
    )


def test_customer_files_validate_and_map_actual_supplied_records(tmp_path):
    orders = tmp_path / "orders.csv"
    orders.write_text("Order,Item,Qty,Due\nSO-1,ERP-100,10,2026-10-10\n")
    actuals = tmp_path / "actuals.csv"
    actuals.write_text("Lot,WC,Op,Start,End,Good,Scrap\nL-1,WC-1,10,480,510,9,1\n")
    assert adapter().read_orders(orders)[0].product_id == "P01"
    actual = adapter().read_actuals(actuals)[0]
    assert actual.machine_id == "M01" and actual.operation_seq == 10 and actual.scrap_qty == 1


def test_customer_import_rejects_unknown_identifiers_and_duplicate_orders(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("Order,Item,Qty,Due\nSO-1,UNKNOWN,10,2026-10-10\n")
    with pytest.raises(ValueError, match="Unmapped"):
        adapter().read_orders(path)
    path.write_text("Order,Item,Qty,Due\nSO-1,ERP-100,10,2026-10-10\nSO-1,ERP-100,10,2026-10-10\n")
    with pytest.raises(ValueError, match="Duplicate"):
        adapter().read_orders(path)
