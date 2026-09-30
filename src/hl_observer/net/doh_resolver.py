"""Résolution DNS résiliente (DNS-over-HTTPS) — read-only, légitime.

Quand le DNS LOCAL de la machine échoue ("Temporary failure in name resolution")
alors que l'accès HTTPS sortant marche, on résout les hôtes Hyperliquid via DoH
(Cloudflare/Google) puis on se connecte normalement. Ce n'est PAS un contournement
de protection : c'est juste utiliser un résolveur DNS public au lieu d'un résolveur
local cassé (ce que font beaucoup d'apps). Aucune clé, aucun ordre, lecture seule.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.request

DOH_ENDPOINTS = (
    ("https://1.1.1.1/dns-query?type=A&name=", {"accept": "application/dns-json"}),
    ("https://dns.google/resolve?type=A&name=", {}),
)

_CACHE: dict[str, tuple[str, float]] = {}
_TTL_S = 300.0


def parse_doh_answer(data: dict) -> list[str]:
    """Extrait les IPv4 (type A = 1) d'une réponse DoH JSON. Pur, testable hors-ligne."""
    out: list[str] = []
    for ans in data.get("Answer", []) or []:
        if ans.get("type") == 1 and ans.get("data"):
            out.append(str(ans["data"]))
    return out


def resolve_via_doh(host: str, *, timeout: float = 10.0) -> str | None:
    ctx = ssl.create_default_context()
    for base, extra in DOH_ENDPOINTS:
        try:
            req = urllib.request.Request(base + host, headers={"User-Agent": "hs-doh", **extra})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                ips = parse_doh_answer(json.loads(r.read().decode()))
            if ips:
                return ips[0]
        except Exception:
            continue
    return None


def resolve(host: str, *, timeout: float = 10.0, use_cache: bool = True) -> str | None:
    """DNS système d'abord ; si échec, DoH. Renvoie une IPv4 ou None."""
    if use_cache:
        hit = _CACHE.get(host)
        if hit and (time.time() - hit[1]) < _TTL_S:
            return hit[0]
    ip: str | None = None
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        ip = resolve_via_doh(host, timeout=timeout)
    if ip and use_cache:
        _CACHE[host] = (ip, time.time())
    return ip


def system_dns_ok(host: str = "api.hyperliquid.xyz") -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


__all__ = ["parse_doh_answer", "resolve_via_doh", "resolve", "system_dns_ok"]
