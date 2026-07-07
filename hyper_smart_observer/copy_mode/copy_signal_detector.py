from __future__ import annotations

from typing import Any

from hyper_smart_observer.copy_mode.copy_models import LeaderDelta, NoTradeDecision, NoTradeReason, SignalCandidate, SignalDecision
from hyper_smart_observer.copy_mode.no_trade_report import decision_from_reason, decisions_from_signal
from hyper_smart_observer.copy_mode.signal_candidate import build_signal_candidate


def detect_signal_candidates(
    deltas: list[LeaderDelta],
    *,
    leader_expected_edge_bps: float | None,
    leader_expected_edges_bps: dict[str, float | None] | None = None,
    leader_scores: dict[str, float] | None = None,
    current_mids: dict[str, float] | None = None,
    market_features: dict[str, Any] | None = None,
    blocked_assets: set[str] | None = None,
    duplicate_hashes: set[str] | None = None,
    open_paper_positions: set[tuple[str, str]] | None = None,
    min_edge_required_bps: float = 8.0,
    min_liquidity_score: float = 0.50,
) -> tuple[list[SignalCandidate], list[NoTradeDecision]]:
    leader_expected_edges_bps = {
        key.lower(): value for key, value in (leader_expected_edges_bps or {}).items()
    }
    leader_scores = {key.lower(): value for key, value in (leader_scores or {}).items()}
    current_mids = {key.upper(): value for key, value in (current_mids or {}).items()}
    # Per-coin MarketSignalFeatures (real l2Book-derived spread/liquidity/mid).
    market_features = {key.upper(): value for key, value in (market_features or {}).items()}
    blocked_assets = {coin.upper() for coin in (blocked_assets or set())}
    duplicate_hashes = duplicate_hashes or set()
    open_paper_positions = {(wallet.lower(), coin.upper()) for wallet, coin in (open_paper_positions or set())}
    signals: list[SignalCandidate] = []
    no_trade: list[NoTradeDecision] = []
    for delta in deltas:
        observed = f"{delta.action_type.value} {delta.coin} leader {delta.leader_wallet}"
        if delta.action_type.value == "UNKNOWN":
            no_trade.append(
                decision_from_reason(
                    NoTradeReason.UNKNOWN_DELTA,
                    observed=observed,
                    leader_wallet=delta.leader_wallet,
                    coin=delta.coin,
                    context={"warnings": delta.warnings, "raw_event_hash": delta.raw_event_hash},
                )
            )
            continue
        if delta.raw_event_hash and delta.raw_event_hash in duplicate_hashes:
            no_trade.append(
                decision_from_reason(
                    NoTradeReason.DUPLICATE_FILL,
                    observed=observed,
                    leader_wallet=delta.leader_wallet,
                    coin=delta.coin,
                    context={"raw_event_hash": delta.raw_event_hash},
                )
            )
            continue
        if delta.coin.upper() in blocked_assets:
            no_trade.append(
                decision_from_reason(
                    NoTradeReason.BLOCKED_ASSET,
                    observed=observed,
                    leader_wallet=delta.leader_wallet,
                    coin=delta.coin,
                )
            )
            continue
        if delta.action_type.value.startswith("CLOSE") or delta.action_type.value == "REDUCE":
            if (delta.leader_wallet.lower(), delta.coin.upper()) not in open_paper_positions:
                no_trade.append(
                    decision_from_reason(
                        NoTradeReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE,
                        observed=observed,
                        leader_wallet=delta.leader_wallet,
                        coin=delta.coin,
                    )
                )
                continue
        # Inject real market features (spread / liquidity / mid) into the gates so
        # they actually influence the decision. Absent features => safe defaults.
        feat = market_features.get(delta.coin.upper())
        feature_kwargs: dict[str, Any] = {}
        feature_mid = None
        if feat is not None:
            feature_mid = getattr(feat, "current_mid", None)
            spread = getattr(feat, "spread_bps", None)
            if spread is not None:
                feature_kwargs["spread_bps"] = float(spread)
            liquidity = getattr(feat, "liquidity_score", None)
            if liquidity is not None:
                feature_kwargs["liquidity_score"] = float(liquidity)
        signal = build_signal_candidate(
            delta,
            leader_expected_edge_bps=leader_expected_edges_bps.get(
                delta.leader_wallet.lower(), leader_expected_edge_bps
            ),
            current_mid=feature_mid or current_mids.get(delta.coin.upper()) or delta.leader_reference_price,
            leader_score=leader_scores.get(delta.leader_wallet.lower(), 0.0),
            min_edge_required_bps=min_edge_required_bps,
            min_liquidity_score=min_liquidity_score,
            **feature_kwargs,
        )
        signals.append(signal)
        if signal.decision == SignalDecision.REJECT_NO_TRADE:
            no_trade.extend(decisions_from_signal(signal))
    return signals, no_trade
