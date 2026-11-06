"""LES COINS QU'ON REGARDE VRAIMENT -- et pourquoi cette liste etait VIDE (2026-07-11).

LE BUG, ET IL A ANNULE TOUT LE RESTE.

Le poller de carnet L2 (`l2_snapshot_cache._loop`) demandait sa liste de coins a
`DEFAULT_EDGE_TREND_RECORDER.coins()`. Or `record_edge_observation()` -- la seule fonction qui
remplit ce recorder -- **n'est appelee NULLE PART dans tout le code**. Elle est exportee dans
`__all__`, et c'est tout.

Consequence en chaine :

    recorder vide -> coins() rend []  ->  le poller sonde une liste VIDE
                                      ->  le carnet L2 n'est JAMAIS recupere
                                      ->  live_costs_for(coin) ne trouve jamais rien
                                      ->  spread/slippage/profondeur retombent sur des CONSTANTES
                                          (6 bps, 6 bps, 50 000 $) -- identiques pour BTC et pour
                                          un meme coin illiquide
                                      ->  et aucune donnee de carnet n'est enregistree, donc le
                                          market making est INTESTABLE.

Le flag `HYPERSMART_V26_BOOK_POLLER=1` etait allume. Le code etait cable. Le recorder etait branche.
**Et rien ne se passait**, parce qu'une liste vide ne fait pas de bruit.

C'est le meme motif que les autres pieges de ce projet : une capacite presente, un interrupteur
allume, et une donnee absente qui ne se plaint pas.

CE MODULE : un registre explicite des coins d'interet, alimente la ou les coins sont REELLEMENT
observes (signaux de leaders, candidats). Borne, avec TTL, thread-safe -- et surtout **il sait dire
qu'il est vide**, au lieu de le taire.

PUR (sauf l'horloge, injectable). Aucun ordre reel.
"""
from __future__ import annotations

import threading
import time
import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Any

# Bornes : un registre non borne finirait par faire sonder 300 marches toutes les 30 s.
MAX_COINS = 200
TTL_S = 900.0                      # un coin plus vu depuis 15 min sort du radar

_lock = threading.Lock()
_vus: dict[str, float] = {}        # coin -> derniere observation (epoch s)


def note_coin(coin: str, *, now_s: float | None = None) -> bool:
    """« On vient de voir ce marche. » Appele la ou un signal/candidat existe VRAIMENT."""
    c = str(coin or "").strip().upper()
    if not c:
        return False
    t = float(now_s if now_s is not None else time.time())
    with _lock:
        _vus[c] = t
        if len(_vus) > MAX_COINS:
            # on jette les plus anciens, jamais les plus recents
            for vieux, _ in sorted(_vus.items(), key=lambda kv: kv[1])[: len(_vus) - MAX_COINS]:
                _vus.pop(vieux, None)
    return True


def note_coins(coins: Any, *, now_s: float | None = None) -> int:
    n = 0
    for c in (coins or []):
        if note_coin(c, now_s=now_s):
            n += 1
    return n


def coins(*, limit: int = 20, now_s: float | None = None) -> list[str]:
    """Les coins vus recemment, du PLUS RECENT au plus ancien. TTL applique."""
    t = float(now_s if now_s is not None else time.time())
    with _lock:
        vivants = [(c, ts) for c, ts in _vus.items() if (t - ts) <= TTL_S]
    vivants.sort(key=lambda kv: -kv[1])
    return [c for c, _ in vivants[: max(0, int(limit))]]


def is_empty(*, now_s: float | None = None) -> bool:
    return not coins(limit=1, now_s=now_s)


def health(*, now_s: float | None = None) -> dict[str, Any]:
    """L'ETAT VIDE DOIT ETRE VISIBLE. C'est exactement ce qui a manque pendant des semaines."""
    actifs = coins(limit=MAX_COINS, now_s=now_s)
    return {
        "n_coins": len(actifs),
        "vide": not actifs,
        # Si `vide` est vrai en plein run, le carnet n'est PAS collecte et les couts sont des
        # constantes. Ce n'est pas un detail d'observabilite : c'est un moteur a l'arret.
        "consequence_si_vide": (
            "aucun carnet L2 collecte -> spread/slippage/profondeur = constantes -> "
            "les gates de liquidite et de cout ne mesurent RIEN"
        ),
        "coins": actifs[:20],
        "real_execution": False,
    }


