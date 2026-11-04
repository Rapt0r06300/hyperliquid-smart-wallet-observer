"""P1A — construire les marks LIQUIDABLES exécutables (LONG@bid, SHORT@ask) pour l'equity autoritaire.

Tout le calcul d'equity liquidable EXISTE déjà (`LedgerPosition.liquidatable_unrealized`,
`PaperLedger.mark_to_market(liquidatable_marks=...)`, `CapitalAccountingTracker`, `equity_canonique`).
Le SEUL trou mesuré : **aucun appelant ne fournit `liquidatable_marks`** → `last_liquidatable_price`
reste `None` → l'equity autoritaire tombe en `UNMEASURABLE_NO_EXECUTABLE_EXIT` en permanence.

Ce module produit exactement ce dict, à partir du carnet CAUSAL : une position **LONG** se dénoue en
**VENDANT au meilleur BID** exécutable ; une position **SHORT** en **ACHETANT au meilleur ASK**.
Cross-venue : chaque jambe est marquée de son côté de sortie.

Règle dure : sans bid/ask exécutable pour une position, **pas** de mark liquidable pour elle (elle
reste `UNMEASURABLE`), JAMAIS un repli silencieux sur le mid. Le mid reste diagnostic. La clé de
sortie reflète `PaperLedger._position_mark` (`position_id`, sinon `COIN:SIDE`). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from hl_observer.instrument_identity import preserve_native_instrument_symbol

SCHEMA_VERSION = "hypersmart.liquidatable_marks.v1"

#: Côté de SORTIE d'une position : une LONG vend (bid), une SHORT achète (ask).
_LONG = ("LONG", "BUY", "B", "BID", "1", "+1")
_SHORT = ("SHORT", "SELL", "S", "ASK", "-1")


def _pos(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def _attr(p: Any, name: str) -> Any:
    if isinstance(p, Mapping):
        return p.get(name)
    return getattr(p, name, None)


def _bbo(entry: Any) -> tuple[float | None, float | None]:
    """Extrait (bid, ask) d'un `{"bid":..,"ask":..}` / `{"best_bid":..,"best_ask":..}` ou `(bid, ask)`."""
    if isinstance(entry, Mapping):
        return _pos(entry.get("bid", entry.get("best_bid"))), _pos(entry.get("ask", entry.get("best_ask")))
    try:
        return _pos(entry[0]), _pos(entry[1])
    except (TypeError, IndexError, KeyError):
        return None, None


def mark_liquidatable(side: object, *, best_bid: object = None, best_ask: object = None) -> float | None:
    """Prix de dénouement exécutable d'une position. LONG→bid, SHORT→ask. `None` si le côté manque."""
    s = str(side or "").strip().upper()
    if s in _LONG:
        return _pos(best_bid)      # sortir d'une LONG = vendre dans le bid
    if s in _SHORT:
        return _pos(best_ask)      # sortir d'une SHORT = acheter à l'ask
    return None


def _cle_sortie(coin: str, side: str, position_id: object) -> str:
    if position_id not in (None, ""):
        return str(position_id)
    return f"{preserve_native_instrument_symbol(coin)}:{str(side).upper()}"


def marks_depuis_bbo(positions: Iterable[Any], bbo: Mapping[str, Any]) -> dict[str, float]:
    """Construit le dict `liquidatable_marks` attendu par `PaperLedger.mark_to_market`.

    `positions` : itérable de `LedgerPosition` ou de dicts `{position_id, coin, side}`.
    `bbo` : mapping `coin -> {"bid":.., "ask":..}` (ou `(bid, ask)`).
    Clé de sortie = `position_id` si présent, sinon `COIN:SIDE`. Une position sans bid/ask exécutable
    côté sortie est **omise** (elle restera UNMEASURABLE côté equity autoritaire — c'est voulu)."""
    out: dict[str, float] = {}
    for p in positions:
        coin, side = _attr(p, "coin"), _attr(p, "side")
        if not coin or not side:
            continue
        entry = bbo.get(preserve_native_instrument_symbol(coin)) if isinstance(bbo, Mapping) else None
        bid, ask = _bbo(entry or {})
        mk = mark_liquidatable(side, best_bid=bid, best_ask=ask)
        if mk is None:
            continue
        out[_cle_sortie(str(coin), str(side), _attr(p, "position_id"))] = mk
    return out


def marks_depuis_execution_truths(positions: Iterable[Any], truths: Mapping[str, Any]) -> dict[str, float]:
    """Variante câblage : `truths` = mapping `coin -> objet portant best_bid/best_ask` (ex. `ExecutionTruth`)."""
    bbo: dict[str, Any] = {}
    for coin, t in (truths or {}).items():
        bbo[preserve_native_instrument_symbol(coin)] = {
            "bid": _attr(t, "best_bid"),
            "ask": _attr(t, "best_ask"),
        }
    return marks_depuis_bbo(positions, bbo)


def couverture(positions: Iterable[Any], marks: Mapping[str, float]) -> dict[str, Any]:
    """Part des positions réellement marquées liquidables (le reste = UNMEASURABLE, nommé et compté)."""
    pos = list(positions)
    total = len(pos)
    mesurees = 0
    manquantes: list[str] = []
    for p in pos:
        coin, side = _attr(p, "coin"), _attr(p, "side")
        cle = _cle_sortie(str(coin), str(side), _attr(p, "position_id"))
        alt = f"{preserve_native_instrument_symbol(coin)}:{str(side).upper()}"
        if cle in marks or alt in marks or preserve_native_instrument_symbol(coin) in marks:
            mesurees += 1
        else:
            manquantes.append(cle)
    return {
        "schema_version": SCHEMA_VERSION,
        "n_positions": total,
        "n_liquidatable_mesurees": mesurees,
        "n_unmeasurable": total - mesurees,
        "positions_unmeasurable": manquantes,
        "couverture": round(mesurees / total, 6) if total else None,
        "real_execution": False,
    }


