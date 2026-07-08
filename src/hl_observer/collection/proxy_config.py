"""Chaînon manquant proxy: lit les proxies depuis l'env et les fait tourner.

Le `proxy_pool` existant ne fait que PLANIFIER (santé, sharding) — il ne branche
rien aux clients HTTP. Ici on comble le trou: on lit `HYPERSMART_HTTP_PROXIES`
(liste séparée par des virgules, ex. proxies Webshare gratuits), on construit des
ProxyEndpoint, et on renvoie une URL de proxy par rotation round-robin sur les
endpoints SAINS. Aucun proxy configuré => None => sortie directe (défaut sûr).

Anti-ban: chaque IP multiplie le budget de poids REST (1200/min/IP). 10 proxies
Webshare gratuits => ~12 000 poids/min. Lecture seule, données publiques.
Aucune exécution réelle.
"""

from __future__ import annotations

import os
from itertools import cycle

from hl_observer.collection.proxy_pool import ProxyEndpoint

ENV_VAR = "HYPERSMART_HTTP_PROXIES"


def parse_proxies(raw: str | None) -> list[ProxyEndpoint]:
    """Parse une liste de proxies séparés par des virgules (ou retours ligne).

    Formats acceptés: `http://user:pass@ip:port`, `http://ip:port`, `ip:port`
    (préfixé http:// par défaut). Vide/blanc => liste vide (sortie directe).
    """
    if not raw:
        return []
    parts = [p.strip() for chunk in str(raw).split(",") for p in chunk.splitlines()]
    endpoints: list[ProxyEndpoint] = []
    for i, p in enumerate(parts):
        if not p:
            continue
        url = p if "://" in p else f"http://{p}"
        endpoints.append(ProxyEndpoint(endpoint_id=f"proxy-{i}", label=f"egress-{i}", url=url))
    return endpoints


def load_proxies(env: dict | None = None) -> list[ProxyEndpoint]:
    e = env if env is not None else os.environ
    return parse_proxies(e.get(ENV_VAR))


class ProxyRotator:
    """Round-robin sur les endpoints SAINS. `next_url()` -> str|None (None=direct)."""

    def __init__(self, endpoints: list[ProxyEndpoint] | None = None):
        self._endpoints = list(endpoints or [])
        self._cycle = cycle(self._endpoints) if self._endpoints else None

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ProxyRotator":
        return cls(load_proxies(env))

    @property
    def enabled(self) -> bool:
        return any(ep.is_healthy for ep in self._endpoints)

    def egress_count(self) -> int:
        """Nb d'IP saines = multiplicateur du budget de poids REST."""
        return sum(1 for ep in self._endpoints if ep.is_healthy)

    def next_url(self) -> str | None:
        if not self._cycle:
            return None
        healthy = [ep for ep in self._endpoints if ep.is_healthy]
        if not healthy:
            return None                       # tous morts => direct plutôt que rien
        # avance dans le cycle jusqu'à tomber sur un sain (borné au nb d'endpoints)
        for _ in range(len(self._endpoints)):
            ep = next(self._cycle)
            if ep.is_healthy:
                return ep.url
        return healthy[0].url


__all__ = ["parse_proxies", "load_proxies", "ProxyRotator", "ENV_VAR"]
