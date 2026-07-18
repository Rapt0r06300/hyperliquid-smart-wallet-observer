"""P1 — ATTRIBUTION DU PnL : quelle stratégie / coin / signal gagne ou perd.

Sans attribution on ne sait pas quoi COUPER ni quoi SCALER. On regroupe le PnL réalisé par une clé
(strategie, coin, signal…) depuis le ledger. PUR. Lit un ledger, n'invente rien. PAPER only.
"""
from __future__ import annotations

from typing import Iterable


def attribution(evenements: Iterable[dict], *, cle: str = "coin") -> dict[str, float]:
    """Somme le PnL réalisé par valeur de `cle`. Ignore les lignes sans PnL (ouvertures)."""
    out: dict[str, float] = {}
    for e in evenements or []:
        if not isinstance(e, dict):
            continue
        pnl = e.get("realized_net_pnl_usdc")
        if pnl is None:
            continue
        k = str(e.get(cle) or "?")
        try:
            out[k] = out.get(k, 0.0) + float(pnl)
        except (TypeError, ValueError):
            continue
    return {k: round(v, 6) for k, v in out.items()}


def gagnants_perdants(evenements: Iterable[dict], *, cle: str = "coin") -> dict:
    """Trie l'attribution en gagnants / perdants (pour savoir quoi scaler / couper)."""
    a = attribution(evenements, cle=cle)
    return {"gagnants": {k: v for k, v in sorted(a.items(), key=lambda kv: -kv[1]) if v > 0},
            "perdants": {k: v for k, v in sorted(a.items(), key=lambda kv: kv[1]) if v < 0}}


__all__ = ["attribution", "gagnants_perdants"]
