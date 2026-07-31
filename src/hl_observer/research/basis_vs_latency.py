"""ALPHA P50 — BASIS persistant vs DISLOCATION de latence (transient). Cross-venue ne trade QUE le transient.

Un écart de prix inter-venues peut être : (a) un BASIS structurel persistant (perp/spot, funding) → NON
tradable en latence, `DISABLED_BY_SCOPE` ; (b) une dislocation TRANSIENTE de latence qui converge vite →
seule tradable. On classe par l'autocorrélation lag-1 et la demi-vie de retour à la moyenne de l'écart.

Mesuré : autocorr proche de 1 + demi-vie longue ⇒ basis persistant. Retour rapide ⇒ transient.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.arbitrage.cross_venue_state_machine import HEDGED, simuler_hedge
from hl_observer.arbitrage.executable_legs import ACHAT, VENTE, jambe_executable, profondeur_disponible_usd

UNMEASURABLE = "UNMEASURABLE"


def autocorr1(serie: Sequence[float]) -> float | None:
    v = [float(x) for x in serie]
    n = len(v)
    if n < 20:
        return None
    m = sum(v) / n
    den = sum((x - m) ** 2 for x in v)
    if den <= 0:
        return None
    num = sum((v[i] - m) * (v[i - 1] - m) for i in range(1, n))
    return num / den


def demi_vie_pas(rho1: float | None) -> float | None:
    """Demi-vie (en pas) d'un AR(1) de coefficient rho1 : ln(0.5)/ln(rho1). None si rho1 hors (0,1)."""
    if rho1 is None or not (0.0 < rho1 < 1.0):
        return None
    return math.log(0.5) / math.log(rho1)


def classer_dislocation(serie_gap_bps: Sequence[float], *, dt_s: float = 1.0,
                        seuil_autocorr: float = 0.5, seuil_demi_vie_s: float = 30.0) -> dict[str, Any]:
    """Classe l'écart inter-venues : persistent_basis vs transient. Le cross-venue ne trade que transient."""
    rho = autocorr1(serie_gap_bps)
    hv_pas = demi_vie_pas(rho)
    hv_s = (hv_pas * dt_s) if hv_pas is not None else None
    if rho is None:
        return {"classe": UNMEASURABLE, "autocorr1": UNMEASURABLE, "demi_vie_s": UNMEASURABLE,
                "persistent_basis": UNMEASURABLE, "transient": UNMEASURABLE}
    persistent = bool(rho >= seuil_autocorr and (hv_s is None or hv_s >= seuil_demi_vie_s))
    return {"classe": ("PERSISTENT_BASIS" if persistent else "TRANSIENT_DISLOCATION"),
            "autocorr1": round(rho, 4), "demi_vie_s": (round(hv_s, 3) if hv_s is not None else UNMEASURABLE),
            "persistent_basis": persistent, "transient": (not persistent)}


def gate_cross_venue(classification: dict[str, Any], *, edge_bps: float | None, cost_bps: float | None) -> dict[str, Any]:
    """N'autorise le cross-venue que si TRANSIENT et edge exécutable > coût. Le basis est hors scope."""
    if classification.get("persistent_basis") is True:
        return {"trade": False, "raison": "PERSISTENT_BASIS_DISABLED_BY_SCOPE"}
    if not isinstance(edge_bps, (int, float)) or not isinstance(cost_bps, (int, float)):
        return {"trade": False, "raison": "UNMEASURABLE"}
    ok = edge_bps > cost_bps
    return {"trade": bool(ok), "raison": ("OK_TRANSIENT" if ok else "EDGE<=COUT")}


def _percentile(xs: Sequence[Any], q: float) -> float | None:
    v = sorted(float(x) for x in xs if isinstance(x, (int, float)) and not isinstance(x, bool))
    if not v:
        return None
    i = min(len(v) - 1, max(0, int(round((q / 100.0) * (len(v) - 1)))))
    return v[i]


