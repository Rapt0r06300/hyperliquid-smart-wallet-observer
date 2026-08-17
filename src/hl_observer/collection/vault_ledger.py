"""LEDGER DES VAULTS (dépôts/retraits) via userNonFundingLedgerUpdates — rectif Flo 23/07.

POURQUOI
--------
La détection des retraits par heuristique (reduce pro-rata multi-coins simultané) est un SECOURS. La
VÉRITÉ, c'est le ledger : `userNonFundingLedgerUpdates` liste dépôts/retraits/transferts. On en tire
les HORAIRES de retrait, et on marque comme « retrait » toute réduction proche d'un retrait réel. On
ne garde l'heuristique que pour ce que le ledger ne couvre pas.

Module PUR (parsing + marquage) → testable sans réseau. Le backfill (`tools/backfill_vault_ledger.py`)
fait les appels (lecture seule). Aucun ordre, aucune clé, aucune signature.
"""
from __future__ import annotations

from typing import Any

MS_PAR_HEURE = 3_600_000


def _vault_id(value: Any) -> str:
    """Identité de jointure stable sans modifier l'affichage historique du ledger."""
    return str(value or "").strip().lower()


def parser_ledger(rep: Any, *, vault: str = "") -> list[dict]:
    """Normalise userNonFundingLedgerUpdates → mouvements de capital.

    Le champ ``vault`` conserve sa casse d'entrée pour compatibilité des rapports ;
    les jointures économiques utilisent ensuite ``_vault_id`` de façon insensible
    à la casse.
    """
    out: list[dict] = []
    vault_id = str(vault or "").strip()
    for u in (rep or []):
        try:
            ts = int(u["time"])
        except (KeyError, TypeError, ValueError):
            continue
        delta = u.get("delta") if isinstance(u, dict) else None
        delta = delta if isinstance(delta, dict) else {}
        typ = str(delta.get("type") or "").strip()
        montant = None
        for k in ("usdc", "amount", "usdcValue", "value"):
            if k in delta:
                try:
                    montant = float(delta[k])
                except (TypeError, ValueError):
                    montant = None
                break
        bas = typ.lower()
        # Capital sortant du vault : type explicite withdraw ou montant négatif.
        est_retrait = ("withdraw" in bas) or (montant is not None and montant < 0)
        out.append({"ts_ms": ts, "vault": vault_id, "type": typ,
                    "delta_usd": montant, "est_retrait": bool(est_retrait), "hash": u.get("hash")})
    return out


def horaires_retraits(ledger: list[dict]) -> dict[str, list[int]]:
    """{vault: [ts_ms de retrait triés]} depuis le ledger parsé."""
    out: dict[str, list[int]] = {}
    for m in ledger:
        if m.get("est_retrait"):
            out.setdefault(str(m.get("vault") or ""), []).append(int(m["ts_ms"]))
    for v in out:
        out[v].sort()
    return out


def _proche(ts: int, horaires: list[int], fenetre_ms: int) -> bool:
    import bisect
    if not horaires:
        return False
    i = bisect.bisect_left(horaires, ts)
    for j in (i - 1, i):
        if 0 <= j < len(horaires) and abs(horaires[j] - ts) <= fenetre_ms:
            return True
    return False


def marquer_retraits_ledger(events: list[dict], ledger: list[dict], *, fenetre_ms: int = 10 * 60_000,
                            heuristique_secours=None) -> list[dict]:
    """Marque REDUCE/CLOSE proches d'un retrait ledger réel, puis heuristique secours.

    La jointure vault est volontairement insensible à la casse : une adresse
    ``0xAB...`` du ledger et ``0xab...`` issue de la reconstruction désignent le
    même vault et ne doivent jamais être traitées comme deux identités.
    """
    horaires = horaires_retraits(ledger)
    horaires_norm: dict[str, list[int]] = {}
    for vault, timestamps in horaires.items():
        horaires_norm.setdefault(_vault_id(vault), []).extend(timestamps)
    for timestamps in horaires_norm.values():
        timestamps.sort()

    for e in events:
        e.setdefault("retrait_probable", False)
        e.setdefault("retrait_source", "")
        if e.get("action") in ("REDUCE", "CLOSE") and not e["retrait_probable"]:
            vault = _vault_id(e.get("vault"))
            if _proche(int(e["ts_ms"]), horaires_norm.get(vault, []), fenetre_ms):
                e["retrait_probable"] = True
                e["retrait_source"] = "ledger"
    if heuristique_secours is not None:
        avant = {id(e): e["retrait_probable"] for e in events}
        heuristique_secours(events)
        for e in events:
            if e["retrait_probable"] and not avant.get(id(e)) and not e.get("retrait_source"):
                e["retrait_source"] = "heuristique"
    return events


__all__ = ["parser_ledger", "horaires_retraits", "marquer_retraits_ledger", "MS_PAR_HEURE"]
