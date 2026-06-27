from __future__ import annotations

from hyper_smart_observer.dydx_v4.mega_audit import run_mega_audit


def test_dydx_mega_audit_ok() -> None:
    report = run_mega_audit()

    assert report["ok"] is True
    assert report["read_only"] is True
    assert report["paper_only"] is True
    assert report["errors"] == []
