from __future__ import annotations

from hyper_smart_observer.dydx_v4.static_contract_audit import run_static_contract_audit


def test_dydx_static_contract_audit_ok() -> None:
    report = run_static_contract_audit()

    assert report["ok"] is True
    assert report["read_only"] is True
    assert report["paper_only"] is True
    assert report["errors"] == []
