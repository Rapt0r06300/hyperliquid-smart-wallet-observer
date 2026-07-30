"""Jalon 1 — décomposition du coût d'exécution en 4 composantes bps NON redondantes.

Le scoreboard reste `UNMEASURABLE` sur `costs_bps` tant que les 4 composantes ne sont pas mesurées.
`slippage_model` mesure pourtant déjà un slippage RÉFÉRENCÉ AU MID — qui contient DÉJÀ le demi-spread.
Sommer un `spread_bps` séparé par-dessus le double-compterait. Ce module décompose proprement le
coût réel d'un franchissement, tout référencé au **mid au moment de la DÉCISION**, en 4 parts
additives et disjointes (dénominateur commun = mid, donc `spread + slippage` égale EXACTEMENT le coût
mid→prix moyen, sans terme croisé) :

    spread_bps   = mid → meilleur prix touché       (franchir le demi-spread)
    slippage_bps = meilleur prix → prix moyen exécuté (impact de profondeur au-delà du touch)
    fees_bps     = frais taker (bps)
    latency_bps  = dérive du mid pendant la latence RÉELLE décision→exécution (adverse = coût +)

Règle dure : toute composante dont l'entrée manque vaut `UNMEASURABLE` (None), JAMAIS 0 — un coût
oublié fabrique un faux edge. Le total réutilise `scoreboard_metrics.costs_bps` : il n'existe que si
les 4 sont mesurées. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from hl_observer.simulation.scoreboard_metrics import costs_bps as _sommer_couts

SCHEMA_VERSION = "hypersmart.cost_components.v1"
_BPS = 10_000.0


def _pos(x) -> float | None:
    """Nombre fini strictement positif, sinon None (un prix/mid <= 0 n'est pas mesurable)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _sens(side: object) -> int | None:
    """+1 pour un achat, -1 pour une vente ; None si le sens est illisible."""
    s = str(side or "").strip().upper()
    if s in ("BUY", "B", "LONG", "BID"):
        return 1
    if s in ("SELL", "S", "SHORT", "ASK"):
        return -1
    return None


def spread_bps(mid: float, best_touch: float, side: object) -> float | None:
    """Coût de franchir le demi-spread : mid → meilleur prix touché, en bps signés-coût (>0 = payé plus)."""
    m, t = _pos(mid), _pos(best_touch)
    sg = _sens(side)
    if m is None or t is None or sg is None:
        return None
    return round(sg * (t - m) / m * _BPS, 6)


def slippage_bps(best_touch: float, avg_fill: float, side: object, *, mid: float | None = None) -> float | None:
    """Impact de profondeur AU-DELÀ du touch : touch → prix moyen. Dénominateur = mid (défaut : touch).

    Utiliser le mid comme dénominateur commun rend `spread_bps + slippage_bps` EXACTEMENT égal au
    coût mid→prix moyen (pas de terme croisé). Sans mid fourni, on retombe sur le touch (approximation).
    """
    t, a = _pos(best_touch), _pos(avg_fill)
    sg = _sens(side)
    if t is None or a is None or sg is None:
        return None
    denom = _pos(mid) if mid is not None else t
    if denom is None:
        return None
    return round(sg * (a - t) / denom * _BPS, 6)


def latency_bps(mid_decision: float, mid_fill: float, side: object) -> float | None:
    """Dérive du mid pendant la latence RÉELLE décision→exécution. Adverse (>0) = surcoût ; favorable (<0) = crédit.

    Signé et honnête par trade : la latence peut jouer pour ou contre. `None` si un des deux mids manque
    (on ne suppose JAMAIS une latence nulle : une latence non mesurée reste UNMEASURABLE, pas 0)."""
    d, f = _pos(mid_decision), _pos(mid_fill)
    sg = _sens(side)
    if d is None or f is None or sg is None:
        return None
    return round(sg * (f - d) / d * _BPS, 6)


@dataclass(frozen=True, slots=True)
class CostComponents:
    fees_bps: float | None
    spread_bps: float | None
    slippage_bps: float | None
    latency_bps: float | None
    total_bps: float | None
    unmeasured: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "fees_bps": self.fees_bps, "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps, "latency_bps": self.latency_bps,
            "total_bps": self.total_bps, "unmeasured": list(self.unmeasured),
            "paper_only": True, "real_execution": False,
        }


