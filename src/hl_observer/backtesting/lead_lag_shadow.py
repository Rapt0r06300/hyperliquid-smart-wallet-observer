"""LEAD-LAG SHADOW — Binance mène, HL suit ? Mesure NETTE, méthodo gelée (23/07, chantier ARB).

Corrections méthodo de Flo, AVANT la collecte :
  1. HL n'émet le BBO que quand il change sur un bloc -> on MESURE d'abord la distribution réelle des
     intervalles entre messages (`distribution_intervalles`) et on ne GARDE un horizon que si la
     donnée permet de l'observer (`horizons_observables` : un horizon < ~2× l'intervalle médian HL
     est illusoire, on le jette).
  2. Le CHOC se détecte sur les TRADES Binance (aggTrade), pas sur le mid BBO ; l'ENTRÉE se simule au
     bid/ask HL réellement dispo (demi-spread réel), avec la profondeur au top ; horloge MONOTONE.
  3. Coins, horizons, seuils, critère de réussite GELÉS avant le live-forward (`geler_config`) — on ne
     les réajuste pas après avoir vu le PnL.
  4. On mesure l'espérance nette, la CAPACITÉ, le DRAWDOWN et la STABILITÉ PAR PÉRIODE — pas le winrate.

Coins de CONTRÔLE gardés : si le contrôle gagne autant, c'est un artefact d'horloge, pas un edge.
PAPER/shadow only : mesurer n'est pas trader.
"""
from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import statistics as st
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.backtesting.anti_overfit_gate import evaluer as evaluer_dsr
from hl_observer.backtesting.anti_overfit_gate import sharpe
from hl_observer.backtesting.lead_lag_evidence import (
    REQUIRED_CRITERIA,
    SCHEMA_VERSION,
    SUPPORTED_HORIZONS_MS,
    estimate_alpha_half_life_ms,
)
from hl_observer.backtesting.quant_methods import block_bootstrap
from hl_observer.backtesting.robustesse_selection import pbo_cscv
from hl_observer.config.frais_venues import frais_taker_bps

TAPE = Path("runtime") / "data" / "bbo_tape.jsonl"
CONFIG_GELE = Path("runtime") / "data" / "lead_lag_config_gele.json"
GLOBAL_TRIAL_LEDGER = Path("runtime") / "research_lab" / "ledgers" / "global_trials.jsonl"
SEUIL_CHOC_BPS = 8.0
FRAIS_SLIPPAGE_BPS = 2.0 * frais_taker_bps("HYPERLIQUID")
HORIZONS_MS = (50.0, 100.0, 250.0, 500.0, 1000.0)
MIN_CHOCS = 30
N_PERIODES = 4                     # pour juger la stabilité dans le temps
DEFAULT_HISTORY_SOURCES = 8
CAMPAIGN_HORIZON_MS = 1000.0
CAMPAIGN_NOTIONAL_USD = 25.0
CAMPAIGN_MAX_REFERENCE_LAG_MS = 30_000.0
CAMPAIGN_MAX_EXIT_LAG_MS = 30_000.0
CAMPAIGN_EXECUTION_MODEL = "causal_marketable_top_v3"


def walk_forward_protocol_signature() -> dict[str, Any]:
    """Return immutable strategy fields, excluding append-only dataset shape."""

    return {
        "seuil_choc_bps": SEUIL_CHOC_BPS,
        "frais_slippage_bps": FRAIS_SLIPPAGE_BPS,
        "horizons_ms": list(HORIZONS_MS),
        "economic_horizon_ms": CAMPAIGN_HORIZON_MS,
        "economic_notional_usd": CAMPAIGN_NOTIONAL_USD,
        "max_reference_lag_ms": CAMPAIGN_MAX_REFERENCE_LAG_MS,
        "max_exit_lag_ms": CAMPAIGN_MAX_EXIT_LAG_MS,
        "execution_model": CAMPAIGN_EXECUTION_MODEL,
        "minimum_shocks": MIN_CHOCS,
        "timestamp_clock": "ts_wall_ms_or_recv_wall_ts_ms;recu_ns_fallback",
    }


def selectionner_sources(
    root: str | Path,
    *,
    include_history: bool = False,
    max_history_sources: int = DEFAULT_HISTORY_SOURCES,
) -> list[Path]:
    """Return a deterministic set of local tapes used by the replay.

    The live tape is always first.  Historical gzip shards are selected by
    their stable filename timestamp, newest first.  ``bbo_tape.jsonl.prev``
    is used only after shards because older versions generally did not record
    Binance trades, which are mandatory for this strategy.
    """

    data = Path(root) / "runtime" / "data"
    selected = [data / "bbo_tape.jsonl"]
    if not include_history:
        return [path for path in selected if path.is_file()]
    historical = sorted(
        [
            *list((data / "bbo_shards").glob("*.jsonl.gz")),
            *list((data / "bbo_shards_archive").glob("*.jsonl.gz")),
        ],
        key=lambda path: path.name,
        reverse=True,
    )
    limit = max(0, int(max_history_sources))
    selected.extend(historical[:limit])
    previous = data / "bbo_tape.jsonl.prev"
    if previous.is_file() and len(historical) < limit:
        selected.append(previous)
    return [path for path in selected if path.is_file()]


