"""Univers officiel des marchés perpétuels Hyperliquid (dex principal + dex HIP-3).

POURQUOI. Vérifié auprès de l'API officielle le 2026-11-11 :

* l'identifiant d'un marché est sensible à la casse et, pour un dex HIP-3, porte le préfixe du
  dex en minuscules : ``xyz:XYZ100``, ``km:US500``, ``kPEPE``. ``XYZ:XYZ100``, ``xyz:xyz100`` ou
  ``KPEPE`` sont refusés (HTTP 500 sur ``l2Book``) ;
* sur le WebSocket, UN SEUL abonnement à un marché inconnu fait fermer TOUTE la connexion par
  le serveur : les dizaines d'autres marchés groupés sur cette connexion ne reçoivent plus rien.

Un collecteur ne doit donc jamais s'abonner à un nom qu'il n'a pas vérifié. Ce module donne la
liste officielle (``meta`` du dex principal, ``perpDexs``, puis ``meta`` de chaque dex), la met
en cache, et sépare une liste demandée en marchés abonnables et marchés inconnus (signalés,
jamais abonnés). Lecture seule : endpoint public ``/info``, aucun ordre, aucune clé.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.ops.echec_silencieux import noter as _noter_echec

URL_INFO = "https://api.hyperliquid.xyz/info"
CACHE_DEFAUT = Path("runtime") / "data" / "hl_univers_perps.json"
CACHE_MAX_AGE_S = 6 * 3600.0
SCHEMA = "hypersmart.hl_univers_perps.v1"


def poster_info(charge: Mapping[str, Any], *, timeout_s: float = 12.0) -> Any:
    """Requête publique ``/info`` (lecture seule)."""
    corps = json.dumps(dict(charge)).encode("utf-8")
    req = urllib.request.Request(URL_INFO, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def noms_depuis_meta(meta: Any) -> list[str]:
    """Noms des marchés cotés d'une réponse ``meta`` (les marchés retirés de la cote sont exclus)."""
    univers = meta.get("universe") if isinstance(meta, Mapping) else None
    noms: list[str] = []
    for marche in univers if isinstance(univers, list) else ():
        if not isinstance(marche, Mapping) or marche.get("isDelisted") is True:
            continue
        nom = preserve_native_instrument_symbol(marche.get("name"))
        if nom:
            noms.append(nom)
    return noms


def noms_des_dexs(perp_dexs: Any) -> list[str]:
    """Noms des dex HIP-3 d'une réponse ``perpDexs`` (l'entrée ``null`` est le dex principal)."""
    return [str(dex["name"]) for dex in perp_dexs if isinstance(dex, Mapping) and dex.get("name")] \
        if isinstance(perp_dexs, list) else []


def interroger_univers(post: Callable[[Mapping[str, Any]], Any] = poster_info) -> dict[str, list[str]]:
    """``{dex: [marchés]}`` ; le dex principal porte la clé ``""``. Un dex illisible est omis."""
    par_dex: dict[str, list[str]] = {}
    principal = noms_depuis_meta(post({"type": "meta"}))
    if principal:
        par_dex[""] = principal
    for dex in noms_des_dexs(post({"type": "perpDexs"})):
        try:
            noms = noms_depuis_meta(post({"type": "meta", "dex": dex}))
        except (OSError, ValueError):
            continue
        if noms:
            par_dex[dex] = noms
    return par_dex


def charger_univers(
    root: str | Path, *, post: Callable[[Mapping[str, Any]], Any] = poster_info,
    now: float | None = None, max_age_s: float = CACHE_MAX_AGE_S, cache: Path = CACHE_DEFAUT,
) -> set[str] | None:
    """Ensemble des marchés officiels, depuis le cache s'il est récent, sinon depuis l'API.

    Réseau indisponible : le dernier cache connu est rendu, même ancien (un univers d'hier vaut
    mieux qu'aucune vérification). Ni réseau ni cache : ``None`` — l'appelant sait alors qu'il n'a
    PAS pu vérifier, il ne doit pas confondre avec un univers vide.
    """
    t = time.time() if now is None else now
    chemin = Path(root) / cache
    ancien: dict[str, Any] | None = None
    try:
        lu = json.loads(chemin.read_text(encoding="utf-8"))
        if isinstance(lu, dict) and lu.get("schema") == SCHEMA and isinstance(lu.get("par_dex"), dict):
            ancien = lu
    except (OSError, ValueError):
        ancien = None
    if ancien is not None and t * 1000 - float(ancien.get("maj_ms") or 0) <= max_age_s * 1000:
        return {nom for noms in ancien["par_dex"].values() for nom in noms}
    try:
        par_dex = interroger_univers(post)
    except (OSError, ValueError):
        par_dex = {}
    if par_dex.get(""):                      # sans le dex principal, la réponse n'est pas fiable
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            temporaire = chemin.with_name(chemin.name + ".partial")
            temporaire.write_text(json.dumps(
                {"schema": SCHEMA, "maj_ms": int(t * 1000), "par_dex": par_dex,
                 "source": "hyperliquid:/info:meta+perpDexs", "read_only": True},
                ensure_ascii=False), encoding="utf-8")
            temporaire.replace(chemin)
        except OSError as exc:
            # cache non écrit : l'univers vient d'être lu, il reste utilisable ; la panne est comptée
            _noter_echec("collection/univers_perps.py:ecriture_du_cache", exc)
        return {nom for noms in par_dex.values() for nom in noms}
    if ancien is not None:
        return {nom for noms in ancien["par_dex"].values() for nom in noms}
    return None


def filtrer_abonnables(coins: Iterable[Any], univers: set[str] | None) -> tuple[list[str], list[str]]:
    """``(abonnables, inconnus)``, ordre conservé, sans doublon, identité native intacte.

    ``univers`` à ``None`` (vérification impossible) : tout est rendu abonnable, rien n'est
    déclaré inconnu — on ne rejette jamais un marché sur la foi d'une vérification qui n'a pas eu lieu.
    """
    vus: dict[str, None] = {}
    for coin in coins:
        nom = preserve_native_instrument_symbol(coin)
        if nom:
            vus.setdefault(nom, None)
    if univers is None:
        return list(vus), []
    return [nom for nom in vus if nom in univers], [nom for nom in vus if nom not in univers]


__all__ = [
    "CACHE_DEFAUT", "CACHE_MAX_AGE_S", "charger_univers", "filtrer_abonnables", "interroger_univers",
    "noms_depuis_meta", "noms_des_dexs", "poster_info",
]