def _finalise(fees, spread, slip, lat) -> CostComponents:
    total = _sommer_couts(fees_bps=fees, spread_bps=spread, slippage_bps=slip, latency_bps=lat)
    champs = {"fees_bps": fees, "spread_bps": spread, "slippage_bps": slip, "latency_bps": lat}
    unmeasured = tuple(k for k, v in champs.items() if v is None)
    if total is None and "total_bps" not in unmeasured:
        unmeasured = unmeasured + ("total_bps",)
    return CostComponents(fees_bps=fees, spread_bps=spread, slippage_bps=slip,
                          latency_bps=lat, total_bps=total, unmeasured=unmeasured)


def decompose_execution(
    *,
    side: object,
    mid_decision: float | None,
    best_touch: float | None,
    avg_fill_price: float | None,
    mid_at_fill: float | None = None,
    fee_bps: float | None = None,
) -> CostComponents:
    """Décompose un franchissement en 4 composantes bps. Chaque entrée absente ⇒ composante UNMEASURABLE."""
    spread = spread_bps(mid_decision, best_touch, side) if (mid_decision is not None and best_touch is not None) else None
    slip = (slippage_bps(best_touch, avg_fill_price, side, mid=mid_decision)
            if (best_touch is not None and avg_fill_price is not None) else None)
    lat = latency_bps(mid_decision, mid_at_fill, side) if (mid_decision is not None and mid_at_fill is not None) else None
    fees = None
    if fee_bps is not None:
        try:
            fv = float(fee_bps)
            fees = round(fv, 6) if math.isfinite(fv) else None
        except (TypeError, ValueError):
            fees = None
    return _finalise(fees, spread, slip, lat)


def _meilleur_touch(book_side: Sequence, sens: int) -> float | None:
    """Meilleur prix touché : plus bas ask (achat), plus haut bid (vente). None si carnet vide/illisible."""
    prix: list[float] = []
    for niveau in book_side or ():
        try:
            p = float(niveau[0])
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(p) and p > 0:
            prix.append(p)
    if not prix:
        return None
    return min(prix) if sens > 0 else max(prix)


def depuis_carnet_causal(
    *,
    side: object,
    notional_usdc: float,
    mid_decision: float,
    asks: Sequence = (),
    bids: Sequence = (),
    mid_at_fill: float | None = None,
    fee_bps: float | None = None,
    min_fill_ratio: float = 0.85,
) -> CostComponents:
    """Câblage L2 CAUSAL : marche le carnet (exec_model) au prix de décision, puis décompose le coût.

    Réutilise le book-walker existant (`simulate_depth_execution`) — aucune duplication. Si rien ne se
    remplit, `avg_fill_price` est None ⇒ slippage UNMEASURABLE (on ne facture pas un fill inexistant)."""
    from hl_observer.paper_trading.exec_model import simulate_depth_execution

    sg = _sens(side)
    touch = _meilleur_touch(asks if (sg or 0) > 0 else bids, sg) if sg is not None else None
    execution = simulate_depth_execution(
        side=str(side), notional_usdc=notional_usdc, mid_price=mid_decision,
        asks=list(asks), bids=list(bids), min_fill_ratio=min_fill_ratio,
    )
    avg = getattr(execution, "average_fill_price", None)
    return decompose_execution(
        side=side, mid_decision=mid_decision, best_touch=touch,
        avg_fill_price=avg, mid_at_fill=mid_at_fill, fee_bps=fee_bps,
    )


__all__ = [
    "SCHEMA_VERSION", "CostComponents",
    "spread_bps", "slippage_bps", "latency_bps",
    "decompose_execution", "depuis_carnet_causal",
]