def clear() -> None:
    with _lock:
        _vus.clear()


def validate_okx_linear_usdt_swap(item: Mapping[str, object]) -> tuple[bool, str]:
    """Validate the immutable contract metadata used by the active OKX feed."""
    inst_id = str(item.get("instId") or "").strip().upper()
    if not inst_id.endswith("-USDT-SWAP"):
        return False, "NOT_USDT_SWAP"
    if str(item.get("instType") or "").strip().upper() != "SWAP":
        return False, "NOT_SWAP"
    if str(item.get("state") or "").strip().lower() != "live":
        return False, "NOT_LIVE"
    if str(item.get("ctType") or "").strip().lower() != "linear":
        return False, "NOT_LINEAR"
    if str(item.get("settleCcy") or "").strip().upper() != "USDT":
        return False, "SETTLEMENT_CURRENCY_MISMATCH"
    if str(item.get("quoteCcy") or "").strip().upper() != "USDT":
        return False, "QUOTE_CURRENCY_MISMATCH"
    base = inst_id.split("-", 1)[0]
    if str(item.get("ctValCcy") or "").strip().upper() != base:
        return False, "NOMINAL_CURRENCY_MISMATCH"

    parsed: dict[str, float] = {}
    for field in ("ctVal", "ctMult", "lotSz", "minSz", "tickSz"):
        try:
            value = float(item.get(field))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False, f"INVALID_{field.upper()}"
        if not math.isfinite(value) or value <= 0.0:
            return False, f"INVALID_{field.upper()}"
        parsed[field] = value

    lot = parsed["lotSz"]
    minimum = parsed["minSz"]
    lots = minimum / lot
    if minimum < lot or not math.isclose(lots, round(lots), rel_tol=1e-9, abs_tol=1e-9):
        return False, "MIN_SIZE_NOT_ALIGNED_TO_LOT"
    for field in ("listTime", "expTime"):
        if field in item and item.get(field) not in (None, ""):
            if validate_okx_timestamp_ms(item.get(field))[0] is False:
                return False, f"INVALID_{field.upper()}"
    return True, "OK"


def validate_okx_timestamp_ms(value: object) -> tuple[bool, str]:
    """Accept only finite epoch timestamps expressed in milliseconds."""
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return False, "INVALID_TIMESTAMP"
    if parsed < 100_000_000_000 or parsed > 100_000_000_000_000:
        return False, "TIMESTAMP_NOT_MILLISECONDS"
    return True, "OK"


def validate_okx_paper_notional(
    item: Mapping[str, object],
    *,
    reference_price: object,
    paper_notional_usd: object = 350.0,
) -> tuple[bool, str]:
    """Reject a contract whose minimum size cannot fit the paper notional."""
    try:
        price = float(reference_price)
        budget = float(paper_notional_usd)
        minimum = float(item.get("minSz"))  # type: ignore[arg-type]
        contract_value = float(item.get("ctVal"))  # type: ignore[arg-type]
        multiplier = float(item.get("ctMult"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False, "PAPER_NOTIONAL_INPUT_MISSING"
    if not all(math.isfinite(v) and v > 0.0 for v in (price, budget, minimum, contract_value, multiplier)):
        return False, "PAPER_NOTIONAL_INPUT_INVALID"
    required = minimum * contract_value * multiplier * price
    return (True, "OK") if required <= budget else (False, "MIN_SIZE_EXCEEDS_PAPER_NOTIONAL")


def quantize_okx_price(
    price: object,
    tick_size: object,
    *,
    side: str = "buy",
) -> float | None:
    """Quantize a repriced value to the venue tick without float drift."""
    try:
        value = Decimal(str(price))
        tick = Decimal(str(tick_size))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite() or not tick.is_finite() or value <= 0 or tick <= 0:
        return None
    units = value / tick
    rounding = ROUND_CEILING if str(side).lower() == "sell" else ROUND_FLOOR
    return float(units.to_integral_value(rounding=rounding) * tick)


__all__ = [
    "MAX_COINS",
    "TTL_S",
    "clear",
    "coins",
    "health",
    "is_empty",
    "note_coin",
    "note_coins",
    "quantize_okx_price",
    "validate_okx_linear_usdt_swap",
    "validate_okx_paper_notional",
    "validate_okx_timestamp_ms",
]
