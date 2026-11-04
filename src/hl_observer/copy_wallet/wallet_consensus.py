"""C14 — CONSENSUS de wallets INDÉPENDANTS : exiger l'accord de PLUSIEURS, pas d'une baleine.

Un seul gros wallet peut se tromper — ou manipuler (afficher un signal pour piéger les suiveurs).
Exiger N wallets INDÉPENDANTS d'accord sur la même direction filtre le bruit et la manipulation.

Indépendants = adresses DISTINCTES qui ne sont PAS dans le même groupe corrélé (une même entité,
des wallets qui bougent ensemble, comptent pour UN seul).

⚠️ Honnête : la vraie indépendance demande une analyse de corrélation (à mesurer). v1 : adresses
distinctes + groupes corrélés CONNUS repliés sur un représentant. Deny-by-default : sous le quorum,
ou pas de côté dominant -> None (pas de consensus). Un consensus n'est pas un ordre. PAPER only.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

QUORUM_DEFAUT = 3          # au moins 3 wallets indépendants d'accord


def _norm_side(side: str) -> str | None:
    s = str(side or "").upper()
    if s in ("BUY", "LONG", "B"):
        return "LONG"
    if s in ("SELL", "SHORT", "S"):
        return "SHORT"
    return None


def _representant(adresse: str, groupes: Iterable[frozenset] | None) -> str:
    """Replie une adresse corrélée sur un représentant stable (le min du groupe)."""
    for g in groupes or []:
        if adresse in g:
            return min(g)
    return adresse


def consensus(
    signaux: Iterable[dict],
    *,
    min_wallets: int = QUORUM_DEFAUT,
    groupes_correles: Iterable[frozenset] | None = None,
    exiger_independance_mesuree: bool = False,
    as_of_ms: int | None = None,
) -> dict[str, Any] | None:
    """Renvoie {direction, n_independants, n_oppose} si >= min_wallets wallets INDÉPENDANTS sont
    d'accord ET dominent strictement le côté opposé. Sinon None."""
    rows = [s for s in signaux or [] if isinstance(s, dict)]
    if exiger_independance_mesuree:
        # The legacy API accepts bare address/side pairs.  That form is useful
        # for compatibility but cannot prove independence; strict mode requires
        # the existing point-in-time entity resolver and therefore abstains.
        if isinstance(as_of_ms, bool) or not isinstance(as_of_ms, int) or as_of_ms <= 0:
            return None
        # Strict mode is an evidence gate: rows without a point-in-time
        # observation, a positive size, or an explicit public entity cannot
        # participate and are rejected rather than silently dropped.
        for row in rows:
            ts_ms = row.get("ts_ms")
            if (
                not str(row.get("adresse") or "").strip()
                or not str(row.get("coin") or "").strip()
                or not str(row.get("public_entity_id") or "").strip()
                or _norm_side(row.get("side")) is None
                or isinstance(ts_ms, bool)
                or not isinstance(ts_ms, int)
                or ts_ms <= 0
            ):
                return None
            try:
                size = float(row.get("size"))
            except (TypeError, ValueError):
                return None
            if not math.isfinite(size) or size <= 0:
                return None
        from hl_observer.following.entity_consensus import infer_entity_consensus

        votes = [
            {
                "wallet": row.get("adresse"),
                "coin": row.get("coin"),
                "side": row.get("side"),
                "ts_ms": row.get("ts_ms"),
                "size": row.get("size"),
                "public_entity_id": row.get("public_entity_id"),
            }
            for row in rows
        ]
        evidence = infer_entity_consensus(votes, as_of_ms=as_of_ms)
        if evidence.get("independence_measurable") is not True:
            return None
        representatives = {
            str(wallet).strip(): str(cluster.get("cluster_id"))
            for cluster in evidence.get("clusters", [])
            for wallet in cluster.get("wallets", [])
        }
        groupes_correles = [
            frozenset(str(wallet).strip() for wallet in cluster.get("wallets", []))
            for cluster in evidence.get("clusters", [])
        ]
        rows = [row for row in rows if row["ts_ms"] <= as_of_ms]
    else:
        representatives = {}

    par_side: dict[str, set] = {"LONG": set(), "SHORT": set()}
    for s in rows:
        if not isinstance(s, dict):
            continue
        side = _norm_side(s.get("side"))
        adr = str(s.get("adresse") or "")
        if side is None or not adr:
            continue
        par_side[side].add(representatives.get(adr, _representant(adr, groupes_correles)))
    n_long, n_short = len(par_side["LONG"]), len(par_side["SHORT"])
    if n_long == n_short:
        return None                                   # égalité -> pas de côté net
    gagnant, n, n_opp = ("LONG", n_long, n_short) if n_long > n_short else ("SHORT", n_short, n_long)
    if n >= int(min_wallets):
        return {"direction": gagnant, "n_independants": n, "n_oppose": n_opp}
    return None


__all__ = ["QUORUM_DEFAUT", "consensus"]
