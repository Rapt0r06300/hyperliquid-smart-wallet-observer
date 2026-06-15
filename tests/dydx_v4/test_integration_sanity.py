from __future__ import annotations

from hyper_smart_observer.dydx_v4.integration_sanity import run_integration_sanity


def test_dydx_integration_sanity_ok() -> None:
    result = run_integration_sanity()

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["paper_only"] is True
    assert result["errors"] == []
