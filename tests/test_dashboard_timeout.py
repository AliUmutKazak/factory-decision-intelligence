"""Dashboard keeps failed hot-order scenarios visibly separate from published plans."""

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.scheduling.what_if import WhatIfEngine


def test_hot_order_timeout_shows_warning_without_success():
    dashboard = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    app = AppTest.from_file(str(dashboard), default_timeout=60).run()
    app.radio[0].set_value("🔥 Acil Sipariş Enjeksiyonu (Hot-Order)").run()
    next(widget for widget in app.number_input if widget.label == "Sipariş Miktarı:").set_value(51)
    next(widget for widget in app.slider if widget.label == "Öncelik Ağırlığı:").set_value(7)
    observed = []

    def timeout(_engine, injection):
        observed.append(injection)
        raise TimeoutError("forced timeout")

    with patch.object(WhatIfEngine, "simulate_hot_order", timeout):
        app.button(key="FormSubmitter:hot_order_form-Acil Siparişi Çizelgeye Ekle").click().run()

    assert len(observed) == 1
    assert observed[0].quantity == 51
    assert observed[0].priority_weight == 7
    assert not app.exception and not app.error
    assert any("ACTIVE plan değiştirilmedi" in warning.value for warning in app.warning)
    assert not any("Acil sipariş başarıyla çizelgeye dahil edildi" in item.value for item in app.success)
