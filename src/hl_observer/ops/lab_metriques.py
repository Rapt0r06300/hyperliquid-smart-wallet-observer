"""[LAB α] MÉTRIQUES + GATE DE PROMOTION. Calcule, pour un candidat, le jeu de mesures exigé (gross/net PnL,
ROI, fees, Profit Factor, drawdown, Expected Shortfall, LCB, turnover, concentration, capacité) et applique la
règle de promotion DURE :
  PROMU ⟺ net>0 ET oos>0 ET forward>0 ET LCB>0 ET adverse_p95>0 ET ledger réconcilié ET échantillon suffisant
          ET capacité mesurable.
Sinon : KILL / MORE_DATA / UNMEASURABLE. Aucune donnée synthétique n'entre dans le verdict (le caller le
garantit). Fonctions pures ; 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

# Câblage de la VÉRITÉ de latence (P1B) dans le laboratoire : le stress de latence (item 20) n'est plus
# un simple coefficient — il réutilise la latence causale autoritaire de paper_trading.latency_truth.
from hl_observer.paper_trading import latency_truth as _LT

UNMEASURABLE = "UNMEASURABLE"


def stress_latence_bps(delay_sec: float, *, coeff_bps_per_sec: float = 0.20,
                       cap_bps: float = 15.0) -> dict[str, Any]:
    """Composante LATENCE du stress adverse (item 20). Délègue à la vérité de latence canonique
    (latency_truth), étiquetée STRESS_ONLY : ne peut jamais être promue comme PnL autoritaire."""
    return _LT.latence_scalaire_stress_bps(float(delay_sec), coeff_bps_per_sec=coeff_bps_per_sec,
                                           cap_bps=cap_bps)


def profit_factor(nets: list[float]) -> Any:
    gains = sum(x for x in nets if isinstance(x, (int, float)) and x > 0)
    pertes = -sum(x for x in nets if isinstance(x, (int, float)) and x < 0)
    if pertes == 0:
        return UNMEASURABLE if gains == 0 else float("inf")
    return round(gains / pertes, 6)


def drawdown(courbe_equity: list[float]) -> Any:
    vals = [x for x in courbe_equity if isinstance(x, (int, float)) and math.isfinite(x)]
    if not vals:
        return UNMEASURABLE
    pic = vals[0]
    dd = 0.0
    for v in vals:
        pic = max(pic, v)
        dd = max(dd, pic - v)
    return round(dd, 8)


def expected_shortfall(rendements: list[float], *, q: float = 0.05) -> Any:
    vals = sorted(x for x in rendements if isinstance(x, (int, float)) and math.isfinite(x))
    if not vals:
        return UNMEASURABLE
    k = max(1, int(math.ceil(q * len(vals))))
    pires = vals[:k]
    return round(sum(pires) / len(pires), 8)


def lcb_moyenne(nets: list[float], *, z: float = 1.645) -> Any:
    """Borne de confiance basse (LCB) de la moyenne (approx normale, z=1.645 → ~95% unilatéral). n<2 → UNMEASURABLE."""
    vals = [x for x in nets if isinstance(x, (int, float)) and math.isfinite(x)]
    n = len(vals)
    if n < 2:
        return UNMEASURABLE
    moy = sum(vals) / n
    var = sum((x - moy) ** 2 for x in vals) / (n - 1)
    return round(moy - z * math.sqrt(var / n), 8)


def hhi(contributions: dict[Any, float]) -> Any:
    """Indice de concentration Herfindahl sur les |contributions| (1 = tout sur une clé, ~0 = dispersé)."""
    parts = {k: abs(float(v)) for k, v in contributions.items()
             if isinstance(v, (int, float)) and math.isfinite(v)}
    tot = sum(parts.values())
    if tot <= 0:
        return UNMEASURABLE
    return round(sum((v / tot) ** 2 for v in parts.values()), 6)


def turnover(notional_traite: float, equity: float) -> Any:
    if not (isinstance(equity, (int, float)) and equity > 0):
        return UNMEASURABLE
    return round(float(notional_traite) / float(equity), 6)


def metriques_candidat(*, segments: dict[str, dict[str, Any]], nets_episodes: list[float],
                       courbe_equity: list[float], notional_traite: float, equity_finale: float,
                       fees: float, contributions_coin: dict[Any, float] | None = None,
                       capacite: Any = UNMEASURABLE, reconcilie: bool = False,
                       placebo_net: Any = None) -> dict[str, Any]:
    """Assemble toutes les métriques. `segments` = {IS/OOS/FORWARD/ADVERSE_P95/ADVERSE_P99: {net, roi}}.
    `placebo_net` (item 18) : PnL des signaux inversés — un vrai edge doit le laisser ≤ 0."""
    def _seg(nom: str, champ: str) -> Any:
        return segments.get(nom, {}).get(champ)
    net = _seg("IS", "net")
    gross = round(net + fees, 8) if isinstance(net, (int, float)) else UNMEASURABLE
    return {
        "gross_pnl": gross, "net_pnl": net, "roi": _seg("IS", "roi"), "fees": round(float(fees), 8),
        "oos_net": _seg("OOS", "net"), "forward_net": _seg("FORWARD", "net"),
        "adverse_p95_net": _seg("ADVERSE_P95", "net"), "adverse_p99_net": _seg("ADVERSE_P99", "net"),
        "adverse_p95_oos": _seg("ADVERSE_P95", "net_oos"), "adverse_p95_forward": _seg("ADVERSE_P95", "net_forward"),
        "profit_factor": profit_factor(nets_episodes), "drawdown": drawdown(courbe_equity),
        "expected_shortfall": expected_shortfall(nets_episodes), "lcb": lcb_moyenne(nets_episodes),
        "turnover": turnover(notional_traite, equity_finale),
        "concentration_hhi": hhi(contributions_coin or {}), "capacite": capacite,
        "n_episodes": len(nets_episodes), "reconcilie": bool(reconcilie),
        "placebo_net": placebo_net,
    }


def verdict_promotion(m: dict[str, Any], *, min_episodes: int = 30,
                      hhi_max: float = 0.6, placebo_tol: float = 0.0) -> str:
    """Applique la règle dure (items 8/18). Retourne PROMU / KILL / MORE_DATA / UNMEASURABLE.

    PROMU ⟺ net>0 ET oos>0 ET forward>0 ET LCB>0 ET ADVERSE_P95>0 (déjà = pire de OOS/FORWARD)
            ET placebo REJETÉ (placebo_net ≤ tol : l'edge disparaît si on inverse les signaux)
            ET concentration valide (HHI mesurable et ≤ hhi_max : pas dominé par un seul coin)
            ET ledger réconcilié ET échantillon suffisant ET capacité mesurable.
    Sinon KILL / MORE_DATA / UNMEASURABLE."""
    if not m.get("reconcilie"):
        return "KILL"
    if m.get("capacite") in (None, UNMEASURABLE):
        return "UNMEASURABLE"
    if (m.get("n_episodes") or 0) < min_episodes:
        return "MORE_DATA"
    # concentration : une HHI non mesurable ne prouve pas la diversification -> pas promouvable en l'état.
    hhi_val = m.get("concentration_hhi")
    if hhi_val in (None, UNMEASURABLE):
        return "UNMEASURABLE"
    cles = ("net_pnl", "oos_net", "forward_net", "lcb", "adverse_p95_net")
    positifs = all(isinstance(m.get(k), (int, float)) and m.get(k) > 0 for k in cles)
    # placebo REJETÉ : les signaux inversés ne doivent PAS être profitables (item 18).
    placebo = m.get("placebo_net")
    placebo_ok = (placebo is None) or (isinstance(placebo, (int, float)) and placebo <= placebo_tol)
    concentration_ok = float(hhi_val) <= float(hhi_max)
    if positifs and placebo_ok and concentration_ok:
        return "PROMU"
    return "KILL"


__all__ = ["profit_factor", "drawdown", "expected_shortfall", "lcb_moyenne", "hhi", "turnover",
           "metriques_candidat", "verdict_promotion", "UNMEASURABLE"]
