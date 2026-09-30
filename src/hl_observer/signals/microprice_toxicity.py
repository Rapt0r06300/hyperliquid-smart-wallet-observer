"""Distillation HFT (hftbacktest, market-making pro): microprice + markout/toxicité.

Attaque le tueur n°1 du grinder — l'adverse selection ("être la liquidité de sortie"):
  - MICROPRICE (VAMP): fair value pondérée par la profondeur du carnet, penche vers
    le côté fin (là où le prix va) → meilleure estimation d'entrée que le mid brut.
  - MARKOUT: après un fill, mesure combien le prix a bougé CONTRE nous (bps signés).
    Négatif = on s'est fait picker (adverse). C'est la mesure quantitative du "toxic flow".
  - TOXICITÉ (EWMA par coin): si un marché nous picke sans cesse, on RELÈVE l'edge
    requis / on l'évite. δ = base + c_vol·σ + c_tox·toxicité (discipline market-making).
Pur, déterministe. Aucune donnée inventée.
"""

from __future__ import annotations


def microprice(bid: float, ask: float, bid_size: float, ask_size: float) -> float:
    """Fair value pondérée: P = (bid·Qask + ask·Qbid)/(Qbid+Qask).

    Déséquilibre vers les BIDS (Qbid grand) → microprice tend vers l'ASK (prix va monter).
    """
    b, a = float(bid), float(ask)
    qb, qa = max(0.0, float(bid_size)), max(0.0, float(ask_size))
    if b <= 0 or a <= 0 or (qb + qa) <= 0:
        return round((b + a) / 2.0, 10) if (b > 0 and a > 0) else 0.0
    return round((b * qa + a * qb) / (qb + qa), 10)


def markout_bps(side: str, entry_price: float, mark_after: float) -> float:
    """Mouvement du prix APRÈS l'entrée, en bps, du point de vue du trade.

    LONG: positif si le prix monte (favorable). SHORT: positif si le prix baisse.
    Négatif = adverse selection (on s'est fait picker).
    """
    e = float(entry_price)
    if e <= 0:
        return 0.0
    move = (float(mark_after) - e) / e * 10_000.0
    return round(move if str(side).upper() == "LONG" else -move, 4)


class ToxicityTracker:
    """EWMA de l'adverse selection (markout négatif) par coin."""

    def __init__(self, alpha: float = 0.2) -> None:
        self.alpha = float(alpha)
        self._tox: dict[str, float] = {}

    def record_markout(self, coin: str, markout_bps_value: float) -> float:
        """Nourrit la toxicité: seule la part ADVERSE (markout < 0) compte, en valeur absolue."""
        adverse = max(0.0, -float(markout_bps_value))
        key = str(coin).upper()
        prev = self._tox.get(key)
        self._tox[key] = adverse if prev is None else round(self.alpha * adverse + (1 - self.alpha) * prev, 6)
        return self._tox[key]

    def toxicity(self, coin: str) -> float:
        return self._tox.get(str(coin).upper(), 0.0)


def toxicity_adjusted_min_edge_bps(
    base_min_edge_bps: float, *, volatility_bps: float = 0.0, toxicity_bps: float = 0.0,
    c_vol: float = 0.5, c_tox: float = 1.0,
) -> float:
    """Edge minimum requis relevé en marché volatil ou toxique (δ = base + c_vol·σ + c_tox·tox)."""
    return round(float(base_min_edge_bps) + c_vol * float(volatility_bps) + c_tox * float(toxicity_bps), 4)


def entry_price_refusal(
    *, side: str, intended_price: float, micro_price: float, max_micro_gap_bps: float = 8.0,
) -> str:
    """Refuse une entrée si le microprice s'écarte déjà contre nous (le prix 'vrai' a bougé)."""
    if intended_price <= 0 or micro_price <= 0:
        return "MICROPRICE_INVALID"
    gap = (micro_price - intended_price) / intended_price * 10_000.0
    adverse = gap if str(side).upper() == "SHORT" else -gap
    # adverse > 0 signifie que le microprice est déjà défavorable au sens du trade
    if adverse > float(max_micro_gap_bps):
        return "MICROPRICE_ALREADY_ADVERSE"
    return ""


__all__ = ["microprice", "markout_bps", "ToxicityTracker",
           "toxicity_adjusted_min_edge_bps", "entry_price_refusal"]
