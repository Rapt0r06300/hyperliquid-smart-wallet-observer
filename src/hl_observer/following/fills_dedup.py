"""V3 §2.3 — Déduplication multi-source + FUSION des champs autoritatifs (pur, 0 réseau).

`fills_sources` normalise chaque schéma vers le contrat unique ; il ne fusionne PAS entre sources.
Or le même fill peut arriver par plusieurs collecteurs, chacun portant un champ que l'autre n'a pas
(l'un a `start_pos`, l'autre `fee`/`receive_ts`). Jeter aveuglément la 2ᵉ occurrence perd de
l'information ; garder « la première vue » est arbitraire. Ce module, en pur et testable :

  * dédup par clé canonique : `tid` en priorité, sinon empreinte causale (user, coin, time, sz, px, sens) ;
  * FUSIONNE les champs complémentaires (union), en préférant la source la plus AUTORITATIVE puis la plus
    RICHE pour tout champ scalaire présent des deux côtés ;
  * détecte une COLLISION divergente (même clé, identité incompatible : user/coin/sz/px/sens différents)
    → `DUPLICATE_CONFLICT` : la promotion est bloquée, on ne devine pas laquelle est vraie.

Deny-by-default : en cas de conflit, on garde la trace, on ne fusionne pas, on n'invente rien.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "hypersmart.fills_dedup.v1"

#: Champs dont une divergence entre deux occurrences de MÊME clé est un vrai conflit d'identité.
CHAMPS_IDENTITE = ("user", "coin", "sz", "px", "side", "dir", "start_pos")

#: Champs complémentaires : une occurrence peut les porter, l'autre non — fusion sans conflit.
CHAMPS_COMPLEMENTAIRES = ("start_pos", "oid", "tid", "twap_id", "receive_ts_ms", "fee", "fee_usd")

_TOL = 1e-9


def cle_canonique(fill: Mapping[str, Any]) -> tuple:
    """Clé de dédup : `tid` si présent, sinon empreinte causale. Jamais l'ordre d'arrivée."""
    tid = fill.get("tid")
    if tid not in (None, ""):
        return ("tid", str(tid))
    sens = fill.get("side")
    if sens in (None, ""):
        sens = fill.get("dir")
    return ("emp", str(fill.get("user")), str(fill.get("coin")), int(float(fill.get("time") or 0)),
            round(float(fill.get("sz") or 0.0), 10), round(float(fill.get("px") or 0.0), 10), str(sens))


def _rang_source(fill: Mapping[str, Any]) -> tuple:
    """Préférence pour trancher un scalaire présent des deux côtés : autoritative, puis la plus riche."""
    autoritative = 1 if fill.get("autoritative") else 0
    richesse = sum(1 for c in CHAMPS_COMPLEMENTAIRES if fill.get(c) not in (None, ""))
    return (autoritative, richesse)


def _divergence(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    """Champs d'identité présents des DEUX côtés avec des valeurs incompatibles."""
    diff: list[str] = []
    for c in CHAMPS_IDENTITE:
        va, vb = a.get(c), b.get(c)
        if va in (None, "") or vb in (None, ""):
            continue
        if c in ("sz", "px", "start_pos"):
            try:
                if abs(float(va) - float(vb)) > _TOL:
                    diff.append(c)
            except (TypeError, ValueError):
                if str(va) != str(vb):
                    diff.append(c)
        elif str(va).strip().lower() != str(vb).strip().lower():
            diff.append(c)
    return diff


def _fusionner(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """Fusionne deux occurrences NON divergentes. Le scalaire gagnant vient de la source préférée ;
    les champs manquants sont complétés par l'autre. Trace les sources fusionnées."""
    prefere, autre = (a, b) if _rang_source(a) >= _rang_source(b) else (b, a)
    fusion = dict(prefere)
    for cle, val in autre.items():
        if val in (None, ""):
            continue
        if fusion.get(cle) in (None, ""):
            fusion[cle] = val
    srcs = sorted({str(a.get("source")), str(b.get("source"))} - {"None", ""})
    if srcs:
        fusion["fusion_sources"] = srcs
    fusion["autoritative"] = bool(a.get("autoritative")) or bool(b.get("autoritative"))
    return fusion


@dataclass
class ResultatDedup:
    fills: list[dict[str, Any]] = field(default_factory=list)
    n_entree: int = 0
    n_uniques: int = 0
    n_fusionnes: int = 0
    conflits: list[dict[str, Any]] = field(default_factory=list)

    def resume(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "n_entree": self.n_entree, "n_uniques": self.n_uniques,
                "n_fusionnes": self.n_fusionnes, "n_conflits": len(self.conflits),
                "conflits": self.conflits[:50], "real_execution": False}


def dedup_merge(fills: Iterable[Mapping[str, Any]]) -> ResultatDedup:
    """Dédup + fusion multi-source. Un conflit divergent NE fusionne pas et bloque la promotion (compté).

    L'ordre de sortie est déterministe (ordre de première apparition de chaque clé retenue).
    """
    res = ResultatDedup()
    par_cle: dict[tuple, dict[str, Any]] = {}
    ordre: list[tuple] = []
    bloques: set[tuple] = set()
    for brut in fills:
        res.n_entree += 1
        f = dict(brut)
        cle = cle_canonique(f)
        if cle in bloques:
            continue                                    # clé déjà en conflit : plus rien ne s'y promeut
        existe = par_cle.get(cle)
        if existe is None:
            par_cle[cle] = f
            ordre.append(cle)
            continue
        diff = _divergence(existe, f)
        if diff:
            res.conflits.append({"cle": list(cle), "champs_divergents": diff,
                                 "sources": sorted({str(existe.get("source")), str(f.get("source"))})})
            bloques.add(cle)
            par_cle.pop(cle, None)                       # deny-by-default : occurrence ambiguë retirée
            continue
        par_cle[cle] = _fusionner(existe, f)
        res.n_fusionnes += 1
    res.fills = [par_cle[c] for c in ordre if c in par_cle]
    res.n_uniques = len(res.fills)
    return res


__all__ = ["SCHEMA_VERSION", "CHAMPS_IDENTITE", "CHAMPS_COMPLEMENTAIRES", "cle_canonique",
           "dedup_merge", "ResultatDedup"]
