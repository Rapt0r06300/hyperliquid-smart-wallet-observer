"""P9.3 (§11.3) — machine à états du hedge cross-venue + UNWIND réellement SIMULÉ contre carnet causal.

Cycle : SIGNAL → LEG1_PENDING → LEG1_PARTIAL/FILLED → LEG2_HEDGE → HEDGED ; échec : LEG2_FAIL → UNWIND.

Quand la jambe 1 reste nue (échec ou hedge partiel), le débouclage n'est PAS supposé au mid : il est
SIMULÉ contre un carnet causal (via `executable_legs.jambe_executable`), avec prix de sortie VWAP,
slippage, frais et PnL réels. Un carnet insuffisant pour déboucler ⇒ `UNMEASURABLE` (risque non
chiffrable), jamais un exit inventé. Métriques publiées pour le scoreboard : matched notional, résidu
(exposition nue), latence de hedge, coût/PnL d'unwind, taux d'échec de hedge. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from hl_observer.arbitrage.executable_legs import ACHAT, VENTE, jambe_executable

SCHEMA_VERSION = "hypersmart.cross_venue_state_machine.v2"

NO_LEG1 = "NO_LEG1"
HEDGED = "HEDGED"
RESIDUAL_UNHEDGED = "RESIDUAL_UNHEDGED"
UNWIND_REQUIRED = "UNWIND_REQUIRED"

_TOL = 1e-9
_LONG = ("LONG", "L", "BUY", "B", "1", "+1")
_SHORT = ("SHORT", "S", "SELL", "-1")


def _num(x: object, defaut: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return defaut
    return v if math.isfinite(v) else defaut


def simuler_unwind(
    *,
    position_side: object,
    notional_usd: float,
    entry_price: float,
    carnet_bids=(),
    carnet_asks=(),
    fee_bps: float = 3.5,
    entry_fee_bps: float | None = None,
) -> dict[str, Any]:
    """Débouclage RÉEL de la jambe nue contre un carnet causal. LONG→vendre les bids, SHORT→acheter les asks."""
    side = str(position_side or "").strip().upper()
    long = side in _LONG
    short = side in _SHORT
    if not (long or short) or _num(entry_price) <= 0 or _num(notional_usd) <= 0:
        return {"statut": "UNMEASURABLE", "raison": "position invalide"}

    sens = VENTE if long else ACHAT                       # sortir d'un long = vendre ; d'un short = acheter
    niveaux = list(carnet_bids) if long else list(carnet_asks)
    j = jambe_executable(niveaux, sens=sens, notional_usd=float(notional_usd))
    if not j.executable or j.prix_moyen is None:
        return {"statut": "UNMEASURABLE", "raison": "carnet insuffisant pour deboucler",
                "jambe": j.as_dict()}

    exit_px = float(j.prix_moyen)
    qty = float(notional_usd) / float(entry_price)
    gross = (exit_px - float(entry_price)) * qty if long else (float(entry_price) - exit_px) * qty
    exit_fee = float(notional_usd) * float(fee_bps) / 10_000.0
    entry_fee = float(notional_usd) * float(entry_fee_bps if entry_fee_bps is not None else fee_bps) / 10_000.0
    return {
        "statut": "OK",
        "exit_price": round(exit_px, 10),
        "unwind_slippage_bps": round(float(j.slippage_bps or 0.0), 6),
        "exit_fee_usd": round(exit_fee, 6),
        "unwind_gross_pnl_usd": round(gross, 6),
        "unwind_net_pnl_usd": round(gross - exit_fee - entry_fee, 6),   # net des frais entrée+sortie
        "unwind_notional_usd": round(float(notional_usd), 6),
        "real_execution": False,
    }


def simuler_hedge(
    *,
    leg1: Mapping[str, Any],
    leg2: Mapping[str, Any] | None = None,
    carnet_unwind: Mapping[str, Any] | None = None,
    position_side: object = None,
    entry_price: float | None = None,
    fee_bps_unwind: float = 3.5,
) -> dict[str, Any]:
    """Simule un cycle de hedge ; si une jambe reste nue et un `carnet_unwind` est fourni, SIMULE l'unwind.

    `leg1`={notional_demande, notional_fill, ts_ms} ; `leg2`={notional_hedge, ts_ms, slippage_bps, echec} ;
    `carnet_unwind`={bids, asks} = carnet causal de débouclage de la jambe 1."""
    leg1 = leg1 or {}
    fill1 = max(0.0, _num(leg1.get("notional_fill")))
    demande1 = max(0.0, _num(leg1.get("notional_demande"), fill1))
    ts1 = leg1.get("ts_ms")

    if fill1 <= _TOL:
        return _resume(NO_LEG1, matched=0.0, residual=0.0, leg1_fill=0.0, hedge_latency_ms=None,
                       hedge_slippage_bps=None, leg1_partial=(demande1 > _TOL), detail="jambe 1 non remplie")

    leg1_partial = fill1 + _TOL < demande1

    if leg2 is None or leg2.get("echec"):
        raison = (leg2 or {}).get("raison_echec") or "LEG2_NON_EXECUTEE"
        res = _resume(UNWIND_REQUIRED, matched=0.0, residual=round(fill1, 10), leg1_fill=round(fill1, 10),
                      hedge_latency_ms=None, hedge_slippage_bps=None, leg1_partial=leg1_partial,
                      detail=f"jambe 1 nue ({raison}) → unwind")
        return _attacher_unwind(res, carnet_unwind, position_side, entry_price, fee_bps_unwind)

    hedge = max(0.0, _num(leg2.get("notional_hedge")))
    matched = min(fill1, hedge)
    residual = max(0.0, fill1 - matched)
    ts2 = leg2.get("ts_ms")
    latence = None
    if ts1 is not None and ts2 is not None:
        d = _num(ts2) - _num(ts1)
        latence = round(d, 6) if d >= 0 else None
    slip = leg2.get("slippage_bps")
    slip = round(_num(slip), 6) if slip is not None else None

    issue = HEDGED if residual <= _TOL else RESIDUAL_UNHEDGED
    res = _resume(issue, matched=round(matched, 10), residual=round(residual, 10), leg1_fill=round(fill1, 10),
                  hedge_latency_ms=latence, hedge_slippage_bps=slip, leg1_partial=leg1_partial,
                  detail=("couvert" if issue == HEDGED else "résidu nu à déboucler"))
    if residual > _TOL:
        res = _attacher_unwind(res, carnet_unwind, position_side, entry_price, fee_bps_unwind)
    return res


def _attacher_unwind(res, carnet_unwind, position_side, entry_price, fee_bps_unwind):
    if carnet_unwind and position_side is not None and entry_price is not None:
        res["unwind"] = simuler_unwind(
            position_side=position_side, notional_usd=res["residual_notional_usd"],
            entry_price=entry_price, carnet_bids=carnet_unwind.get("bids", ()),
            carnet_asks=carnet_unwind.get("asks", ()), fee_bps=fee_bps_unwind,
        )
    return res


def _resume(issue, *, matched, residual, leg1_fill, hedge_latency_ms, hedge_slippage_bps,
            leg1_partial, detail) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "issue": issue,
        "matched_notional_usd": matched, "residual_notional_usd": residual, "leg1_fill_usd": leg1_fill,
        "leg1_partial": leg1_partial, "hedge_latency_ms": hedge_latency_ms,
        "hedge_slippage_bps": hedge_slippage_bps, "couvert": issue == HEDGED,
        "unwind": None, "detail": detail, "real_execution": False,
    }


def statistiques_hedge(resumes) -> dict[str, Any]:
    """Agrège pour le scoreboard : taux d'échec, latence médiane, résidu total, coût/PnL d'unwind."""
    rs = [r for r in (resumes or []) if isinstance(r, Mapping)]
    tentes = [r for r in rs if r.get("issue") != NO_LEG1]
    n = len(tentes)
    echecs = sum(1 for r in tentes if r.get("issue") == UNWIND_REQUIRED)
    residuels = sum(1 for r in tentes if r.get("issue") == RESIDUAL_UNHEDGED)
    latences = sorted(r["hedge_latency_ms"] for r in tentes if r.get("hedge_latency_ms") is not None)
    med = None
    if latences:
        m = len(latences)
        med = latences[m // 2] if m % 2 else (latences[m // 2 - 1] + latences[m // 2]) / 2.0
    unwinds = [r["unwind"] for r in tentes if isinstance(r.get("unwind"), Mapping) and r["unwind"].get("statut") == "OK"]
    unwind_pnl = round(sum(_num(u.get("unwind_net_pnl_usd")) for u in unwinds), 6)
    return {
        "schema_version": SCHEMA_VERSION,
        "n_hedges_tentes": n,
        "failed_hedge_rate": (round(echecs / n, 6) if n else None),
        "residual_rate": (round(residuels / n, 6) if n else None),
        "matched_notional_total_usd": round(sum(_num(r.get("matched_notional_usd")) for r in tentes), 6),
        "residual_exposure_total_usd": round(sum(_num(r.get("residual_notional_usd")) for r in tentes), 6),
        "hedge_latency_mediane_ms": (round(med, 6) if med is not None else None),
        "n_unwinds_simules": len(unwinds),
        "unwind_net_pnl_total_usd": unwind_pnl,
        "real_execution": False,
    }


__all__ = [
    "SCHEMA_VERSION", "NO_LEG1", "HEDGED", "RESIDUAL_UNHEDGED", "UNWIND_REQUIRED",
    "simuler_unwind", "simuler_hedge", "statistiques_hedge",
]