def episode_cross_venue(*, serie_gap_bps: Sequence[float], gross_edge_bps: float, notional_usd: float,
                        carnet_A: Sequence[tuple[float, float]] = (), carnet_B: Sequence[tuple[float, float]] = (),
                        carnet_unwind: Mapping[str, Any] | None = None, ts_signal_ms: float = 0.0,
                        ts_hedge_ms: float | None = None, fee_bps: float = 4.5,
                        roundtrip_costs_bps: Sequence[float] | None = None, dt_s: float = 1.0) -> dict[str, Any]:
    """FIX-10 — épisode cross-venue de BOUT EN BOUT, revalidé contre TOUS les coûts :
    détection (transient vs basis) → gate → jambe A (entrée, carnet causal) → jambe B (hedge, latence) →
    fills/partials → machine à états (hedge/résidu) → unwind éventuel → PnL net (gross − slippage A − slippage B
    − frais − coût d'unwind). Règles dures : basis persistant = PAS un arb (éliminé) ; gross ≤ P95 du coût
    roundtrip = KILL. `carnet_*` = [(prix, taille)] ; sans profondeur L2, les jambes restent MORE_DATA (jamais
    de fill inventé). 0 réseau, 0 ordre réel."""
    out: dict[str, Any] = {"real_execution": False, "gross_edge_bps": round(float(gross_edge_bps), 4)}
    cls = classer_dislocation(serie_gap_bps, dt_s=dt_s)
    out["classe"] = cls["classe"]
    if cls["classe"] == UNMEASURABLE:
        return {**out, "verdict": "MORE_DATA", "net_pnl_usd": UNMEASURABLE,
                "raison": "dislocation non classable (série trop courte)"}
    if cls.get("persistent_basis") is True:                       # basis != arb : hors scope
        return {**out, "verdict": "NO_ARB_PERSISTENT_BASIS", "net_pnl_usd": 0.0,
                "raison": "basis persistant éliminé (basis != arb)"}
    p95 = _percentile(roundtrip_costs_bps or [], 95.0)
    out["p95_roundtrip_bps"] = (round(p95, 4) if isinstance(p95, (int, float)) else UNMEASURABLE)
    if isinstance(p95, (int, float)) and float(gross_edge_bps) <= p95:      # gross <= P95 roundtrip = KILL
        return {**out, "verdict": "KILL", "net_pnl_usd": 0.0,
                "raison": "gross %.2f <= P95 roundtrip %.2f bps" % (gross_edge_bps, p95)}
    g = gate_cross_venue(cls, edge_bps=float(gross_edge_bps), cost_bps=2.0 * float(fee_bps))
    if not g["trade"]:
        return {**out, "verdict": "NO_TRADE", "net_pnl_usd": 0.0, "raison": g["raison"]}
    # ── exécution des jambes contre carnet causal (jamais extrapolée) ──
    depthA = profondeur_disponible_usd(list(carnet_A))
    depthB = profondeur_disponible_usd(list(carnet_B))
    if depthA <= 0.0 and depthB <= 0.0:                           # top-of-book seul : profondeur L2 requise
        return {**out, "verdict": "MORE_DATA", "net_pnl_usd": UNMEASURABLE,
                "raison": "transient tradable mais profondeur L2 absente (jambes non exécutables)"}
    fill1 = min(float(notional_usd), depthA)
    jA = jambe_executable(list(carnet_A), sens=ACHAT, notional_usd=fill1) if fill1 > 0 else None
    if jA is None or not jA.executable or jA.prix_moyen is None:
        return {**out, "verdict": "NO_FILL_A", "net_pnl_usd": 0.0, "raison": "carnet A insuffisant"}
    hedge_notional = min(fill1, depthB)
    jB = jambe_executable(list(carnet_B), sens=VENTE, notional_usd=hedge_notional) if hedge_notional > 0 else None
    leg2 = {"notional_hedge": hedge_notional, "ts_ms": ts_hedge_ms,
            "slippage_bps": (jB.slippage_bps if jB else None), "echec": (hedge_notional <= 0)}
    res = simuler_hedge(leg1={"notional_demande": float(notional_usd), "notional_fill": fill1, "ts_ms": ts_signal_ms},
                        leg2=leg2, carnet_unwind=carnet_unwind, position_side="LONG",
                        entry_price=jA.prix_moyen, fee_bps_unwind=fee_bps)
    matched = float(res["matched_notional_usd"])
    gross_usd = float(gross_edge_bps) / 1e4 * matched
    slipA = float(jA.slippage_bps or 0.0) / 1e4 * matched
    slipB = float(jB.slippage_bps or 0.0) / 1e4 * matched if jB else 0.0
    fees = 2.0 * float(fee_bps) / 1e4 * matched                   # entrée + hedge (taker les deux)
    u = res.get("unwind")
    unwind_pnl = float(u["unwind_net_pnl_usd"]) if isinstance(u, Mapping) and u.get("statut") == "OK" else 0.0
    net = round(gross_usd - slipA - slipB - fees + unwind_pnl, 6)
    verdict = "CANDIDAT" if (res["issue"] == HEDGED and net > 0) else "KILL"
    return {**out, "verdict": verdict, "issue": res["issue"], "couvert": res["couvert"],
            "matched_notional_usd": round(matched, 6), "residual_notional_usd": res["residual_notional_usd"],
            "leg1_partial": res["leg1_partial"], "hedge_latency_ms": res["hedge_latency_ms"],
            "gross_pnl_usd": round(gross_usd, 6), "entry_slippage_usd": round(slipA, 6),
            "hedge_slippage_usd": round(slipB, 6), "fees_usd": round(fees, 6),
            "unwind_net_pnl_usd": round(unwind_pnl, 6), "net_pnl_usd": net,
            "net_bps": (round(net / float(notional_usd) * 1e4, 4) if notional_usd else UNMEASURABLE)}


__all__ = ["autocorr1", "demi_vie_pas", "classer_dislocation", "gate_cross_venue",
           "episode_cross_venue", "UNMEASURABLE"]
