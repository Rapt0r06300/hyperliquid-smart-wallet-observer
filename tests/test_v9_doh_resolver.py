import hl_observer.net.doh_resolver as doh
from hl_observer.net.doh_resolver import parse_doh_answer, resolve


def test_parse_doh_answer_extracts_ipv4():
    data = {
        "Answer": [
            {"name": "api.hyperliquid.xyz", "type": 5, "data": "cname.example."},  # CNAME ignoré
            {"name": "api.hyperliquid.xyz", "type": 1, "data": "104.18.1.2"},
            {"name": "api.hyperliquid.xyz", "type": 1, "data": "104.18.3.4"},
        ]
    }
    assert parse_doh_answer(data) == ["104.18.1.2", "104.18.3.4"]


def test_parse_doh_answer_empty():
    assert parse_doh_answer({}) == []
    assert parse_doh_answer({"Answer": []}) == []


def test_resolve_uses_system_dns_when_available(monkeypatch):
    monkeypatch.setattr(doh.socket, "gethostbyname", lambda h: "1.2.3.4")
    assert resolve("api.hyperliquid.xyz", use_cache=False) == "1.2.3.4"


def test_resolve_falls_back_to_doh_when_system_dns_fails(monkeypatch):
    def boom(_h):
        raise OSError("Temporary failure in name resolution")
    monkeypatch.setattr(doh.socket, "gethostbyname", boom)
    monkeypatch.setattr(doh, "resolve_via_doh", lambda host, timeout=10.0: "9.9.9.9")
    assert resolve("api.hyperliquid.xyz", use_cache=False) == "9.9.9.9"


def test_resolve_returns_none_when_all_fail(monkeypatch):
    monkeypatch.setattr(doh.socket, "gethostbyname", lambda h: (_ for _ in ()).throw(OSError("dns")))
    monkeypatch.setattr(doh, "resolve_via_doh", lambda host, timeout=10.0: None)
    assert resolve("api.hyperliquid.xyz", use_cache=False) is None
