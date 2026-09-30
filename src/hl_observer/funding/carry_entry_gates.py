"""GATES & THROTTLE CARRY (idées #12/#14/#20) — entrer au bon moment, capturer la base, et se
mettre en veille quand rien ne paie. Purs, deny-by-default. PAPER only, aucun ordre.

  Y12 spread_assez_serre : ne monter la jambe que quand le carnet spot est ÉTROIT (coupe le coût
      de spread). Spread inconnu -> refus (on ne devine pas).
  Y14 gain_convergence_base_bps : quand le perp s'écarte du spot (base), la base tend à converger ;
      c'est un 2e PnL. On mesure le gain attendu de la convergence, net du coût.
  Y20 doit_throttler : quand AUCUNE stratégie n'a d'edge (pas de carry viable, pas de purge), réduire
      l'activité et attendre au lieu de forcer -> coûts préservés pendant les creux.
"""
from __future__ import annotations

SPREAD_MAX_ENTREE_BPS = 8.0        # au-dessus, l'entrée coûte trop cher -> on attend un carnet serré
BASE_CONVERGENCE_MIN_BPS = 5.0     # sous ça, la convergence ne vaut pas le coût


def spread_assez_serre(spread_spot_bps: float | None, spread_perp_bps: float | None, *,
                       maxi_bps: float = SPREAD_MAX_ENTREE_BPS) -> bool:
    """Y12 : True seulement si le spread combiné des 2 jambes est sous le seuil. Inconnu -> False."""
    if spread_spot_bps is None or spread_perp_bps is None:
        return False
    return (float(spread_spot_bps) + float(spread_perp_bps)) <= float(maxi_bps)


def gain_convergence_base_bps(base_bps: float | None, cout_bps: float, *,
                              fraction_capturee: float = 0.5, mini_bps: float = BASE_CONVERGENCE_MIN_BPS) -> float | None:
    """Y14 : gain NET attendu si la base converge (on ne capture qu'une fraction, prudent). None si
    base absente ou trop faible pour dépasser le coût."""
    if base_bps is None:
        return None
    capturable = abs(float(base_bps)) * float(fraction_capturee)
    if capturable < float(mini_bps):
        return None
    net = capturable - float(cout_bps)
    return round(net, 3) if net > 0 else None


def doit_throttler(*, carrys_viables: int, purges_actives: int, edge_copy_bps: float | None) -> bool:
    """Y20 : True si aucune source d'edge -> on se met en veille (moins de coûts, on attend un régime
    porteur). deny-by-default : on ne throttle QUE si tout est à zéro/absent."""
    edge_copy = float(edge_copy_bps) if edge_copy_bps is not None else 0.0
    return int(carrys_viables) <= 0 and int(purges_actives) <= 0 and edge_copy <= 0.0


__all__ = ["spread_assez_serre", "gain_convergence_base_bps", "doit_throttler",
           "SPREAD_MAX_ENTREE_BPS", "BASE_CONVERGENCE_MIN_BPS"]
