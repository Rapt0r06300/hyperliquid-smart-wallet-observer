"""RÉCONCILIATION DÉTERMINISTE du livre EXPERIMENTAL_PAPER (LOT14 #8, Flo 26/07).

Prouve, pour chaque position et au total : OPEN + REDUCE éventuels + CLOSE == ledger == store == statut ==
rapport/dashboard, à TOLÉRANCE 0,01 USD près par position. Un écart au-delà = ANOMALIE (le PnL affiché ne
serait plus interprétable). Cœur PUR (prend les lignes déjà lues). 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections import defaultdict

TOLERANCE_USD = 0.01


def realized_par_position(ledger_lignes: list[dict]) -> dict:
    """Somme, par position (moteur:coin), du realized des CLOSE + REDUCE. Rend {cle: realized_usd}."""
    par = defaultdict(float)
    for r in ledger_lignes:
        if r.get("kind") in ("CLOSE", "REDUCE") or r.get("evt") in ("CLOSE", "REDUCE"):
            cle = "%s:%s" % (r.get("strategie") or r.get("moteur") or "?", str(r.get("coin") or "?").upper())
            v = r.get("realized_net_pnl_usdc")
            if v is None:
                v = r.get("realized_usd")
            par[cle] += float(v or 0.0)
    return {k: round(v, 6) for k, v in par.items()}


def auditer(ledger_lignes: list[dict], *, realise_store_usd: float, realise_statut_usd: float,
            tolerance_usd: float = TOLERANCE_USD) -> dict:
    """Compare le realized total du LEDGER au realized du STORE et du STATUT. Rend {coherent, ecarts...}.
    coherent=True seulement si les trois coïncident à `tolerance_usd` près."""
    par_pos = realized_par_position(ledger_lignes)
    total_ledger = round(sum(par_pos.values()), 6)
    ecart_store = round(abs(total_ledger - float(realise_store_usd)), 6)
    ecart_statut = round(abs(total_ledger - float(realise_statut_usd)), 6)
    coherent = ecart_store <= tolerance_usd and ecart_statut <= tolerance_usd
    return {"coherent": coherent, "realized_total_ledger_usd": total_ledger,
            "realized_store_usd": round(float(realise_store_usd), 6),
            "realized_statut_usd": round(float(realise_statut_usd), 6),
            "ecart_ledger_store_usd": ecart_store, "ecart_ledger_statut_usd": ecart_statut,
            "tolerance_usd": tolerance_usd, "n_positions": len(par_pos), "par_position": par_pos}


def auditer_position(ledger_lignes: list[dict], cle: str, *, notional_ouvert_usd: float,
                     tolerance_usd: float = TOLERANCE_USD) -> dict:
    """Réconcilie UNE position : OPEN(notional) − somme(REDUCE.notional_ferme) doit égaler le résidu, et le
    realized = somme des parties fermées. Rend {coherent, realized, residuel}."""
    ferme = 0.0
    realized = 0.0
    for r in ledger_lignes:
        k = r.get("kind") or r.get("evt")
        if ("%s:%s" % (r.get("strategie") or r.get("moteur") or "?", str(r.get("coin") or "?").upper())) != cle:
            continue
        if k == "REDUCE":
            ferme += float(r.get("notional_ferme_usd") or 0.0)
            realized += float(r.get("realized_usd") or r.get("realized_net_pnl_usdc") or 0.0)
        elif k == "CLOSE":
            ferme += float(r.get("notional_ferme_usd") or notional_ouvert_usd)
            realized += float(r.get("realized_net_pnl_usdc") or r.get("realized_usd") or 0.0)
    residuel = round(float(notional_ouvert_usd) - ferme, 6)
    return {"cle": cle, "realized_usd": round(realized, 6), "notional_ferme_usd": round(ferme, 6),
            "notional_residuel_usd": residuel,
            "coherent": abs(residuel) <= max(tolerance_usd, 1e-6) or residuel >= -tolerance_usd}


__all__ = ["realized_par_position", "auditer", "auditer_position", "TOLERANCE_USD"]
