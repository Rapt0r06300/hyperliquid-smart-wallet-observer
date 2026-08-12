"""Adapter from recorded Lead-Lag tapes to strict economic campaign evidence.

It converts observed Binance shocks and Hyperliquid BBO reactions into causal
``SignalLeadLag`` objects, replays them through the closed paper ledger, then
emits the strict +4 USD evidence shape. It never opens a network connection or
executes. Historical replay is never mislabeled as post-freeze forward.
"""
from __future__ import annotations

import bisect
import hashlib
import statistics
from collections.abc import Mapping
from typing import Any

from hl_observer.backtesting import lead_lag_shadow
from hl_observer.simulation.economic_objective import evaluate_objective
from hl_observer.strategies.lead_lag_paper import SignalLeadLag, rejouer_lead_lag


def signals_from_tape(
    tape: Mapping[str, Mapping[str, list]],
    *,
    shock_threshold_bps: float,
    horizon_ms: int = 1_000,
    min_history: int = 5,
) -> tuple[list[SignalLeadLag], dict[str, Any]]:
    """Create causal signals using only prior shock outcomes for expected edge.

    ``delta_mid_futur`` settles a frozen exit; it is never used in the entry
    decision. ``edge_bps_prevu`` is the mean aligned return of *previous*
    shocks for the same coin, therefore no look-ahead is introduced.
    """
    signals: list[SignalLeadLag] = []
    shocks_seen = 0
    shocks_with_exit = 0
    spread_samples: list[float] = []

    for coin, streams in tape.items():
        hl = sorted(list(streams.get("HL") or []))
        trades = sorted(list(streams.get("TRADE") or []))
        if len(hl) < 2 or len(trades) < 2:
            continue
        hl_times = [int(row[0]) for row in hl]
        shocks = lead_lag_shadow.detecter_chocs(trades, seuil_bps=float(shock_threshold_bps))
        prior_aligned: list[float] = []
        for shock_ns, direction in shocks:
            shocks_seen += 1
            entry_index = bisect.bisect_right(hl_times, int(shock_ns)) - 1
            exit_index = bisect.bisect_right(
                hl_times, int(shock_ns) + int(horizon_ms) * 1_000_000
            ) - 1
            if entry_index < 0 or exit_index <= entry_index:
                continue
            entry = hl[entry_index]
            exit_quote = hl[exit_index]
            mid_entry = float(entry[1])
            mid_exit = float(exit_quote[1])
            if mid_entry <= 0:
                continue
            shocks_with_exit += 1
            bid, ask = float(entry[2]), float(entry[3])
            if bid > 0 and ask >= bid:
                spread_samples.append((ask - bid) / mid_entry * 1e4)
            expected = (
                statistics.fmean(prior_aligned)
                if len(prior_aligned) >= int(min_history)
                else 0.0
            )
            signals.append(
                SignalLeadLag(
                    ts_ms=int(shock_ns // 1_000_000),
                    coin=str(coin),
                    signe_leader=1 if float(direction) > 0 else -1,
                    mid_entree=mid_entry,
                    delta_mid_futur=mid_exit - mid_entry,
                    edge_bps_prevu=round(float(expected), 6),
                    liquidite=1.0,
                    horizon_ms=int(horizon_ms),
                )
            )
            realized_aligned = (1 if float(direction) > 0 else -1) * (
                (mid_exit - mid_entry) / mid_entry * 1e4
            )
            prior_aligned.append(float(realized_aligned))

    signals.sort(key=lambda signal: (signal.ts_ms, signal.coin, signal.signe_leader))
    meta = {
        "shock_threshold_bps": float(shock_threshold_bps),
        "horizon_ms": int(horizon_ms),
        "min_history": int(min_history),
        "shocks_seen": shocks_seen,
        "shocks_with_observable_exit": shocks_with_exit,
        "signals_built": len(signals),
        "median_full_spread_bps": (
            round(float(statistics.median(spread_samples)), 6) if spread_samples else None
        ),
        "no_lookahead": True,
        "read_only": True,
        "real_execution": False,
    }
    return signals, meta


def run_ledger(
    tape: Mapping[str, Mapping[str, list]],
    *,
    shock_threshold_bps: float,
    horizon_ms: int,
    min_history: int,
    config: dict[str, Any],
    min_episodes: int,
) -> dict[str, Any]:
    signals, meta = signals_from_tape(
        tape,
        shock_threshold_bps=shock_threshold_bps,
        horizon_ms=horizon_ms,
        min_history=min_history,
    )
    replay = rejouer_lead_lag(signals, config=config, min_episodes=min_episodes)
    return {"signals_meta": meta, "signals": len(signals), "replay": replay}


def _forward_signal_times(replay: Mapping[str, Any]) -> list[int]:
    ledgers = replay.get("ledgers") if isinstance(replay.get("ledgers"), Mapping) else {}
    events = ledgers.get("FORWARD") if isinstance(ledgers.get("FORWARD"), list) else []
    times: list[int] = []
    for event in events:
        if not isinstance(event, Mapping) or event.get("evt") != "SIGNAL":
            continue
        try:
            times.append(int(event.get("ts")))
        except (TypeError, ValueError, OverflowError):
            continue
    return times


def campaign_from_replay(
    raw: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
    evidence_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Convert closed Lead-Lag ledger segments into strict objective evidence."""
    replay = raw.get("replay") if isinstance(raw.get("replay"), Mapping) else {}
    segments = replay.get("segments") if isinstance(replay.get("segments"), Mapping) else {}
    ordered = [
        segments.get(label) if isinstance(segments.get(label), Mapping) else {}
        for label in ("IS", "OOS", "FORWARD")
    ]

    def total(key: str) -> float:
        return round(sum(float(segment.get(key) or 0.0) for segment in ordered), 8)

    opened = sum(int(segment.get("opened_positions") or 0) for segment in ordered)
    closed = sum(int(segment.get("closed_positions") or 0) for segment in ordered)
    trade_ids = [
        str(trade_id)
        for segment in ordered
        for trade_id in (segment.get("trade_ids") or [])
        if trade_id
    ]
    unique_trade_ids = sorted(set(trade_ids))
    nets = [float(value) for segment in ordered for value in (segment.get("nets_episodes") or [])]
    total_net = total("net")
    gross = total("gross_pnl_usd")
    fees = total("fees_usd")
    spread = total("spread_cost_usd")
    slippage = total("slippage_cost_usd")
    latency = total("latency_cost_usd")
    all_liquidatable = bool(
        opened > 0
        and opened == closed
        and all(segment.get("LIQUIDATABLE_NET") is True for segment in ordered)
    )
    gains = sum(value for value in nets if value > 0)
    losses = -sum(value for value in nets if value < 0)
    profit_factor = (
        float("inf")
        if gains > 0 and losses == 0
        else round(gains / losses, 8)
        if losses > 0
        else None
    )
    placebo = replay.get("placebo") if isinstance(replay.get("placebo"), Mapping) else {}
    placebo_net = float(placebo.get("net") or 0.0)
    oos = ordered[1]
    forward = ordered[2]
    frozen_at_ms = int(freeze.get("frozen_at_ms") or 0) if freeze else 0
    forward_signal_times = _forward_signal_times(replay)
    forward_post_freeze = bool(
        frozen_at_ms > 0
        and forward_signal_times
        and min(forward_signal_times) > frozen_at_ms
    )

    row: dict[str, Any] = {
        "schema_version": "hypersmart.economic_campaign_evidence.v1",
        "family": "lead_lag",
        "campaign_id": freeze.get("campaign_id") if freeze else None,
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
        "parameters_frozen": bool(freeze and freeze.get("selected_before_final_evaluation") is True),
        "parameter_freeze": dict(freeze) if freeze else None,
        "dataset_provenance": dict(datasets),
        "signal_count": raw.get("signals"),
        "opened_positions": opened,
        "closed_positions": closed,
        "gross_pnl_usd": gross,
        "fees_usd": fees,
        "spread_cost_usd": spread,
        "slippage_cost_usd": slippage,
        "latency_cost_usd": latency,
        "net_pnl_usd": total_net,
        "roi_pct": round(total_net / 1000.0 * 100.0, 8),
        "max_drawdown_usd": max(
            (float(segment.get("max_drawdown_usd") or 0.0) for segment in ordered),
            default=0.0,
        ),
        "hit_rate": round(sum(value > 0 for value in nets) / len(nets), 8) if nets else None,
        "profit_factor": profit_factor,
        "liquidatable_net": all_liquidatable,
        "duplicate_trade_ids": len(trade_ids) - len(unique_trade_ids),
        "trade_ids_count": len(unique_trade_ids),
        "trade_ids_sha256": hashlib.sha256("\n".join(unique_trade_ids).encode("utf-8")).hexdigest(),
        "oos": {
            "net_pnl_usd": oos.get("net"),
            "sample_count": oos.get("closed_positions"),
            "no_lookahead": True,
        },
        "forward": {
            "net_pnl_usd": forward.get("net"),
            "sample_count": forward.get("closed_positions"),
            "post_freeze": forward_post_freeze,
            "first_signal_ts_ms": min(forward_signal_times) if forward_signal_times else None,
            "frozen_at_ms": frozen_at_ms or None,
        },
        "placebos": {
            "beaten": bool(nets) and total_net > placebo_net,
            "candidate_net_usd": total_net,
            "placebo_net_usd": placebo_net,
        },
        "source_status": replay.get("verdict"),
        "source_detail": raw.get("signals_meta"),
        "evidence_paths": list(dict.fromkeys(evidence_paths or [])),
    }
    row.update(evaluate_objective(row))
    return row


__all__ = ["campaign_from_replay", "run_ledger", "signals_from_tape"]
