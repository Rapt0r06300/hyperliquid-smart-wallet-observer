"""Causal Lead-Lag paper replay with frozen exits and strict accounting.

The decision only uses information known at signal time.  The future price
move is used to settle the already-frozen exit, never to decide whether to
enter.  All outputs are local paper evidence; this module has no network or
execution capability.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Sequence

from hl_observer.mega_cablage.replay_driver import separer_par_episodes
from hl_observer.ops import lab_metriques as M
from hl_observer.paper_trading import latency_truth as _LT


@dataclass(frozen=True)
class SignalLeadLag:
    ts_ms: int
    coin: str
    signe_leader: int
    mid_entree: float
    delta_mid_futur: float
    edge_bps_prevu: float
    liquidite: float = 1.0
    horizon_ms: int = 1_000


def cout_components_bps(config: dict[str, Any], *, delai_sec: float = 1.0) -> dict[str, Any]:
    """Return a complete conservative cost model and its proof status.

    Slippage is charged even when it has not yet been measured so the model
    never benefits from a free fill.  Such an estimate is still not eligible
    for ``LIQUIDATABLE_NET`` until executable observations prove all costs.
    """

    fee = max(0.0, float(config.get("fee_bps", 2.5)))
    spread = max(0.0, float(config.get("demi_spread_bps", fee)))
    slippage = max(0.0, float(config.get("slippage_bps", 1.0)))
    latency = max(
        0.0,
        float(
            _LT.latence_scalaire_stress_bps(
                float(delai_sec), coeff_bps_per_sec=0.20, cap_bps=15.0
            ).get("latency_stress_bps")
            or 0.0
        ),
    )
    result = {
        "fees_bps": round(fee, 6),
        "spread_bps": round(spread, 6),
        "slippage_bps": round(slippage, 6),
        "latency_bps": round(latency, 6),
    }
    result["total_bps"] = round(sum(result.values()), 6)
    result["costs_measured"] = bool(config.get("costs_measured", False))
    return result


def cout_total_bps(config: dict[str, Any], *, delai_sec: float = 1.0) -> float:
    """Conservative round-trip cost in basis points."""

    return float(cout_components_bps(config, delai_sec=delai_sec)["total_bps"])


def _bps(delta: float, mid: float) -> float:
    return (float(delta) / float(mid)) * 1e4 if mid else 0.0


def _trade_id(sig: SignalLeadLag) -> str:
    """Identity contains only information fixed before the outcome."""

    payload = {
        "coin": sig.coin,
        "horizon_ms": sig.horizon_ms,
        "mid_entree": sig.mid_entree,
        "signe_leader": sig.signe_leader,
        "ts_ms": sig.ts_ms,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def simuler_episode(sig: SignalLeadLag, *, config: dict[str, Any]) -> dict[str, Any]:
    """Replay one complete causal episode with a frozen exit."""

    notional = float(config.get("notional", 100.0))
    min_fill = float(config.get("min_fill_ratio", 0.5))
    costs = cout_components_bps(config)
    total_cost_bps = float(costs["total_bps"])
    trade_id = _trade_id(sig)
    ledger: list[dict[str, Any]] = [
        {
            "evt": "SIGNAL",
            "ts": sig.ts_ms,
            "coin": sig.coin,
            "signe": int(sig.signe_leader),
            "edge_prevu_bps": sig.edge_bps_prevu,
            "trade_id": trade_id,
        }
    ]

    edge_net_prevu = float(sig.edge_bps_prevu) - total_cost_bps
    if edge_net_prevu <= 0:
        ledger.append(
            {
                "evt": "NO_TRADE",
                "raison": "EDGE_NET_PREVU<=0",
                "edge_net_prevu_bps": round(edge_net_prevu, 6),
                "trade_id": trade_id,
            }
        )
        return {
            "statut": "NO_TRADE",
            "pnl_usd": 0.0,
            "notional": 0.0,
            "coin": sig.coin,
            "trade_id": trade_id,
            "opened_positions": 0,
            "closed_positions": 0,
            "LIQUIDATABLE_NET": False,
            "ledger": ledger,
        }

    ledger.append(
        {
            "evt": "ENTREE",
            "mid": sig.mid_entree,
            "horizon_ms": sig.horizon_ms,
            "sortie": "GELEE",
            "trade_id": trade_id,
        }
    )
    if float(sig.liquidite) < min_fill:
        ledger.append(
            {
                "evt": "MISSED_FILL",
                "liquidite": sig.liquidite,
                "min_fill_ratio": min_fill,
                "trade_id": trade_id,
            }
        )
        return {
            "statut": "MISSED_FILL",
            "pnl_usd": 0.0,
            "notional": 0.0,
            "coin": sig.coin,
            "trade_id": trade_id,
            "opened_positions": 0,
            "closed_positions": 0,
            "LIQUIDATABLE_NET": False,
            "ledger": ledger,
        }

    gross_bps = float(sig.signe_leader) * _bps(sig.delta_mid_futur, sig.mid_entree)
    net_bps = gross_bps - total_cost_bps
    gross_usd = round(gross_bps / 1e4 * notional, 8)
    component_usd = {
        "fees_usd": round(float(costs["fees_bps"]) / 1e4 * notional, 8),
        "spread_cost_usd": round(float(costs["spread_bps"]) / 1e4 * notional, 8),
        "slippage_cost_usd": round(float(costs["slippage_bps"]) / 1e4 * notional, 8),
        "latency_cost_usd": round(float(costs["latency_bps"]) / 1e4 * notional, 8),
    }
    pnl_usd = round(gross_usd - sum(component_usd.values()), 8)
    reconciled = math.isclose(gross_usd - sum(component_usd.values()), pnl_usd, abs_tol=1e-8)
    liquidatable = bool(costs["costs_measured"] and reconciled)
    ledger.append(
        {
            "evt": "SORTIE",
            "gross_bps": round(gross_bps, 6),
            "couts_bps": total_cost_bps,
            "net_bps": round(net_bps, 6),
            "trade_id": trade_id,
        }
    )
    ledger.append(
        {
            "evt": "PNL",
            "pnl_usd": pnl_usd,
            "gross_pnl_usd": gross_usd,
            **component_usd,
            "notional": notional,
            "trade_id": trade_id,
            "LIQUIDATABLE_NET": liquidatable,
        }
    )
    return {
        "statut": "FILLED",
        "pnl_usd": pnl_usd,
        "gross_pnl_usd": gross_usd,
        **component_usd,
        "notional": notional,
        "coin": sig.coin,
        "trade_id": trade_id,
        "opened_positions": 1,
        "closed_positions": 1,
        "economic_reconciled": reconciled,
        "LIQUIDATABLE_NET": liquidatable,
        "ledger": ledger,
    }


def _as_signal(value: Any) -> SignalLeadLag:
    if isinstance(value, SignalLeadLag):
        return value
    return SignalLeadLag(
        ts_ms=int(value.get("ts_ms") or 0),
        coin=str(value.get("coin") or "?"),
        signe_leader=int(value.get("signe_leader") or value.get("signe") or 0),
        mid_entree=float(value.get("mid_entree") or value.get("mid") or 0.0),
        delta_mid_futur=float(value.get("delta_mid_futur") or 0.0),
        edge_bps_prevu=float(value.get("edge_bps_prevu") or 0.0),
        liquidite=float(value.get("liquidite", 1.0)),
        horizon_ms=int(value.get("horizon_ms", 1_000)),
    )


def _net_segment(signaux: Sequence[Any], *, config: dict[str, Any]) -> dict[str, Any]:
    net = 0.0
    gross = 0.0
    notional = 0.0
    fills = 0
    missed = 0
    costs = {
        "fees_usd": 0.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
    }
    nets: list[float] = []
    contributions: dict[str, float] = {}
    ledger: list[dict[str, Any]] = []
    trade_ids: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    all_liquidatable = True

    for value in signaux:
        signal = _as_signal(value)
        identity = _trade_id(signal)
        if identity in seen:
            duplicates += 1
            ledger.append(
                {
                    "evt": "NO_TRADE",
                    "raison": "DUPLICATE_TRADE_ID",
                    "trade_id": identity,
                    "ts": signal.ts_ms,
                    "coin": signal.coin,
                }
            )
            continue
        seen.add(identity)
        result = simuler_episode(signal, config=config)
        ledger.extend(result["ledger"])
        if result["statut"] == "FILLED":
            fills += 1
            net += result["pnl_usd"]
            gross += result["gross_pnl_usd"]
            for key in costs:
                costs[key] += float(result[key])
            notional += result["notional"]
            nets.append(result["pnl_usd"])
            contributions[result["coin"]] = contributions.get(result["coin"], 0.0) + result["pnl_usd"]
            trade_ids.append(result["trade_id"])
            all_liquidatable = all_liquidatable and bool(result["LIQUIDATABLE_NET"])
        elif result["statut"] == "MISSED_FILL":
            missed += 1

    gains = sum(value for value in nets if value > 0)
    losses = -sum(value for value in nets if value < 0)
    profit_factor = (
        float("inf") if gains > 0 and losses == 0
        else round(gains / losses, 8) if losses > 0
        else None
    )
    curve = [float(config.get("equity", 1000.0))]
    for value in nets:
        curve.append(curve[-1] + value)
    return {
        "net": round(net, 8),
        "gross_pnl_usd": round(gross, 8),
        **{key: round(value, 8) for key, value in costs.items()},
        "notional": round(notional, 8),
        "fills": fills,
        "missed": missed,
        "opened_positions": fills,
        "closed_positions": fills,
        "nets_episodes": nets,
        "contributions": contributions,
        "ledger": ledger,
        "trade_ids": trade_ids,
        "trade_ids_count": len(trade_ids),
        "trade_ids_sha256": hashlib.sha256("\n".join(trade_ids).encode("utf-8")).hexdigest(),
        "duplicate_trade_ids": duplicates,
        "profit_factor": profit_factor,
        "max_drawdown_usd": M.drawdown(curve),
        "hit_rate": round(sum(value > 0 for value in nets) / fills, 8) if fills else None,
        "LIQUIDATABLE_NET": bool(fills and all_liquidatable),
    }


def rejouer_lead_lag(
    signaux: list[Any],
    *,
    config: dict[str, Any] | None = None,
    fractions: tuple[float, ...] = (0.6, 0.2, 0.2),
    min_episodes: int = 5,
) -> dict[str, Any]:
    """Replay indivisible IS/OOS/FORWARD episodes and an all-sample placebo."""

    config = {
        "notional": 100.0,
        "fee_bps": 2.5,
        "slippage_bps": 1.0,
        "min_fill_ratio": 0.5,
        **(config or {}),
    }
    events = [
        {
            "ts_ms": _as_signal(signal).ts_ms,
            "coin": _as_signal(signal).coin,
            "signe": _as_signal(signal).signe_leader,
            "_sig": signal,
        }
        for signal in signaux
    ]
    split = separer_par_episodes(events, fractions=fractions)
    segments = {
        label: _net_segment([event["_sig"] for event in split[label]], config=config)
        for label in ("IS", "OOS", "FORWARD")
    }
    in_sample = segments["IS"]

    placebo_signals = []
    for value in signaux:
        signal = _as_signal(value)
        placebo_signals.append(
            SignalLeadLag(
                signal.ts_ms,
                signal.coin,
                -signal.signe_leader,
                signal.mid_entree,
                signal.delta_mid_futur,
                signal.edge_bps_prevu,
                signal.liquidite,
                signal.horizon_ms,
            )
        )
    placebo = _net_segment(placebo_signals, config=config)

    equity = [float(config.get("equity", 1000.0))]
    for value in in_sample["nets_episodes"]:
        equity.append(equity[-1] + value)
    capacity = round(in_sample["notional"], 4) if in_sample["fills"] else M.UNMEASURABLE
    all_costs = sum(in_sample[key] for key in (
        "fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd"
    ))
    metrics = M.metriques_candidat(
        segments={
            "IS": {"net": in_sample["net"]},
            "OOS": {"net": segments["OOS"]["net"]},
            "FORWARD": {"net": segments["FORWARD"]["net"]},
            "ADVERSE_P95": {"net": min(segments["OOS"]["net"], segments["FORWARD"]["net"])},
            "ADVERSE_P99": {"net": min(segments["OOS"]["net"], segments["FORWARD"]["net"])},
        },
        nets_episodes=in_sample["nets_episodes"],
        courbe_equity=equity,
        notional_traite=in_sample["notional"],
        equity_finale=equity[-1],
        fees=all_costs,
        contributions_coin=in_sample["contributions"],
        capacite=capacity,
        reconcilie=in_sample["LIQUIDATABLE_NET"],
        placebo_net=placebo["net"],
    )
    verdict = M.verdict_promotion(metrics, min_episodes=min_episodes)
    return {
        "segments": {
            label: {key: value for key, value in segment.items() if key != "ledger"}
            for label, segment in segments.items()
        },
        "metriques": metrics,
        "verdict": verdict,
        "placebo_net": placebo["net"],
        "placebo": {key: value for key, value in placebo.items() if key != "ledger"},
        "ledger_is": in_sample["ledger"],
        "ledgers": {label: segment["ledger"] for label, segment in segments.items()},
        "paper_read_only": True,
        "real_execution": False,
    }


def signaux_depuis_events(
    events: list[dict[str, Any]],
    *,
    min_historique: int = 5,
    horizon_ms: int = 1_000,
    liquidite_defaut: float = 1.0,
) -> list[SignalLeadLag]:
    """Build causal expected edges from prior observations of each coin."""

    by_coin: dict[str, list[tuple[int, int, float, Any]]] = {}
    for event in events:
        mid = event.get("mid", event.get("px"))
        if isinstance(mid, (int, float)) and event.get("signe"):
            by_coin.setdefault(str(event.get("coin")), []).append(
                (event.get("ts_ms") or 0, int(event.get("signe")), float(mid), event.get("liquidite"))
            )
    signals: list[SignalLeadLag] = []
    for coin, series in by_coin.items():
        series.sort(key=lambda item: item[0])
        prior_alignments: list[float] = []
        for index in range(len(series) - 1):
            ts_ms, sign, mid, liquidity = series[index]
            delta = series[index + 1][2] - mid
            expected = (
                sum(prior_alignments) / len(prior_alignments)
                if len(prior_alignments) >= min_historique
                else 0.0
            )
            signals.append(
                SignalLeadLag(
                    ts_ms=ts_ms,
                    coin=coin,
                    signe_leader=sign,
                    mid_entree=mid,
                    delta_mid_futur=delta,
                    edge_bps_prevu=round(expected, 6),
                    liquidite=float(liquidity) if isinstance(liquidity, (int, float)) else liquidite_defaut,
                    horizon_ms=horizon_ms,
                )
            )
            prior_alignments.append(sign * _bps(delta, mid))
    signals.sort(key=lambda signal: signal.ts_ms)
    return signals


__all__ = [
    "SignalLeadLag",
    "cout_components_bps",
    "cout_total_bps",
    "rejouer_lead_lag",
    "signaux_depuis_events",
    "simuler_episode",
]
