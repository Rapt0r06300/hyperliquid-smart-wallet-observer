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


def parser_ledger(rep: Any, *, vault: str = "") -> list[dict]:
    """Normalise userNonFundingLedgerUpdates → mouvements {ts_ms, vault, type, delta_usd (signé),
    est_retrait}. Format HL : [{"time":.., "hash":.., "delta":{"type":"withdraw"/"deposit"/
    "vaultWithdraw"/..., "usdc"/"amount":..}}]. Illisible → ignoré (jamais inventé)."""
    out: list[dict] = []
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
        # un retrait = capital qui SORT du vault (type 'withdraw'/'vaultWithdraw' ou montant négatif)
        est_retrait = ("withdraw" in bas) or (montant is not None and montant < 0)
        out.append({"ts_ms": ts, "vault": vault, "type": typ,
                    "delta_usd": montant, "est_retrait": bool(est_retrait), "hash": u.get("hash")})
    return out


def horaires_retraits(ledger: list[dict]) -> dict[str, list[int]]:
    """{vault: [ts_ms de retrait triés]} depuis le ledger parsé."""
    out: dict[str, list[int]] = {}
    for m in ledger:
        if m.get("est_retrait"):
            out.setdefault(m.get("vault", ""), []).append(int(m["ts_ms"]))
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
    """Marque `retrait_probable=True` (source='ledger') les REDUCE/CLOSE proches d'un retrait RÉEL du
    ledger. Puis, en SECOURS uniquement, applique l'heuristique pro-rata sur ce qui n'est pas déjà
    marqué (source='heuristique'). En place. Rend `events`."""
    horaires = horaires_retraits(ledger)
    for e in events:
        e.setdefault("retrait_probable", False)
        e.setdefault("retrait_source", "")
        if e.get("action") in ("REDUCE", "CLOSE") and not e["retrait_probable"]:
            if _proche(int(e["ts_ms"]), horaires.get(e.get("vault", ""), []), fenetre_ms):
                e["retrait_probable"] = True
                e["retrait_source"] = "ledger"
    if heuristique_secours is not None:
        avant = {id(e): e["retrait_probable"] for e in events}
        heuristique_secours(events)                               # marque d'autres retraits (pro-rata)
        for e in events:
            if e["retrait_probable"] and not avant.get(id(e)) and not e.get("retrait_source"):
                e["retrait_source"] = "heuristique"
    return events


__all__ = ["parser_ledger", "horaires_retraits", "marquer_retraits_ledger", "MS_PAR_HEURE"]
