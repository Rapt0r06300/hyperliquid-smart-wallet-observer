"""V13 — Corpus growth: turn REFUSED decisions into shadow-labeled samples.

The live recorder only labels trades we OPENED and CLOSED, so the model learns
from a tiny minority of decisions (77 samples over weeks). The vast majority of
decisions are REFUSALS (NO_TRADE). Those carry decision-time evidence but no
outcome — so today they teach the model nothing.

This module gives each measurable refusal an HONEST shadow outcome: using the
real marks that came AFTER the decision, it simulates the trade we would have
taken (same side, same SL/TP/horizon/cost model as the A/B replay) and records
the net PnL it would have produced. The model then learns to tell a GOOD refusal
(would have lost) from a BAD refusal (would have won) — the exact signal needed
to stop refusing profitable trades and keep refusing bad ones.

Pure / read-only / no-lookahead (only marks strictly after the decision are
used). If an outcome is not measurable (no future marks, no price), the sample
is skipped — never fabricated.
"""

from __future__ import annotations

from hl_observer.backtesting.ab_flag_replay import simulate_exit_on_path
from hl_observer.ml.dataset import FeatureRow, Outcome
from hl_observer.ml.features import canonical_features
from hl_observer.paper_trading.sl_tp import SLTPConfig

SHADOW_CONTEXT = "SHADOW_REFUSED"
_REFUSAL_STATUSES = {"REJECT_NO_TRADE"}
_REFUSAL_ACTIONS = {"NO_TRADE"}


def _is_refusal(ev: dict) -> bool:
    return (
        str(ev.get("status") or "") in _REFUSAL_STATUSES
        or str(ev.get("paper_action_type") or "") in _REFUSAL_ACTIONS
    )


def _num(ev: dict, *names: str) -> float:
    for n in names:
        v = ev.get(n)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _features_from_refusal(ev: dict) -> dict:
    return canonical_features(
        net_edge_bps=_num(ev, "edge_remaining_bps", "net_edge_bps"),
        signal_age_ms=_num(ev, "signal_age_ms", "age_ms"),
        consensus_wallets=_num(ev, "leader_wallets_count", "consensus_wallets"),
        liquidity_score=_num(ev, "liquidity_score"),
        leader_score=_num(ev, "leader_score", "winning_vote_score"),
        adverse_move_bps=_num(ev, "adverse_price_move_bps"),
        price_deviation_bps=_num(ev, "price_deviation_bps", "spread_bps"),
    )


def rows_outcomes_from_refusals(
    events: list[dict],
    marks_by_coin: dict[str, list[tuple[float, float]]],
    *,
    horizon_min: float = 10.0,
    cost_bps: float = 12.0,
    config: SLTPConfig | None = None,
) -> tuple[list[FeatureRow], list[Outcome]]:
    """Build shadow (features -> outcome) pairs from refused decisions.

    Only refusals that carry a side, a reference price and produce a measurable
    forward outcome on real marks are kept.
    """

    cfg = config or SLTPConfig(stop_loss_bps=40.0, take_profit_bps=70.0)
    rows: list[FeatureRow] = []
    outcomes: list[Outcome] = []
    for ev in events or []:
        if not isinstance(ev, dict) or not _is_refusal(ev):
            continue
        coin = str(ev.get("coin") or "").upper()
        side = str(ev.get("leader_side") or ev.get("side") or "").upper()
        if side not in {"LONG", "SHORT"} or coin not in marks_by_coin:
            continue
        entry = _num(ev, "leader_price", "reference_price")
        ts = _num(ev, "observed_at_ms", "ts_ms")
        if entry <= 0 or ts <= 0:
            continue
        entry_ts_sec = ts / 1000.0
        path = marks_by_coin.get(coin) or []
        shadow = simulate_exit_on_path(
            side=side,
            entry_price=entry,
            path=path,
            entry_ts=entry_ts_sec,
            config=cfg,
            horizon_min=horizon_min,
            cost_bps=cost_bps,
        )
        if shadow is None:
            continue  # not measurable -> never fabricate a label
        did = f"refused:{coin}:{side}:{int(ts)}"
        rows.append(FeatureRow(decision_id=did, ts_ms=int(ts), features=_features_from_refusal(ev), context=SHADOW_CONTEXT))
        outcomes.append(Outcome(did, int(ts) + int(horizon_min * 60_000), round(float(shadow), 6)))
    return rows, outcomes


def summarize_refusal_corpus(rows: list[FeatureRow], outcomes: list[Outcome]) -> dict:
    n = len(outcomes)
    wins = sum(1 for o in outcomes if o.realized_net_pnl_usdc > 0)
    return {
        "shadow_samples": n,
        "would_have_won": wins,
        "would_have_lost": n - wins,
        "context": SHADOW_CONTEXT,
        "honesty": "shadow outcomes from real forward marks; unmeasurable refusals skipped; no fabrication",
    }


__all__ = ["SHADOW_CONTEXT", "rows_outcomes_from_refusals", "summarize_refusal_corpus"]
