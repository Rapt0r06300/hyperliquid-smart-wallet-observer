"""No operational /exchange path, no signature call, no real order in source.
place_order(...) is tolerated ONLY in the locked refusing testnet stub."""

from pathlib import Path

from hyper_smart_observer.audit.source_scanner import scan_source_forbidden_terms


def test_no_exchange_path_or_signature_or_real_order():
    findings = scan_source_forbidden_terms(Path("hyper_smart_observer"))
    assert findings["exchange_path"] == [], findings["exchange_path"]
    assert findings["sign_call"] == [], findings["sign_call"]
    assert all(
        p.replace("\\", "/").endswith("hyperliquid_client/testnet_exchange_client.py")
        for p in findings["place_order"]
    ), findings["place_order"]
