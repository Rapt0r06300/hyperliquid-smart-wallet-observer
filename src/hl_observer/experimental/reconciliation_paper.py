"""RÉCONCILIATION DÉTERMINISTE du livre EXPERIMENTAL_PAPER (LOT14 #8, Flo 26/07).

Prouve, pour chaque position et au total : OPEN + REDUCE éventuels + CLOSE == ledger == store == statut ==
rapport/dashboard, à TOLÉRANCE 0,01 USD près par position. Un écart au-delà = ANOMALIE (le PnL affiché ne
serait plus interprétable). Cœur PUR (prend les lignes déjà lues). 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections import defaultdict

TOLERANCE_USD = 0.01


def _cle(r: dict) -> str:
    """Clé d'ÉPISODE : position_id UNIQUE (P9) si présent, sinon repli moteur:coin (legacy). La clé
    moteur:coin mélangeait des épisodes successifs sur le même coin -> le position_id les sépare."""
    pid = r.get("position_id")
    if pid:
        return str(pid)
    return "%s:%s" % (r.get("strategie") or r.get("moteur") or "?", str(r.get("coin") or "?").upper())


def realized_par_position(ledger_lignes: list[dict]) -> dict:
    """Somme, par ÉPISODE (position_id), du realized des CLOSE + REDUCE. Rend {cle: realized_usd}."""
    par = defaultdict(float)
    for r in ledger_lignes:
        if r.get("kind") in ("CLOSE", "REDUCE") or r.get("evt") in ("CLOSE", "REDUCE"):
            v = r.get("realized_net_pnl_usdc")
            if v is None:
                v = r.get("realized_usd")
            par[_cle(r)] += float(v or 0.0)
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


def auditer_position(ledger_lignes: list[dict], position_id: str, *, notional_initial_usd: float,
                     notional_residuel_store_usd: float = 0.0, tolerance_usd: float = TOLERANCE_USD) -> dict:
    """Réconcilie UN ÉPISODE (par position_id, P9). CONSERVATION du notionnel :
        initial == somme(notional_ferme des REDUCE+CLOSE) + résidu réel encore ouvert dans le store.
    Un CLOSE final laisse résidu 0 ; sans CLOSE, le résidu ouvert du store doit boucler l'égalité.
    Réconcilie AUSSI le realized (somme des tranches). Le critère est une VRAIE comparaison au résidu
    attendu (remplace l'ancien `residuel >= -tolerance` qui ne validait presque rien)."""
    ferme = 0.0
    realized = 0.0
    a_close = False
    for r in ledger_lignes:
        if _cle(r) != str(position_id):
            continue
        k = r.get("kind") or r.get("evt")
        if k == "REDUCE":
            ferme += float(r.get("notional_ferme_usd") or 0.0)
            realized += float(r.get("realized_net_pnl_usdc") or r.get("realized_usd") or 0.0)
        elif k == "CLOSE":
            a_close = True
            ferme += float(r.get("notional_ferme_usd") or 0.0)
            realized += float(r.get("realized_net_pnl_usdc") or r.get("realized_usd") or 0.0)
    residuel_attendu = 0.0 if a_close else float(notional_residuel_store_usd)
    ecart = abs(float(notional_initial_usd) - (ferme + residuel_attendu))
    return {"position_id": str(position_id), "realized_usd": round(realized, 6),
            "notional_ferme_usd": round(ferme, 6), "notional_residuel_attendu_usd": round(residuel_attendu, 6),
            "ecart_conservation_usd": round(ecart, 6),
            "coherent": ecart <= max(tolerance_usd, 1e-6)}


__all__ = ["realized_par_position", "auditer", "auditer_position", "TOLERANCE_USD"]
