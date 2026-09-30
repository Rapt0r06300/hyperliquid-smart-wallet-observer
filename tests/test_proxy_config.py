"""Contrat du chaînon proxy: parsing, rotation round-robin, fallback direct sûr."""

from __future__ import annotations

from hl_observer.collection.proxy_config import ProxyRotator, load_proxies, parse_proxies
from hl_observer.collection.proxy_pool import ProxyEndpoint


def test_no_proxies_means_direct_output():
    assert parse_proxies("") == []
    assert parse_proxies(None) == []
    r = ProxyRotator([])
    assert r.enabled is False and r.egress_count() == 0
    assert r.next_url() is None                          # défaut sûr = sortie directe


def test_parse_various_formats_and_default_scheme():
    eps = parse_proxies("1.2.3.4:8000, http://u:p@5.6.7.8:9000\n9.9.9.9:1")
    assert [e.url for e in eps] == ["http://1.2.3.4:8000", "http://u:p@5.6.7.8:9000", "http://9.9.9.9:1"]


def test_load_from_env(monkeypatch):
    eps = load_proxies({"HYPERSMART_HTTP_PROXIES": "1.1.1.1:80,2.2.2.2:80"})
    assert len(eps) == 2 and eps[0].url == "http://1.1.1.1:80"


def test_rotation_round_robin_over_healthy():
    r = ProxyRotator(parse_proxies("1.1.1.1:80,2.2.2.2:80,3.3.3.3:80"))
    assert r.enabled and r.egress_count() == 3           # 3 IP = 3x le budget
    got = [r.next_url() for _ in range(6)]
    assert set(got) == {"http://1.1.1.1:80", "http://2.2.2.2:80", "http://3.3.3.3:80"}
    assert got[0] != got[1]                               # tourne bien


def test_unhealthy_endpoints_are_skipped():
    healthy = ProxyEndpoint(endpoint_id="ok", url="http://good:80")
    dead = ProxyEndpoint(endpoint_id="bad", url="http://bad:80", recent_429_count=3)  # is_healthy False
    r = ProxyRotator([healthy, dead])
    assert r.egress_count() == 1
    assert all(r.next_url() == "http://good:80" for _ in range(4))   # le mort est sauté