def liquidatable_marks_report(
    positions: Iterable[Any],
    bbo: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an executable-bid/ask report with no mid-price fallback."""
    position_rows = list(positions)
    marks = marks_depuis_bbo(position_rows, bbo)
    coverage = couverture(position_rows, marks)
    coverage.update(
        {
            "marks": dict(marks),
            "equity_basis": "EXECUTABLE_EXIT_BID_ASK_ONLY",
            "mid_price_fallback": False,
            "status": "MEASURED" if coverage["n_unmeasurable"] == 0 else "UNMEASURABLE",
        }
    )
    return coverage


def _marks_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _marks_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _marks_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def liquidatable_marks_safety_receipt(result: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(result, Mapping) and result.get("schema_version") == SCHEMA_VERSION and result.get("real_execution") is False and result.get("mid_price_fallback") is False
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDATABLE_MARKS_SAFE" if valid else "LIQUIDATABLE_MARKS_UNSAFE", fail_closed=not valid)


def marks_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_FIELD_PRESENT" if valid else "MARKS_FIELD_MISSING", field=field, fail_closed=not valid)


def marks_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_FIELD_NON_NULL" if valid else "MARKS_FIELD_NULL", field=field, fail_closed=not valid)


def marks_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_FIELD_TYPE_VALID" if valid else "MARKS_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def marks_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _marks_finite(value)
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_VALUE_FINITE" if valid else "MARKS_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def marks_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _marks_integer(event_ts_ms) and _marks_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_EVENT_WITHIN_CUTOFF" if valid else "MARKS_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def marks_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _marks_integer(event_ts_ms) and _marks_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_EVENT_AGE_VALID" if valid else "MARKS_EVENT_TOO_OLD", fail_closed=not valid)


def marks_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_EVENTS_UNIQUE" if valid else "MARKS_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def marks_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _marks_integer(attempts) and _marks_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_RETRY_BOUNDED" if valid else "MARKS_RETRY_UNSAFE", fail_closed=not valid)


def marks_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_REPLAY_DETERMINISTIC" if valid else "MARKS_REPLAY_DIVERGED", fail_closed=not valid)


def marks_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_FILLS_UNIQUE" if valid else "MARKS_FILL_DUPLICATED", fail_closed=not valid)


def marks_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_REJECTION_NO_DEBIT" if valid else "MARKS_REJECTION_DEBITED", fail_closed=not valid)


def marks_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    values = tuple(float(value) if _marks_finite(value) else None for value in (close_quantity, open_quantity, fee_amount))
    close, open_size, fee = values
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_PARTIAL_CLOSE_COSTED" if valid else "MARKS_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def marks_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    values = tuple(float(value) if _marks_finite(value) else None for value in (close_quantity, open_quantity, released_margin))
    close, open_size, release = values
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_TOTAL_CLOSE_RELEASED" if valid else "MARKS_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def marks_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    values = tuple(float(value) if _marks_finite(value) else None for value in (mark_price, bid, ask))
    mark, best_bid, best_ask = values
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_MARK_LIQUIDABLE" if valid else "MARKS_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def marks_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = float(balance) if _marks_finite(balance) else None
    valid = value is not None and value >= 0
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_BALANCE_NON_NEGATIVE" if valid else "MARKS_BALANCE_NEGATIVE", fail_closed=not valid)


def marks_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = float(amount) if _marks_finite(amount) else None
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_FUNDING_SIGN_VALID" if valid else "MARKS_FUNDING_SIGN_INVALID", fail_closed=not valid)


def marks_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount = float(fee_amount) if _marks_finite(fee_amount) else None
    rate = float(token_to_pnl_rate) if _marks_finite(token_to_pnl_rate) else None
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_CONVERSION_PROVEN" if valid else "MARKS_CONVERSION_MISSING", fail_closed=not valid)


def marks_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_COMMIT_ATOMIC" if valid else "MARKS_COMMIT_PARTIAL", fail_closed=not valid)


def marks_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _marks_base("PROVEN" if valid else "REJECTED", verdict="MARKS_WRITES_UNIQUE" if valid else "MARKS_DOUBLE_WRITE", fail_closed=not valid)


__all__ = [
    "SCHEMA_VERSION", "mark_liquidatable", "marks_depuis_bbo",
    "marks_depuis_execution_truths", "couverture", "liquidatable_marks_report",
    "liquidatable_marks_safety_receipt", "marks_required_field_receipt", "marks_null_field_receipt",
    "marks_field_type_receipt", "marks_finite_receipt", "marks_cutoff_receipt", "marks_age_receipt",
    "marks_duplicate_receipt", "marks_retry_receipt", "marks_replay_receipt", "marks_fill_duplicate_receipt",
    "marks_rejection_no_debit_receipt", "marks_partial_close_receipt", "marks_total_close_release_receipt",
    "marks_mark_liquidability_receipt", "marks_balance_receipt", "marks_funding_sign_receipt",
    "marks_conversion_receipt", "marks_commit_receipt", "marks_concurrent_write_receipt",
]
