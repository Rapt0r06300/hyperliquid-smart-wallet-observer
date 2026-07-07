"""Empty paper state => clean zeros, never fabricated positions/PnL."""

from __future__ import annotations

from hyper_smart_observer.dashboard.exporter import export_dashboard
from tests.hl_runtime_fakes import runtime_config


def test_dashboard_empty_paper_is_clean(tmp_path):
    cfg = runtime_config(tmp_path)
    html = export_dashboard(cfg).read_text(encoding="utf-8")
    assert "Open paper simulations: 0" in html
    low = html.lower()
    for marker in ("math.random", "fakeposition", "dummyequity", "fabricated"):
        assert marker not in low
