"""BACKTEST CARRY SUR FUNDING HISTORIQUE (idées #3/#4) — rejouer le carry sur des MOIS de funding
réel (fundingHistory / candleSnapshot), sans attendre. Mesure le PnL cumulé (funding encaissé −
coût d'entrée) et balaie le levier pour trouver la meilleure config. Pur ; l'appelant fournit la
série (fetch sur Windows). Ne PROMET rien : métriques descriptives. PAPER only, aucun ordre.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultatBacktestCarry:
    coin: str
    heures: int
    funding_cumule_bps: float
    cout_entree_bps: float
    pnl_net_bps: float
    break_even_h: int | None
    positif: bool

    def as_dict(self) -> dict:
        return {"coin": self.coin, "heures": self.heures, "funding_cumule_bps": self.funding_cumule_bps,
                "cout_entree_bps": self.cout_entree_bps, "pnl_net_bps": self.pnl_net_bps,
                "break_even_h": self.break_even_h, "positif": self.positif,
                "promesse": "aucune - descriptif", "real_execution": False}


def simuler_carry(coin: str, funding_serie_bps_h: list[float], cout_entree_bps: float) -> ResultatBacktestCarry:
    """Encaisse le funding heure par heure (on est short le perp -> on reçoit |funding| du bon côté),
    moins le coût d'entrée payé une fois. Série vide -> PnL 0 non positif."""
    serie = [float(f) for f in (funding_serie_bps_h or []) if isinstance(f, (int, float))]
    cumule = 0.0
    break_even = None
    for h, f in enumerate(serie, start=1):
        cumule += abs(f)                                  # funding encaissé (du bon côté), horaire
        if break_even is None and cumule >= float(cout_entree_bps):
            break_even = h
    pnl = cumule - float(cout_entree_bps)
    return ResultatBacktestCarry(str(coin).upper(), len(serie), round(cumule, 4),
                                 float(cout_entree_bps), round(pnl, 4), break_even, pnl > 0)


def balayer_levier(coin: str, funding_serie_bps_h: list[float], couts_par_levier: dict[float, float]) -> dict:
    """#4 : rejoue le carry pour chaque (levier -> coût d'entrée) et renvoie le meilleur PnL net.
    Le coût dépend du levier (plus de notional = plus de frais). Renvoie {levier: pnl_net_bps, best}."""
    par_levier = {}
    for lev, cout in (couts_par_levier or {}).items():
        r = simuler_carry(coin, funding_serie_bps_h, cout)
        par_levier[float(lev)] = r.pnl_net_bps
    best = max(par_levier, key=lambda k: par_levier[k]) if par_levier else None
    return {"par_levier": par_levier, "meilleur_levier": best,
            "meilleur_pnl_bps": par_levier[best] if best is not None else None}


__all__ = ["ResultatBacktestCarry", "simuler_carry", "balayer_levier"]
