"""[ALL #90] CLOSE-TYPE TAXONOMY : distinguer les manières dont une position se FERME — succès économique, timeout,
insufficient liquidity, stale market, retry exhausted, emergency hedge, risk stop. Toutes les clôtures ne se valent
pas : un succès économique et un risk-stop n'ont pas le même sens pour le scoreboard. Non reconnu → UNKNOWN_CLOSE
(jamais requalifié en succès). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

ECONOMIC_SUCCESS = "ECONOMIC_SUCCESS"
TIMEOUT = "TIMEOUT"
INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
STALE_MARKET = "STALE_MARKET"
RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
EMERGENCY_HEDGE = "EMERGENCY_HEDGE"
RISK_STOP = "RISK_STOP"
UNKNOWN_CLOSE = "UNKNOWN_CLOSE"

TYPES = (ECONOMIC_SUCCESS, TIMEOUT, INSUFFICIENT_LIQUIDITY, STALE_MARKET, RETRY_EXHAUSTED,
         EMERGENCY_HEDGE, RISK_STOP, UNKNOWN_CLOSE)

_MOTIFS = {
    ECONOMIC_SUCCESS: ("SUCCESS", "TARGET", "TAKE_PROFIT", "TP", "ECON"),
    TIMEOUT: ("TIMEOUT", "DEADLINE", "EXPIRED"),
    INSUFFICIENT_LIQUIDITY: ("INSUFFICIENT_LIQUIDITY", "NO_LIQUIDITY", "THIN"),
    STALE_MARKET: ("STALE", "NO_DATA", "FROZEN"),
    RETRY_EXHAUSTED: ("RETRY_EXHAUSTED", "MAX_RETRY", "GIVE_UP"),
    EMERGENCY_HEDGE: ("EMERGENCY", "PANIC", "FORCED_UNWIND"),
    RISK_STOP: ("RISK", "STOP_LOSS", "SL", "LIQUIDATION", "DRAWDOWN"),
}


def classifier(signal: Any) -> dict[str, Any]:
    """Mappe un motif de clôture vers un type. Reconnaissable dans l'ordre de priorité ci-dessous, sinon
    UNKNOWN_CLOSE (une clôture non classée n'est jamais comptée comme un succès)."""
    s = str(signal).upper()
    for t in (RISK_STOP, EMERGENCY_HEDGE, RETRY_EXHAUSTED, STALE_MARKET, INSUFFICIENT_LIQUIDITY, TIMEOUT,
              ECONOMIC_SUCCESS):
        if any(m in s for m in _MOTIFS[t]):
            return {"type": t, "succes_economique": (t == ECONOMIC_SUCCESS), "reconnu": True}
    return {"type": UNKNOWN_CLOSE, "succes_economique": False, "reconnu": False}


__all__ = ["classifier", "TYPES", "ECONOMIC_SUCCESS", "TIMEOUT", "INSUFFICIENT_LIQUIDITY", "STALE_MARKET",
           "RETRY_EXHAUSTED", "EMERGENCY_HEDGE", "RISK_STOP", "UNKNOWN_CLOSE"]
