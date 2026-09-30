"""Le verdict NET de la piste liquidations — brancher le markout brut sur LE noyau de coûts.

`liquidation_cascade.juger()` mesure le markout **BRUT** de l'absorbeur (sur le MID, jamais sur un
prix de trade). Il le dit lui-même, honnêtement : « *un markout brut n'est pas un edge net* ». Ce
module fait le dernier pas : il fait passer ce markout brut par `compute_net_edge` — **LE lieu unique
des coûts** (frais taker/maker, spread) — et ne déclare la piste vivante que si l'edge **NET** est
positif.

🩺 Anti-« maladie du projet » (capacité présente, chaînon manquant) : on ne réécrit PAS une nouvelle
soustraction de coûts à côté du noyau ; on **BRANCHE** la mesure liquidations SUR le noyau. Il n'y a
donc qu'un seul endroit qui décide des coûts — pas deux standards.

Coûts par défaut (doc de `liquidation_cascade`) : **9 bps taker aller-retour** (4,5 × 2), **3 bps
maker aller-retour**. En pleine cascade, poser un ordre maker est risqué (on peut être traversé) —
d'où le défaut prudent : **taker**.

🔒 Ceci **MESURE** la net-positivité (`min_edge_bps=0.0` → « net > 0 ? »). Ce n'est PAS un
abaissement du plancher de trading : quand le noyau tradera pour de vrai, c'est **son** plancher
(30 bps par défaut) qui s'applique. Module PUR (aucun réseau, aucun état). Une mesure n'est pas un ordre.
"""
from __future__ import annotations

from collections.abc import Mapping

from hl_observer.edge.edge_calculator import EdgeNetInputs, EdgeNetResult, compute_net_edge

# Aller-retour = entrée + sortie. Source : la doc des 4 pièges de liquidation_cascade.
COUT_TAKER_ALLER_RETOUR_BPS = 9.0
COUT_MAKER_ALLER_RETOUR_BPS = 3.0


def edge_net_liquidation(
    markout_brut_bps: float,
    *,
    en_maker: bool = False,
    spread_bps: float = 0.0,
    min_edge_bps: float = 0.0,
) -> EdgeNetResult:
    """Fait passer le markout brut de l'absorbeur par le noyau de coûts et renvoie le verdict NET.

    - `en_maker=False` (défaut) → coût taker aller-retour (9 bps). `True` → maker (3 bps).
    - `spread_bps` → coût de spread à traverser (0 par défaut ; à renseigner sur données réelles).
    - `min_edge_bps=0.0` → on répond « net-positif ? ». Relève-le pour exiger une marge.

    Renvoie un `EdgeNetResult` : `.net_edge_bps` (le nombre), `.accepted` (net ≥ plancher).
    """
    cout_frais = COUT_MAKER_ALLER_RETOUR_BPS if en_maker else COUT_TAKER_ALLER_RETOUR_BPS
    return compute_net_edge(
        EdgeNetInputs(
            gross_edge_bps=float(markout_brut_bps),
            taker_fee_bps=cout_frais,               # frais aller-retour = un COÛT qui se soustrait
            spread_cost_bps=max(0.0, float(spread_bps)),
        ),
        min_edge_bps=float(min_edge_bps),
    )


def meilleur_horizon_net(
    markouts_moyens_par_horizon: Mapping[float, float],
    *,
    en_maker: bool = False,
    spread_bps: float = 0.0,
    min_edge_bps: float = 0.0,
) -> tuple[float, EdgeNetResult] | None:
    """Sur un dict {horizon_s: markout_brut_moyen}, renvoie (meilleur_horizon, verdict NET) — ou
    `None` si le dict est vide. Compose directement avec `VerdictCascade.markouts_moyens`.

    On choisit l'horizon au **meilleur edge NET** (après coûts), pas au meilleur brut : c'est le net
    qui paie.
    """
    if not markouts_moyens_par_horizon:
        return None
    best_h = None
    best_res: EdgeNetResult | None = None
    for h, brut in markouts_moyens_par_horizon.items():
        res = edge_net_liquidation(
            brut, en_maker=en_maker, spread_bps=spread_bps, min_edge_bps=min_edge_bps
        )
        if best_res is None or res.net_edge_bps > best_res.net_edge_bps:
            best_h, best_res = float(h), res
    assert best_h is not None and best_res is not None
    return best_h, best_res


__all__ = [
    "COUT_MAKER_ALLER_RETOUR_BPS",
    "COUT_TAKER_ALLER_RETOUR_BPS",
    "edge_net_liquidation",
    "meilleur_horizon_net",
]
