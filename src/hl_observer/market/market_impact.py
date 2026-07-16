"""L'IMPACT DE MARCHÉ (idée `impact` de moisson-fini.md).

*Notre propre ordre bouge le prix **contre** nous.* C'est **l'hypothèse qui expliquerait nos
−7,97 bps de copy-trading** : on paie l'impact du leader **après** lui. On ne l'a **jamais** chiffré.

🔒 **Règle dure.** L'impact est un **COÛT** : il se **SOUSTRAIT** de l'edge brut, **exactement comme**
les frais (9 bps) et le slippage. *Un coût qu'on mesure mais qu'on ne soustrait pas est un coût
qu'on **CACHE** — c'est arrivé **17 fois**.* Et *pas de zéro silencieux* : profondeur inconnue →
`None` (INSUFFICIENT_DATA), pas 0.

Module PUR. Il alimente `edge/edge_calculator.py::compute_net_edge()` (le branchement est une étape
séparée, faite avec soin — ce module fournit la brique testée).
"""
from __future__ import annotations

K_IMPACT_DEFAUT_BPS = 50.0   # impact (bps) à 100 % de participation — À CALIBRER sur nos carnets


def impact_bps(
    taille_notional: float,
    profondeur_notional: float,
    *,
    k: float = K_IMPACT_DEFAUT_BPS,
) -> float | None:
    """Coût d'impact en bps pour prendre `taille_notional` dans un carnet de `profondeur_notional`.

    Modèle linéaire en **participation** (part du carnet qu'on consomme) : plus on prend une grosse
    part, plus ça coûte. Renvoie `None` si la profondeur est inconnue/nulle (**INSUFFICIENT_DATA**).
    """
    if profondeur_notional is None or float(profondeur_notional) <= 0.0:
        return None
    if taille_notional is None or float(taille_notional) < 0.0:
        return None
    participation = float(taille_notional) / float(profondeur_notional)
    return float(k) * participation


def edge_net_apres_impact(edge_brut_bps: float, impact: float | None) -> float | None:
    """edge_net = edge_brut − impact. Renvoie `None` si l'impact est inconnu.

    🔴 On **soustrait** (l'impact est un coût). Si on ne connaît pas l'impact, on ne peut pas
    garantir l'edge net → `None` (le noyau refuse plutôt que de deviner).
    """
    if impact is None:
        return None
    return float(edge_brut_bps) - float(impact)
