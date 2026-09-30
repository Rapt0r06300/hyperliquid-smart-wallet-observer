"""CHANTIER — REJOUER Wallet×Binance sur une GRANDE population (débloqué par les collecteurs #64/#65).

Rejoue l'expérience d'anticipation (research.wallet_binance_anticipation) sur la population LARGE issue du
backfill (leader_fills) croisée avec la série Binance (bbo_synchro), AVEC la discipline anti-sur-ajustement :
tester des MILLIERS de wallets est une énorme surface de multiple-testing. Un « gagnant parmi le bruit » est
donc DÉFLATÉ par le Deflated Sharpe sur `n_essais = nombre de wallets mesurés` (réutilise FIX-36
backtesting.anti_overfit_gate) ; seuls les anticipateurs qui SURVIVENT à la déflation sont conservés.

Sans les fichiers réels (produits par les collecteurs côté machine Flo) → BLOCKED_EXTERNAL, aucun wallet
fabriqué. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import os
from typing import Any

from hl_observer.backtesting import anti_overfit_gate as _aog
from hl_observer.research import wallet_binance_anticipation as _wba

BLOCKED = "BLOCKED_EXTERNAL"
_PROMOUVABLE = "ANTICIPATEUR_A_FORWARD"


def _sharpes(classement: list[dict[str, Any]]) -> list[float]:
    out = []
    for v in classement:
        votes = v.get("votes_net_oos")
        if votes and len(votes) >= 2:
            s = _aog.sharpe(votes)
            if isinstance(s, (int, float)):
                out.append(s)
    return out


def rejouer_wallet_binance(fills_path: str, bbo_path: str, *, horizon_ms: int = 5000, cout_bps: float = 9.0,
                           min_fills_wallet: int = 8, coins: set[str] | None = None,
                           max_lignes: int = 2_000_000, top_n: int = 20) -> dict[str, Any]:
    """Rejoue l'anticipation sur toute la population puis DÉFLATE par le nombre de wallets testés (multiple-testing).
    Retourne le classement dé-promu et le nombre d'anticipateurs SURVIVANTS à la déflation."""
    if not (fills_path and bbo_path and os.path.exists(fills_path) and os.path.exists(bbo_path)):
        return {"statut": BLOCKED, "manque": "leader_fills (backfill #65) + bbo_synchro (recorder #64) cote user",
                "real_execution": False}
    fills = _wba.charger_fills(fills_path)
    univers = coins or {f.get("coin") for f in fills if f.get("coin")}
    bin_by_coin = _wba.charger_bin_series(bbo_path, set(univers), max_lignes=max_lignes)
    r = _wba.experience_anticipation(fills, bin_by_coin, horizon_ms=horizon_ms, cout_bps=cout_bps,
                                     min_fills_wallet=min_fills_wallet)
    classement = r["classement"]
    n_essais = max(1, r["n_wallets_mesures"])            # surface de multiple-testing = wallets réellement mesurés
    trial_sharpes = _sharpes(classement)
    n_survivants = 0
    for v in classement:
        votes = v.get("votes_net_oos")
        if v.get("verdict") == _PROMOUVABLE and votes:
            av = _aog.evaluer(votes, n_essais=n_essais, trial_sharpes=trial_sharpes)
            v["proba_deflatee"] = round(av.proba_deflatee, 6)
            if av.motif == _aog.MOTIF_NOISE:             # gagnant parmi le bruit -> dé-promu (jamais un faux champion)
                v["verdict"] = "MORE_DATA"
                v["notes"] = ("anti-overfit: DSR bruit apres deflation par %d essais" % n_essais)
            else:
                n_survivants += 1
    classement.sort(key=lambda l: ({"ANTICIPATEUR_A_FORWARD": 0, "MORE_DATA": 1, "KILL": 2,
                                     "KILL_FOLLOWER": 3}.get(l["verdict"], 9),
                                    -(l.get("proba_deflatee") or 0.0), -(l.get("lcb_net_bps") or -1e9)))
    return {"statut": "OK", "n_wallets": r["n_wallets_mesures"], "n_essais": n_essais,
            "n_anticipateurs_survivants": n_survivants, "horizon_ms": horizon_ms, "cout_bps": cout_bps,
            "top": classement[:top_n], "real_execution": False}


__all__ = ["rejouer_wallet_binance", "BLOCKED"]
