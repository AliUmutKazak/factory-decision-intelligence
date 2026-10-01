import pytest

from src.utils.erp_service import ERPService


def test_erp_mapping_forward_lookup():
    """Dahili ID'den ERP koduna dönüşüm testi."""
    erp_sku = ERPService.get_erp_code("SKU", "P01")
    assert erp_sku == "MAT-10001"

    erp_machine = ERPService.get_erp_code("MACHINE", "M01")
    assert erp_machine == "WC-CNC-5AX"


def test_erp_mapping_reverse_lookup():
    """ERP kodundan dahili ID'ye ters dönüşüm testi."""
    internal_sku = ERPService.get_internal_id("SKU", "MAT-10002")
    assert internal_sku == "P02"

    internal_rm = ERPService.get_internal_id("RAW_MATERIAL", "RAW-ST52-01")
    assert internal_rm == "RM_STEEL_01"


def test_erp_mapping_nonexistent_returns_none():
    """Geçersiz kayıtların None dönmesi testi."""
    assert ERPService.get_erp_code("SKU", "NON_EXISTENT") is None