def _iter_lines(path: Path):
    opener = gzip.open if path.name.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def _event_time_ns(row: dict[str, Any]) -> int | None:
    """Use a cross-process wall clock; monotonic ``recu_ns`` is only fallback."""

    wall_ms = row.get("ts_wall_ms", row.get("recv_wall_ts_ms"))
    try:
        if wall_ms is not None:
            return int(float(wall_ms) * 1_000_000.0)
        return int(row["recu_ns"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _dedupe_key(row: dict[str, Any], timestamp_ns: int) -> tuple[Any, ...]:
    event_id = row.get("event_id")
    if event_id:
        return ("event_id", str(event_id))
    venue = str(row.get("venue") or "")
    coin = str(row.get("coin") or "").upper()
    if venue == "BIN_TRADE":
        return (venue, coin, timestamp_ns, row.get("px"), row.get("side"), row.get("sz"))
    return (
        venue,
        coin,
        timestamp_ns,
        row.get("bid"),
        row.get("ask"),
        row.get("mid"),
        row.get("bid_sz", row.get("bid_size")),
        row.get("ask_sz", row.get("ask_size")),
    )


def charger_tape(
    root: str | Path,
    *,
    include_history: bool = False,
    max_history_sources: int = DEFAULT_HISTORY_SOURCES,
    sources: list[Path] | None = None,
    return_meta: bool = False,
) -> dict[str, dict[str, list]] | tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Load causal HL quotes and Binance trades from exact local sources.

    Modern tapes are compared with wall timestamps because ``recu_ns`` is a
    process-local monotonic clock and cannot be ordered across restarts.
    """

    from collections import defaultdict
    root_path = Path(root).resolve()
    selected = list(sources) if sources is not None else selectionner_sources(
        root_path,
        include_history=include_history,
        max_history_sources=max_history_sources,
    )
    par: dict[str, dict[str, list]] = defaultdict(lambda: {"HL": [], "BIN": [], "TRADE": []})
    seen: set[tuple[Any, ...]] = set()
    lines_read = duplicates = invalid = 0
    consumed: list[str] = []
    for path_value in selected:
        path = Path(path_value)
        if not path.is_absolute():
            path = root_path / path
        if not path.is_file():
            continue
        try:
            consumed.append(path.relative_to(root_path).as_posix())
        except ValueError:
            consumed.append(str(path))
        for line in _iter_lines(path):
            lines_read += 1
            try:
                d = json.loads(line)
                coin = str(d["coin"]).upper()
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            venue = d.get("venue")
            if venue not in {"HL", "BIN_TRADE"}:
                continue
            timestamp_ns = _event_time_ns(d)
            if timestamp_ns is None:
                invalid += 1
                continue
            key = _dedupe_key(d, timestamp_ns)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            if venue == "HL":
                mid = _flt(d.get("mid"))
                if mid:
                    par[coin]["HL"].append(
                        (
                            timestamp_ns,
                            mid,
                            _flt(d.get("bid")) or mid,
                            _flt(d.get("ask")) or mid,
                            _positive_or_none(d.get("bid_sz", d.get("bid_size"))),
                            _positive_or_none(d.get("ask_sz", d.get("ask_size"))),
                        )
                    )
            else:
                price = _flt(d.get("px"))
                if price:
                    par[coin]["TRADE"].append(
                        (timestamp_ns, price, 1.0 if d.get("side") == "BUY" else -1.0)
                    )
    for c in par:
        for k in par[c]:
            par[c][k].sort()
    result = dict(par)
    meta = {
        "timestamp_clock": "ts_wall_ms_or_recv_wall_ts_ms;recu_ns_fallback",
        "sources": consumed,
        "sources_count": len(consumed),
        "lines_read": lines_read,
        "relevant_unique_events": len(seen),
        "duplicates_rejected": duplicates,
        "invalid_rows": invalid,
        "complete_sources": True,
    }
    return (result, meta) if return_meta else result


def _flt(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _positive_or_none(value: Any) -> float | None:
    parsed = _flt(value)
    return parsed if parsed is not None and parsed > 0 else None


def distribution_intervalles(evenements: list) -> dict[str, float]:
    """Percentiles (ms) des intervalles entre messages — DIT si un horizon est observable."""
    ns = [e[0] for e in evenements]
    if len(ns) < 5:
        return {"n": len(ns), "p50_ms": None, "p90_ms": None}
    d = sorted((ns[i] - ns[i - 1]) / 1e6 for i in range(1, len(ns)))
    return {"n": len(ns), "p50_ms": round(d[len(d) // 2], 2),
            "p90_ms": round(d[int(len(d) * 0.9)], 2), "p99_ms": round(d[int(len(d) * 0.99)], 2)}


def horizons_observables(dist_hl: dict, horizons) -> list[float]:
    """On ne garde un horizon que s'il est >= 2× l'intervalle médian HL : sinon la 'réaction' à cet
    horizon n'est PAS observable (HL n'a pas encore réémis). C'est le garde-fou n°1 de Flo."""
    p50 = dist_hl.get("p50_ms")
    if not p50:
        return []
    return [h for h in horizons if h >= 2.0 * p50]


FENETRE_GROUPE_MS = 100.0          # deux chocs à moins de ça = le MÊME mouvement -> groupés (1 seul)


def detecter_chocs(trades: list, *, seuil_bps: float,
                   fenetre_groupe_ms: float = FENETRE_GROUPE_MS) -> list[tuple[int, float]]:
    """Chocs exécutables depuis les TRADES Binance : un saut de prix >= seuil entre trades consécutifs.
    Les chocs qui SE CHEVAUCHENT (< fenetre_groupe_ms) sont GROUPÉS en un seul (sinon on compte 5 fois
    le même mouvement et on gonfle l'échantillon). Retour [(recu_ns, direction)]."""
    out = []
    dernier_ns = -1e30
    for i in range(1, len(trades)):
        if trades[i - 1][1] <= 0:
            continue
        mv = (trades[i][1] - trades[i - 1][1]) / trades[i - 1][1] * 1e4
        if abs(mv) < seuil_bps:
            continue
        t = trades[i][0]
        if (t - dernier_ns) / 1e6 < fenetre_groupe_ms:        # chevauche le choc précédent -> groupé
            continue
        out.append((t, 1.0 if mv > 0 else -1.0))
        dernier_ns = t
    return out


def _hl_a(hl: list, t_ns: int) -> tuple | None:
    """Last quote at-or-before ``t_ns`` (diagnostics only)."""

    i = bisect.bisect_right([e[0] for e in hl], t_ns) - 1
    return hl[i] if i >= 0 else None


def _hl_apres(hl: list, t_ns: int, *, timestamps: list[int] | None = None) -> tuple | None:
    """Return the first quote observable at-or-after ``t_ns``."""

    times = timestamps if timestamps is not None else [event[0] for event in hl]
    index = bisect.bisect_left(times, t_ns)
    return hl[index] if index < len(hl) else None


def _top_capacity_usd(quote: tuple, *, side: str) -> float | None:
    if len(quote) < 6:
        return None
    if side == "BUY":
        price, size = _flt(quote[3]), _positive_or_none(quote[5])
    else:
        price, size = _flt(quote[2]), _positive_or_none(quote[4])
    if price is None or size is None:
        return None
    return price * size


def episodes_par_horizon(
    hl: list,
    chocs: list,
    *,
    frais_slippage_bps: float,
    horizons_ms,
    coin: str = "",
    notional_usd: float = 25.0,
    max_reference_lag_ms: float = CAMPAIGN_MAX_REFERENCE_LAG_MS,
    max_exit_lag_ms: float = CAMPAIGN_MAX_EXIT_LAG_MS,
) -> dict[float, list[dict[str, Any]]]:
    """Build causal closed paper episodes from marketable HL quotes.

    Quotes without top sizes remain valid for directional research, but they
    are explicitly non-liquidatable and cannot certify an economic result.
    """

    out: dict[float, list[dict[str, Any]]] = {h: [] for h in horizons_ms}
    if not hl:
        return out
    times = [event[0] for event in hl]
    requested = max(0.0, float(notional_usd))
    for t0, direction in chocs:
        entry = _hl_apres(hl, t0, timestamps=times)
        if entry is None:
            continue
        reference = _hl_a(hl, t0)
        reference_observed_before_signal = reference is not None
        reference_age_ms = (
            (t0 - int(reference[0])) / 1e6
            if reference_observed_before_signal
            else None
        )
        reference_fresh = bool(
            reference_observed_before_signal
            and reference_age_ms is not None
            and 0.0 <= reference_age_ms <= float(max_reference_lag_ms)
        )
        if reference is None:
            # Keep a directional diagnostic row, but never certify it as
            # liquidatable economic evidence without a pre-signal mark.
            reference = entry
        entry_price = entry[3] if direction > 0 else entry[2]
        entry_side = "BUY" if direction > 0 else "SELL"
        exit_side = "SELL" if direction > 0 else "BUY"
        if entry_price <= 0:
            continue
        entry_capacity = _top_capacity_usd(entry, side=entry_side)
        for horizon in horizons_ms:
            target_ns = t0 + int(float(horizon) * 1e6)
            if entry[0] > target_ns:
                continue
            exit_quote = _hl_apres(hl, target_ns, timestamps=times)
            if exit_quote is None or exit_quote[0] <= entry[0]:
                continue
            exit_observation_lag_ms = (exit_quote[0] - target_ns) / 1e6
            exit_quote_fresh = bool(
                0.0 <= exit_observation_lag_ms <= float(max_exit_lag_ms)
            )
            exit_price = exit_quote[2] if direction > 0 else exit_quote[3]
            if exit_price <= 0:
                continue
            exit_capacity = _top_capacity_usd(exit_quote, side=exit_side)
            capacity = (
                min(entry_capacity, exit_capacity)
                if entry_capacity is not None and exit_capacity is not None
                else None
            )
            liquidatable = (
                reference_fresh
                and exit_quote_fresh
                and capacity is not None
                and requested > 0
                and capacity >= requested
            )
            reference_mid = float(reference[1])
            entry_mid = float(entry[1])
            exit_mid = float(exit_quote[1])
            quantity = requested / float(entry_price) if requested > 0 else 0.0
            gross_from_reference = quantity * direction * (exit_mid - reference_mid)
            signed_latency = quantity * direction * (entry_mid - reference_mid)
            latency_cost = max(0.0, signed_latency)
            latency_benefit = max(0.0, -signed_latency)
            gross_pnl = gross_from_reference + latency_benefit
            delayed_mid_pnl = quantity * direction * (exit_mid - entry_mid)
            executable_before_fees = quantity * direction * (exit_price - entry_price)
            spread_cost = delayed_mid_pnl - executable_before_fees
            if spread_cost < -1e-8:
                continue
            spread_cost = max(0.0, spread_cost)
            per_side_fee_bps = max(0.0, float(frais_slippage_bps)) / 2.0
            fees = (
                abs(quantity * float(entry_price)) + abs(quantity * float(exit_price))
            ) * per_side_fee_bps / 10_000.0
            slippage_cost = 0.0
            net_pnl = gross_pnl - spread_cost - fees - slippage_cost - latency_cost
            if not math.isclose(net_pnl, executable_before_fees - fees, abs_tol=1e-8):
                continue
            net_bps = net_pnl / requested * 1e4 if requested > 0 else 0.0
            identity = "|".join(
                (
                    str(coin).upper(),
                    str(t0),
                    f"{float(horizon):g}",
                    f"{float(direction):g}",
                    str(entry[0]),
                    str(exit_quote[0]),
                )
            )
            out[horizon].append(
                {
                    "episode_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "trade_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    "coin": str(coin).upper() or None,
                    "direction": "LONG" if direction > 0 else "SHORT",
                    "signal_ts_ns": int(t0),
                    "entry_ts_ns": int(entry[0]),
                    "exit_ts_ns": int(exit_quote[0]),
                    "horizon_ms": float(horizon),
                    "entry_latency_ms": round((entry[0] - t0) / 1e6, 6),
                    "exit_observation_lag_ms": round(exit_observation_lag_ms, 6),
                    "entry_price": float(entry_price),
                    "exit_price": float(exit_price),
                    "reference_mid": reference_mid,
                    "reference_age_ms": (
                        round(reference_age_ms, 6)
                        if reference_age_ms is not None
                        else None
                    ),
                    "max_reference_lag_ms": float(max_reference_lag_ms),
                    "reference_status": (
                        "OBSERVED_AT_OR_BEFORE_SIGNAL"
                        if reference_fresh
                        else "STALE_PRE_SIGNAL_QUOTE"
                        if reference_observed_before_signal
                        else "MISSING_PRE_SIGNAL_QUOTE"
                    ),
                    "exit_status": (
                        "OBSERVED_AT_OR_AFTER_TARGET"
                        if exit_quote_fresh
                        else "STALE_EXIT_QUOTE"
                    ),
                    "max_exit_lag_ms": float(max_exit_lag_ms),
                    "entry_mid": entry_mid,
                    "exit_mid": exit_mid,
                    "quantity": quantity,
                    "entry_side": entry_side,
                    "exit_side": exit_side,
                    "configured_round_trip_cost_bps": float(frais_slippage_bps),
                    "net_bps": float(net_bps),
                    "gross_pnl_usd": gross_pnl,
                    "fees_usd": fees,
                    "spread_cost_usd": spread_cost,
                    "slippage_cost_usd": slippage_cost,
                    "latency_cost_usd": latency_cost,
                    "latency_signed_usd": signed_latency,
                    "latency_benefit_in_gross_usd": latency_benefit,
                    "latency_cost_method": (
                        "adverse_only;favourable_component_in_gross;exact_reconciliation"
                    ),
                    "net_pnl_usd": net_pnl,
                    "requested_notional_usd": requested,
                    "top_capacity_usd": capacity,
                    "liquidatable_net": liquidatable,
                    "closed": True,
                    "opened": True,
                    "economic_reconciliation_ok": True,
                    "real_execution": False,
                    "paper_read_only": True,
                }
            )
    return out


def summarize_executable_episodes(
    episodes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize only closed, sized, economically reconciled paper episodes."""

    all_rows = list(episodes)
    rows = [
        row
        for row in all_rows
        if row.get("liquidatable_net") is True
        and row.get("closed") is True
        and row.get("economic_reconciliation_ok") is True
    ]
    ids = [str(row.get("trade_id") or "") for row in rows]
    duplicate_ids = len(ids) - len(set(ids))
    gross = sum(float(row["gross_pnl_usd"]) for row in rows)
    fees = sum(float(row["fees_usd"]) for row in rows)
    spread = sum(float(row["spread_cost_usd"]) for row in rows)
    slippage = sum(float(row["slippage_cost_usd"]) for row in rows)
    latency = sum(float(row["latency_cost_usd"]) for row in rows)
    net = sum(float(row["net_pnl_usd"]) for row in rows)
    equity = peak = max_drawdown = gains = losses = 0.0
    wins = 0
    for row in sorted(rows, key=lambda value: int(value["exit_ts_ns"])):
        pnl = float(row["net_pnl_usd"])
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if pnl > 0:
            wins += 1
            gains += pnl
        elif pnl < 0:
            losses -= pnl
    reconciliation_ok = math.isclose(
        gross - fees - spread - slippage - latency,
        net,
        abs_tol=1e-6,
    )
    return {
        "positions_ouvertes": len(rows),
        "positions_fermees": len(rows),
        "observations_total": len(all_rows),
        "observations_non_liquidables": len(all_rows) - len(rows),
        "gross_pnl_usd": round(gross, 8),
        "fees_usd": round(fees, 8),
        "spread_cost_usd": round(spread, 8),
        "slippage_cost_usd": round(slippage, 8),
        "latency_cost_usd": round(latency, 8),
        "net_pnl_usd": round(net, 8),
        "roi_pct": round(net / 1000.0 * 100.0, 8),
        "max_drawdown_usd": round(max_drawdown, 8),
        "hit_rate": round(wins / len(rows), 8) if rows else 0.0,
        "profit_factor": round(gains / losses, 8) if losses > 0 else None,
        "LIQUIDATABLE_NET": bool(rows) and reconciliation_ok,
        "duplicate_trade_ids": duplicate_ids,
        "trade_ids_count": len(set(ids)),
        "trade_ids_sha256": hashlib.sha256(
            "\n".join(sorted(set(ids))).encode("utf-8")
        ).hexdigest(),
        "economic_reconciliation_ok": reconciliation_ok,
    }


def _placebo_direction(coin: str, signal_ts_ns: int) -> float:
    digest = hashlib.sha256(f"{coin}|{signal_ts_ns}|placebo-v1".encode("utf-8")).digest()
    return 1.0 if digest[0] & 1 else -1.0


def _temporal_bounds(signal_times: list[int], *, purge_ns: int) -> dict[str, int | None]:
    ordered = sorted(set(int(value) for value in signal_times))
    if len(ordered) < 3:
        return {
            "train_end_ns": None,
            "validation_start_ns": None,
            "validation_end_ns": None,
            "oos_start_ns": None,
            "purge_ns": int(purge_ns),
        }
    train_index = min(len(ordered) - 2, max(0, int(len(ordered) * 0.60) - 1))
    validation_index = min(
        len(ordered) - 1,
        max(train_index + 1, int(len(ordered) * 0.80) - 1),
    )
    train_end = ordered[train_index]
    validation_end = ordered[validation_index]
    return {
        "train_end_ns": train_end,
        "validation_start_ns": train_end + int(purge_ns),
        "validation_end_ns": validation_end,
        "oos_start_ns": validation_end + int(purge_ns),
        "purge_ns": int(purge_ns),
    }


def executable_campaign_evidence(
    tape: Mapping[str, Mapping[str, list]],
    *,
    frozen_at_ms: int,
    horizon_ms: float = CAMPAIGN_HORIZON_MS,
    frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS,
    seuil_choc_bps: float = SEUIL_CHOC_BPS,
    notional_usd: float = CAMPAIGN_NOTIONAL_USD,
    max_reference_lag_ms: float = CAMPAIGN_MAX_REFERENCE_LAG_MS,
    max_exit_lag_ms: float = CAMPAIGN_MAX_EXIT_LAG_MS,
) -> dict[str, Any]:
    """Build the fixed-horizon, purged, post-freeze Lead-Lag paper ledger."""

    frozen_at_ns = int(frozen_at_ms) * 1_000_000
    horizon_ns = int(float(horizon_ms) * 1_000_000.0)
    candidates: list[dict[str, Any]] = []
    placebos: list[dict[str, Any]] = []
    for coin in sorted(tape):
        events = tape[coin]
        hl = list(events.get("HL") or [])
        shocks = detecter_chocs(
            list(events.get("TRADE") or []),
            seuil_bps=float(seuil_choc_bps),
        )
        if len(hl) < 3 or not shocks:
            continue
        candidates.extend(
            episodes_par_horizon(
                hl,
                shocks,
                frais_slippage_bps=float(frais_slippage_bps),
                horizons_ms=(float(horizon_ms),),
                coin=coin,
                notional_usd=float(notional_usd),
                max_reference_lag_ms=float(max_reference_lag_ms),
                max_exit_lag_ms=float(max_exit_lag_ms),
            )[float(horizon_ms)]
        )
        placebo_shocks = [
            (timestamp, _placebo_direction(coin, timestamp))
            for timestamp, _direction in shocks
        ]
        placebos.extend(
            episodes_par_horizon(
                hl,
                placebo_shocks,
                frais_slippage_bps=float(frais_slippage_bps),
                horizons_ms=(float(horizon_ms),),
                coin=coin,
                notional_usd=float(notional_usd),
                max_reference_lag_ms=float(max_reference_lag_ms),
                max_exit_lag_ms=float(max_exit_lag_ms),
            )[float(horizon_ms)]
        )

    historical_times = [
        int(row["signal_ts_ns"])
        for row in candidates
        if int(row["exit_ts_ns"]) <= frozen_at_ns
    ]
    bounds = _temporal_bounds(historical_times, purge_ns=horizon_ns)

    def segment(row: Mapping[str, Any]) -> str | None:
        signal = int(row["signal_ts_ns"])
        exit_ts = int(row["exit_ts_ns"])
        if signal > frozen_at_ns:
            return "forward"
        train_end = bounds["train_end_ns"]
        validation_start = bounds["validation_start_ns"]
        validation_end = bounds["validation_end_ns"]
        oos_start = bounds["oos_start_ns"]
        if train_end is None:
            return None
        if signal <= int(train_end) and exit_ts <= int(train_end):
            return "train"
        if (
            validation_start is not None
            and validation_end is not None
            and signal >= int(validation_start)
            and exit_ts <= int(validation_end)
        ):
            return "validation"
        if oos_start is not None and signal >= int(oos_start) and exit_ts <= frozen_at_ns:
            return "oos"
        return None

    segmented = {name: [] for name in ("train", "validation", "oos", "forward")}
    placebo_segmented = {name: [] for name in segmented}
    for row in candidates:
        name = segment(row)
        if name is not None:
            row["walk_forward_segment"] = name
            segmented[name].append(row)
    for row in placebos:
        name = segment(row)
        if name is not None:
            row["walk_forward_segment"] = name
            placebo_segmented[name].append(row)

    summaries = {
        name: summarize_executable_episodes(rows)
        for name, rows in segmented.items()
    }
    placebo_summaries = {
        name: summarize_executable_episodes(rows)
        for name, rows in placebo_segmented.items()
    }
    combined_rows = [row for rows in segmented.values() for row in rows]
    combined = summarize_executable_episodes(combined_rows)
    oos = summaries["oos"]
    forward = summaries["forward"]
    placebo_oos = placebo_summaries["oos"]
    return {
        "schema_version": "hypersmart.lead_lag_executable_campaign.v1",
        "execution_model": CAMPAIGN_EXECUTION_MODEL,
        "params": {
            "horizon_ms": float(horizon_ms),
            "seuil_choc_bps": float(seuil_choc_bps),
            "round_trip_fee_bps": float(frais_slippage_bps),
            "notional_usd": float(notional_usd),
            "max_reference_lag_ms": float(max_reference_lag_ms),
            "max_exit_lag_ms": float(max_exit_lag_ms),
        },
        "walk_forward_bounds": bounds,
        "summary": combined,
        "segment_summaries": summaries,
        "placebo_summaries": placebo_summaries,
        "temporal_evidence": {
            "oos": (
                {
                    "net_pnl_usd": oos["net_pnl_usd"],
                    "sample_count": oos["positions_fermees"],
                    "no_lookahead": True,
                }
                if oos["positions_fermees"] > 0
                else None
            ),
            "forward": (
                {
                    "net_pnl_usd": forward["net_pnl_usd"],
                    "sample_count": forward["positions_fermees"],
                    "post_freeze": True,
                }
                if forward["positions_fermees"] > 0
                else None
            ),
            "placebos": {
                "beaten": bool(
                    oos["positions_fermees"] > 0
                    and placebo_oos["positions_fermees"] > 0
                    and float(oos["net_pnl_usd"]) > float(placebo_oos["net_pnl_usd"])
                ),
                "candidate_oos_net_usd": oos["net_pnl_usd"],
                "placebo_oos_net_usd": placebo_oos["net_pnl_usd"],
                "candidate_sample_count": oos["positions_fermees"],
                "placebo_sample_count": placebo_oos["positions_fermees"],
            },
        },
        "diagnostics": {
            "candidate_observations": len(candidates),
            "liquidatable_observations": sum(
                1 for row in candidates if row.get("liquidatable_net") is True
            ),
            "missing_top_sizes": sum(
                1 for row in candidates if row.get("top_capacity_usd") is None
            ),
            "stale_pre_signal_quotes": sum(
                1
                for row in candidates
                if row.get("reference_status") == "STALE_PRE_SIGNAL_QUOTE"
            ),
            "stale_exit_quotes": sum(
                1 for row in candidates if row.get("exit_status") == "STALE_EXIT_QUOTE"
            ),
            "purged_or_unassigned": len(candidates) - len(combined_rows),
        },
        "trades": combined_rows,
        "paper_read_only": True,
        "real_execution": False,
    }


def net_par_horizon(hl: list, chocs: list, *, frais_slippage_bps: float,
                    horizons_ms) -> dict[float, list[tuple[float, float | None]]]:
    """Project causal episodes as ``(net_bps, measured_top_capacity_usd)``."""

    episodes = episodes_par_horizon(
        hl,
        chocs,
        frais_slippage_bps=frais_slippage_bps,
        horizons_ms=horizons_ms,
    )
    return {
        horizon: [(row["net_bps"], row["top_capacity_usd"]) for row in rows]
        for horizon, rows in episodes.items()
    }


def _metriques(nets: list[float], *, n_periodes: int) -> dict[str, Any]:
    """Espérance, drawdown du cumul, et stabilité PAR PÉRIODE (pas le winrate)."""
    esper = st.mean(nets)
    cum, pic, dd = 0.0, 0.0, 0.0
    for x in nets:
        cum += x
        pic = max(pic, cum)
        dd = min(dd, cum - pic)
    taille = max(1, len(nets) // n_periodes)
    periodes = [nets[i:i + taille] for i in range(0, len(nets), taille)]
    moys = [st.mean(p) for p in periodes if p]
    bootstrap_totals = block_bootstrap(
        nets,
        block=max(1, int(math.sqrt(len(nets)))),
        n=500,
        seed=20260729,
    )
    bootstrap_means = sorted(total / len(nets) for total in bootstrap_totals)
    lower_index = max(0, int(len(bootstrap_means) * 0.025) - 1)
    upper_index = min(len(bootstrap_means) - 1, int(len(bootstrap_means) * 0.975))
    bootstrap_ci = (
        [round(bootstrap_means[lower_index], 3), round(bootstrap_means[upper_index], 3)]
        if bootstrap_means
        else [None, None]
    )
    return {"esperance_nette_bps": round(esper, 3), "n": len(nets),
            "drawdown_cumule_bps": round(dd, 2),
            "periodes_positives": (
                f"{sum(1 for value in moys if value > 0)}/{len(moys)}"
            ),
            "moyennes_par_periode_bps": [round(value, 3) for value in moys],
            "bootstrap_mean_ci95_bps": bootstrap_ci,
            "stable": bool(moys) and all(m > 0 for m in moys)}


def backtest(root: str | Path = ".", *, seuil_choc_bps: float = SEUIL_CHOC_BPS,
             frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS, horizons_ms=HORIZONS_MS,
             coins_controle: tuple = (), min_chocs: int = MIN_CHOCS,
             include_history: bool = False,
             max_history_sources: int = DEFAULT_HISTORY_SOURCES,
             sources: list[Path] | None = None,
             economic_frozen_at_ms: int | None = None,
             economic_horizon_ms: float = CAMPAIGN_HORIZON_MS,
             economic_notional_usd: float = CAMPAIGN_NOTIONAL_USD) -> dict[str, Any]:
    """Verdict lead-lag NET par horizon (gaté par l'observable), par coin, test vs contrôle, avec
    espérance/capacité/drawdown/stabilité. NEED_MORE_DATA tant que trop peu de chocs."""
    tape, source_meta = charger_tape(
        root,
        include_history=include_history,
        max_history_sources=max_history_sources,
        sources=sources,
        return_meta=True,
    )
    if not tape:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "detail": "tape vide",
                "source_meta": source_meta}
    controle = {c.upper() for c in coins_controle}
    # 1) cadence HL PAR COIN (jamais poolée : l'interleaving de N coins donne un p50 illusoire ~0 ms
    #    et ferait croire que 50/100 ms sont observables alors qu'HL n'emet ~qu'aux 100 ms PAR coin).
    p50s = [d["p50_ms"] for ev in tape.values() if len(ev["HL"]) >= 5
            and (d := distribution_intervalles(ev["HL"]))["p50_ms"]]
    med_p50 = st.median(p50s) if p50s else None
    dist = {"p50_ms_par_coin_median": round(med_p50, 2) if med_p50 else None, "n_coins_mesures": len(p50s)}
    horizons = [h for h in horizons_ms if med_p50 and h >= 2.0 * med_p50]
    if not horizons:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA",
                "intervalles_hl": dist, "detail": "aucun horizon observable (HL trop lent / peu de data)",
                "source_meta": source_meta}
    # 2) chocs sur trades -> net par horizon, séparé test/contrôle
    import random
    test: dict[float, list] = {h: [] for h in horizons}
    ctrl: dict[float, list] = {h: [] for h in horizons}
    placebo: dict[float, list] = {h: [] for h in horizons}     # directions MÉLANGÉES -> doit donner ~0
    cap: list[float] = []
    test_event_times: list[int] = []
    for coin, ev in tape.items():
        chocs = detecter_chocs(ev["TRADE"], seuil_bps=seuil_choc_bps)
        if not chocs or len(ev["HL"]) < 3:
            continue
        nets = net_par_horizon(ev["HL"], chocs, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
        cible = ctrl if coin in controle else test
        for h in horizons:
            cible[h].extend(x[0] for x in nets[h])
        if coin not in controle:
            test_event_times.extend(t0 for t0, _direction in chocs)
            for h in horizons:
                cap.extend(x[1] for x in nets[h] if x[1] is not None)
            rng = random.Random(20260723)                      # placebo REPRODUCTIBLE : mêmes t0, sens aléatoire
            faux = [(t0, 1.0 if rng.random() > 0.5 else -1.0) for t0, _ in chocs]
            netpl = net_par_horizon(ev["HL"], faux, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
            for h in horizons:
                placebo[h].extend(x[0] for x in netpl[h])
    n_test = max((len(v) for v in test.values()), default=0)
    if n_test < min_chocs:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "chocs_test": n_test,
                "cible": min_chocs, "intervalles_hl": dist, "horizons_observables": horizons,
                "source_meta": source_meta}
    par_h = {h: _metriques(v, n_periodes=N_PERIODES) for h, v in test.items() if v}
    ctrl_h = {h: round(st.mean(v), 3) for h, v in ctrl.items() if v}
    plac_h = {h: round(st.mean(v), 3) for h, v in placebo.items() if v}
    trial_sharpes = [sharpe(values) for values in test.values() if len(values) >= 2]
    dsr_h = {
        h: evaluer_dsr(
            values,
            n_essais=max(1, len(horizons_ms)),
            trial_sharpes=trial_sharpes,
        ).as_dict()
        for h, values in test.items()
        if values
    }
    pbo_rows = [
        metrics["moyennes_par_periode_bps"]
        for metrics in par_h.values()
        if len(metrics.get("moyennes_par_periode_bps") or ()) >= 4
    ]
    pbo = pbo_cscv(pbo_rows) if len(pbo_rows) >= 2 else pbo_cscv([])
    event_frequency = None
    if len(test_event_times) >= 2:
        duration_days = (max(test_event_times) - min(test_event_times)) / 1e9 / 86400.0
        if duration_days > 0:
            event_frequency = round(len(test_event_times) / duration_days, 6)
    # KEEP seulement si : espérance>0, STABLE par période, ET bat le PLACEBO (sinon = artefact d'horloge)
    gagnants = {h: r for h, r in par_h.items()
                if r["esperance_nette_bps"] > 0 and r["stable"]
                and r["esperance_nette_bps"] > plac_h.get(h, 0.0)}
    result = {"strategie": "lead_lag_shadow",
            "statut": "PROMETTEUR" if gagnants else "PAS_D_EDGE",
            "chocs_test": n_test,
            "intervalles_hl": dist, "horizons_observables": horizons,
            "capacite_mediane_usd": round(st.median(cap), 2) if cap else None,
            "capacity_status": "MEASURED_TOP_OF_BOOK" if cap else "UNMEASURABLE_NO_TOP_SIZES",
            "net_par_horizon": par_h, "controle_par_horizon": ctrl_h, "placebo_par_horizon": plac_h,
            "dsr_par_horizon": dsr_h,
            "pbo": pbo,
            "frequence_evenements_par_jour": event_frequency,
            "information_coefficient": {
                "value": None,
                "status": "UNMEASURABLE_WITH_DIRECTION_ONLY_SHOCKS",
            },
            "regimes": {
                "period_count": N_PERIODES,
                "stable_horizons_ms": [h for h, row in par_h.items() if row.get("stable")],
            },
            "source_meta": source_meta,
            "avertissement": "Choc sur trades Binance ; entrée demi-spread HL réel + frais/slippage ; "
                             "horizons GATÉS par l'observable ; stabilité par période. Contrôle > 0 = "
                             "artefact d'horloge. Sub-seconde souvent gagnée par des racers co-localisés."}
    if economic_frozen_at_ms is not None:
        result["executable_campaign"] = executable_campaign_evidence(
            tape,
            frozen_at_ms=int(economic_frozen_at_ms),
            horizon_ms=float(economic_horizon_ms),
            frais_slippage_bps=float(frais_slippage_bps),
            seuil_choc_bps=float(seuil_choc_bps),
            notional_usd=float(economic_notional_usd),
        )
    return result


def _legacy_geler_config(root: str | Path = ".", *, coins: list[str], coins_controle: list[str],
                         horizons_ms=HORIZONS_MS, seuil_choc_bps: float = SEUIL_CHOC_BPS,
                         frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS) -> dict[str, Any]:
    """GÈLE coins/horizons/seuils/critère AVANT le live-forward. On lira CE fichier, jamais des seuils
    réajustés après avoir vu le PnL (anti-cherry-picking)."""
    import time
    cfg = {"gele_ts": time.time(), "coins": [c.upper() for c in coins],
           "coins_controle": [c.upper() for c in coins_controle], "horizons_ms": list(horizons_ms),
           "seuil_choc_bps": seuil_choc_bps, "frais_slippage_bps": frais_slippage_bps,
           "critere_reussite": "esperance_nette_bps > 0 ET stable sur toutes les périodes ET contrôle <= 0",
           "min_chocs": MIN_CHOCS}
    p = Path(root) / CONFIG_GELE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return cfg


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    if path.exists():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        digest.update(b"<missing>")
    return f"sha256:{digest.hexdigest()}"


def _horizon_value(mapping: Any, horizon: float, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in (horizon, str(horizon), str(int(horizon))):
        if key in mapping:
            return mapping[key]
    return default


def _register_clock_boundary_trials(
    root: Path,
    *,
    dataset_hash: str,
    pipeline_hash: str,
    requested_horizons: list[float],
) -> dict[str, Any]:
    """Register every tested clock boundary once in the global research ledger."""

    ledger = root / GLOBAL_TRIAL_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    known_ids: set[str] = set()
    valid_rows = 0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                valid_rows += 1
                if row.get("trial_id"):
                    known_ids.add(str(row["trial_id"]))

    added = 0
    now = datetime.now(timezone.utc).isoformat()
    with ledger.open("a", encoding="utf-8") as handle:
        for horizon in requested_horizons:
            identity = "|".join(
                (dataset_hash, pipeline_hash, "lead_lag_shadow", f"{horizon:g}ms")
            )
            trial_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            if trial_id in known_ids:
                continue
            row = {
                "trial_id": trial_id,
                "strategy": "lead_lag_shadow",
                "dimension": "clock_boundary_ms",
                "value": horizon,
                "dataset_hash": dataset_hash,
                "pipeline_hash": pipeline_hash,
                "registered_at": now,
                "real_execution": False,
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            known_ids.add(trial_id)
            added += 1
    return {
        "count": valid_rows + added,
        "added": added,
        "ledger": str(ledger),
    }


def geler_config(
    root: str | Path = ".",
    *,
    coins: list[str],
    coins_controle: list[str],
    horizons_ms=HORIZONS_MS,
    seuil_choc_bps: float = SEUIL_CHOC_BPS,
    frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS,
    minimum_events: int = MIN_CHOCS,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze a complete, versioned and deny-by-default lead-lag evidence artefact."""

    root_path = Path(root)
    requested = [float(value) for value in horizons_ms]
    unsupported = [value for value in requested if value not in SUPPORTED_HORIZONS_MS]
    if unsupported:
        raise ValueError(f"unsupported lead-lag horizons: {unsupported}")

    dataset_path = root_path / TAPE
    pipeline_path = Path(__file__)
    dataset_hash = _sha256_file(dataset_path)
    pipeline_hash = _sha256_file(pipeline_path)
    global_trials = _register_clock_boundary_trials(
        root_path,
        dataset_hash=dataset_hash,
        pipeline_hash=pipeline_hash,
        requested_horizons=requested,
    )
    result = evidence or backtest(
        root_path,
        seuil_choc_bps=seuil_choc_bps,
        frais_slippage_bps=frais_slippage_bps,
        horizons_ms=requested,
        coins_controle=tuple(coins_controle),
        min_chocs=minimum_events,
    )
    observable = [
        float(value)
        for value in result.get("horizons_observables", ())
        if float(value) in requested
    ]
    net_rows = result.get("net_par_horizon") or {}
    controls = result.get("controle_par_horizon") or {}
    placebos = result.get("placebo_par_horizon") or {}
    dsr_rows = result.get("dsr_par_horizon") or {}

    edges: dict[str, float] = {}
    samples: dict[str, int] = {}
    stability: dict[str, bool] = {}
    bootstrap: dict[str, list[float | None]] = {}
    placebo_edges: dict[str, float | None] = {}
    control_edges: dict[str, float | None] = {}
    dsr: dict[str, dict[str, Any]] = {}
    for horizon in observable:
        key = str(int(horizon) if horizon.is_integer() else horizon)
        row = _horizon_value(net_rows, horizon, {}) or {}
        edges[key] = float(row.get("esperance_nette_bps") or 0.0)
        samples[key] = int(row.get("n") or 0)
        stability[key] = row.get("stable") is True
        bootstrap[key] = list(row.get("bootstrap_mean_ci95_bps") or [None, None])
        placebo = _horizon_value(placebos, horizon)
        control = _horizon_value(controls, horizon)
        placebo_edges[key] = float(placebo) if placebo is not None else None
        control_edges[key] = float(control) if control is not None else None
        dsr[key] = dict(_horizon_value(dsr_rows, horizon, {}) or {})

    pbo = dict(result.get("pbo") or {})
    estimated_half_life_ms = estimate_alpha_half_life_ms(
        {float(horizon): edge for horizon, edge in edges.items()}
    )
    alpha_half_life_p95_ms = _optional_finite_positive(
        result.get("alpha_half_life_p95_ms")
    )
    end_to_end_latency_p95_ms = _optional_finite_non_negative(
        result.get("end_to_end_latency_p95_ms")
    )
    latency_safety_margin_ms = _optional_finite_non_negative(
        result.get("latency_safety_margin_ms")
    )
    if latency_safety_margin_ms is None:
        latency_safety_margin_ms = 25.0
    latency_budget_passed = (
        alpha_half_life_p95_ms is not None
        and end_to_end_latency_p95_ms is not None
        and alpha_half_life_p95_ms
        > end_to_end_latency_p95_ms + latency_safety_margin_ms
    )
    criteria = {
        "minimum_sample": bool(observable)
        and all(samples.get(str(int(h)), 0) >= minimum_events for h in observable),
        "observable_horizon": bool(observable),
        "net_positive": bool(observable)
        and all(edges.get(str(int(h)), 0.0) > 0 for h in observable),
        "period_stability": bool(observable)
        and all(stability.get(str(int(h))) is True for h in observable),
        "placebo_beaten": bool(observable)
        and all(
            placebo_edges.get(str(int(h))) is not None
            and edges.get(str(int(h)), 0.0) > float(placebo_edges[str(int(h))])
            for h in observable
        ),
        "controls_non_winning": bool(observable)
        and all(
            control_edges.get(str(int(h))) is not None
            and float(control_edges[str(int(h))]) <= 0
            for h in observable
        ),
        "costs_executable": math.isfinite(float(frais_slippage_bps))
        and float(frais_slippage_bps) >= 0,
        "bootstrap_positive": bool(observable)
        and all(
            len(bootstrap.get(str(int(h)), ())) == 2
            and bootstrap[str(int(h))][0] is not None
            and float(bootstrap[str(int(h))][0]) > 0
            for h in observable
        ),
        "pbo_acceptable": pbo.get("pbo") is not None and float(pbo["pbo"]) <= 0.5,
        "dsr_acceptable": bool(observable)
        and all(dsr.get(str(int(h)), {}).get("survit") is True for h in observable),
        "latency_budget_passed": latency_budget_passed,
    }
    promotion_status = (
        "PROMOTED"
        if all(criteria.get(name) is True for name in REQUIRED_CRITERIA)
        else "REJECTED"
    )
    now = datetime.now(timezone.utc)
    config = {
        "schema_version": SCHEMA_VERSION,
        "strategy": "lead_lag_shadow",
        "promotion_status": promotion_status,
        "dataset_hash": dataset_hash,
        "pipeline_hash": pipeline_hash,
        "freeze_ts": now.isoformat(),
        "freeze_ts_ms": int(now.timestamp() * 1000),
        "coins": sorted({str(coin).upper() for coin in coins if coin}),
        "control_coins": sorted(
            {str(coin).upper() for coin in coins_controle if coin}
        ),
        "requested_horizons_ms": requested,
        "observable_horizons_ms": observable,
        "unobservable_horizons_ms": [
            horizon for horizon in requested if horizon not in observable
        ],
        "minimum_events": int(minimum_events),
        "seuil_choc_bps": float(seuil_choc_bps),
        "edge_net_par_horizon_bps": edges,
        "sample_n_by_horizon": samples,
        "period_stability_by_horizon": stability,
        "bootstrap_mean_ci95_bps": bootstrap,
        "placebo_edge_by_horizon_bps": placebo_edges,
        "control_edge_by_horizon_bps": control_edges,
        "dsr_by_horizon": dsr,
        "pbo": pbo,
        "costs": {
            "round_trip_bps": float(frais_slippage_bps),
            "model": "real_hl_bid_ask_plus_configured_fees_and_slippage",
            "executable": criteria["costs_executable"],
        },
        "latency_budget": {
            "estimated_alpha_half_life_ms": estimated_half_life_ms,
            "alpha_half_life_p95_ms": alpha_half_life_p95_ms,
            "end_to_end_latency_p95_ms": end_to_end_latency_p95_ms,
            "safety_margin_ms": latency_safety_margin_ms,
            "remaining_budget_ms": (
                alpha_half_life_p95_ms
                - end_to_end_latency_p95_ms
                - latency_safety_margin_ms
                if latency_budget_passed
                else None
            ),
            "status": "PASS" if latency_budget_passed else "UNMEASURABLE_OR_TOO_SLOW",
        },
        "frequency": {
            "events_per_day": result.get("frequence_evenements_par_jour"),
        },
        "information_coefficient": result.get("information_coefficient")
        or {"value": None, "status": "UNMEASURABLE"},
        "regimes": result.get("regimes") or {},
        "criteria": criteria,
        "global_trials": global_trials,
        "source_status": str(result.get("statut") or "UNKNOWN"),
        "source_detail": result.get("detail"),
        "real_execution": False,
    }
    output = root_path / CONFIG_GELE
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    import os

    os.replace(temporary, output)
    return config


def _optional_finite_positive(value: Any) -> float | None:
    parsed = _optional_finite_non_negative(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _optional_finite_non_negative(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


__all__ = [
    "SEUIL_CHOC_BPS",
    "FRAIS_SLIPPAGE_BPS",
    "HORIZONS_MS",
    "charger_tape",
    "CAMPAIGN_HORIZON_MS",
    "CAMPAIGN_NOTIONAL_USD",
    "CAMPAIGN_MAX_REFERENCE_LAG_MS",
    "CAMPAIGN_MAX_EXIT_LAG_MS",
    "CAMPAIGN_EXECUTION_MODEL",
    "walk_forward_protocol_signature",
    "distribution_intervalles",
    "horizons_observables",
    "detecter_chocs",
    "episodes_par_horizon",
    "summarize_executable_episodes",
    "executable_campaign_evidence",
    "net_par_horizon",
    "backtest",
    "geler_config",
    "GLOBAL_TRIAL_LEDGER",
]
