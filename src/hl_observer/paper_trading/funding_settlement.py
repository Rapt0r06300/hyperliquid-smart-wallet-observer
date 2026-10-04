"""Funding settlement certification for PAPER/read-only accounting.

A continuous funding accrual is useful as a diagnostic estimate, but it is not a
cash settlement. Hyperliquid settles funding on discrete hourly boundaries.
Certified paper PnL may therefore use funding only when the position carries
complete user-funding settlement evidence (or an explicitly trusted exact
reconstruction). Crossing an hourly boundary by itself never manufactures cash.

This module is pure accounting: no network, no signature, no order.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

PERIODE_REGLEMENT_MS = 3_600_000

_CERTIFIED_SCALAR_SOURCES = frozenset(
    {"USERFUNDING", "USER_FUNDING", "VENUE_SETTLEMENT_EVENT", "EXACT_SETTLEMENT_RECONSTRUCTION"}
)


def _nombre(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def reglements_franchis(debut_ms: int, fin_ms: int, periode_ms: int = PERIODE_REGLEMENT_MS) -> int:
    """Count settlement boundaries in ]debut_ms, fin_ms]; never infer cash from them."""
    d, f = int(debut_ms), int(fin_ms)
    if f <= d or periode_ms <= 0:
        return 0
    return int(f // periode_ms) - int(d // periode_ms)


def _event_timestamp_ms(event: Mapping[str, Any]) -> int | None:
    for key in ("time", "timestamp_ms", "ts_ms", "exchange_ts_ms"):
        value = event.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _event_amount_usdt(event: Mapping[str, Any]) -> float | None:
    delta = event.get("delta")
    source = delta if isinstance(delta, Mapping) else event
    if isinstance(delta, Mapping):
        kind = str(delta.get("type") or "").lower()
        if kind and "funding" not in kind:
            return None
    for key in ("usdc", "amount_usdc", "amount_usdt", "pnl_usdt", "funding_usdc", "funding_usdt"):
        value = source.get(key)
        if value is None:
            continue
        try:
            amount = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return amount if math.isfinite(amount) else None
    return None


def _observed_settlements(
    position: Mapping[str, Any], *, entree_ms: int, now_ms: int
) -> tuple[float, int]:
    rows = None
    for key in ("funding_settlements", "user_funding_events", "userFunding"):
        candidate = position.get(key)
        if isinstance(candidate, list):
            rows = candidate
            break
    if rows is None:
        return 0.0, 0

    total = 0.0
    count = 0
    seen: set[tuple[Any, ...]] = set()
    for event in rows:
        if not isinstance(event, Mapping):
            continue
        ts = _event_timestamp_ms(event)
        amount = _event_amount_usdt(event)
        if ts is None or amount is None or ts < entree_ms or ts > int(now_ms):
            continue
        delta = event.get("delta")
        source = delta if isinstance(delta, Mapping) else event
        identity = (
            str(event.get("hash") or event.get("txHash") or ""),
            ts,
            str(source.get("coin") or position.get("coin") or ""),
            round(amount, 12),
        )
        if identity in seen:
            continue
        seen.add(identity)
        total += amount
        count += 1
    return total, count


def decouper(
    position: dict[str, Any], *, now_ms: int, periode_ms: int = PERIODE_REGLEMENT_MS
) -> dict[str, Any]:
    """Separate certified settlements from diagnostic accrual estimates."""
    accru_raw = _nombre(position.get("funding_accrued_usdt"))
    accru = accru_raw or 0.0
    entree = _nombre(position.get("entry_ts_ms"))
    if entree is None:
        return {
            "net_funding_settled": 0.0,
            "funding_accrual_estimate": round(accru, 8),
            "heures_reglees": 0.0,
            "fraction_heure_en_cours": 0.0,
            "funding_certified": False,
            "settlement_evidence_count": 0,
            "funding_certification_reason": "ENTRY_TIMESTAMP_MISSING",
        }

    duree_ms = max(0.0, float(now_ms) - entree)
    n_regl = reglements_franchis(int(entree), int(now_ms), periode_ms)
    heures_totales = duree_ms / float(periode_ms) if periode_ms > 0 else 0.0
    fraction = max(0.0, heures_totales - n_regl)

    if n_regl == 0:
        return {
            "net_funding_settled": 0.0,
            "funding_accrual_estimate": round(accru, 8),
            "heures_reglees": 0.0,
            "fraction_heure_en_cours": round(fraction, 6),
            "funding_certified": True,
            "settlement_evidence_count": 0,
            "funding_certification_reason": "NO_SETTLEMENT_BOUNDARY_CROSSED",
        }

    source = str(position.get("funding_settlement_source") or "").upper()
    settled_scalar = _nombre(position.get("net_funding_settled"))
    if settled_scalar is None:
        settled_scalar = _nombre(position.get("funding_settled_usdt"))
    if settled_scalar is not None and source in _CERTIFIED_SCALAR_SOURCES:
        return {
            "net_funding_settled": round(settled_scalar, 8),
            "funding_accrual_estimate": round(accru - settled_scalar, 8) if accru_raw is not None else 0.0,
            "heures_reglees": float(n_regl),
            "fraction_heure_en_cours": round(fraction, 6),
            "funding_certified": True,
            "settlement_evidence_count": int(position.get("funding_settlement_evidence_count") or 1),
            "funding_certification_reason": source,
        }

    observed, evidence_count = _observed_settlements(
        position, entree_ms=int(entree), now_ms=int(now_ms)
    )
    if position.get("funding_settlement_evidence_complete") is True:
        return {
            "net_funding_settled": round(observed, 8),
            "funding_accrual_estimate": round(accru - observed, 8) if accru_raw is not None else 0.0,
            "heures_reglees": float(n_regl),
            "fraction_heure_en_cours": round(fraction, 6),
            "funding_certified": True,
            "settlement_evidence_count": evidence_count,
            "funding_certification_reason": "COMPLETE_USER_FUNDING_EVENTS",
        }

    return {
        "net_funding_settled": 0.0,
        "funding_accrual_estimate": round(accru, 8),
        "heures_reglees": float(n_regl),
        "fraction_heure_en_cours": round(fraction, 6),
        "funding_certified": False,
        "settlement_evidence_count": evidence_count,
        "funding_certification_reason": "SETTLEMENT_EVIDENCE_INCOMPLETE",
    }


def agreger(positions: Any, *, now_ms: int, periode_ms: int = PERIODE_REGLEMENT_MS) -> dict[str, Any]:
    """Aggregate a portfolio while propagating funding-certification state."""
    regle = est = 0.0
    n_pos = evidence = 0
    all_certified = True
    for p in (positions.values() if isinstance(positions, dict) else (positions or ())):
        if not isinstance(p, dict):
            continue
        d = decouper(p, now_ms=now_ms, periode_ms=periode_ms)
        regle += float(d["net_funding_settled"])
        est += float(d["funding_accrual_estimate"])
        evidence += int(d["settlement_evidence_count"])
        n_pos += 1
        all_certified = all_certified and bool(d["funding_certified"])
    return {
        "net_funding_settled": round(regle, 8),
        "funding_accrual_estimate": round(est, 8),
        "funding_total_couru": round(regle + est, 8),
        "positions": n_pos,
        "settlement_evidence_count": evidence,
        "funding_certified": all_certified,
        "funding_certification_status": "CERTIFIED" if all_certified else "UNMEASURABLE",
    }


def pnl_stable(realise_usd: float, net_funding_settled: float) -> float:
    """Combine realized PnL with already-certified settled funding only."""
    return round(float(realise_usd or 0.0) + float(net_funding_settled or 0.0), 8)


__all__ = ["PERIODE_REGLEMENT_MS", "reglements_franchis", "decouper", "agreger", "pnl_stable"]
