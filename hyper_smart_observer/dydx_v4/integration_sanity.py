from __future__ import annotations

import argparse
import json
from typing import Any


REQUIRED_CONFIG_FIELDS = (
    "read_only",
    "paper_only",
    "allow_trading",
    "allow_private_key",
    "max_signal_age_ms",
    "hard_max_signal_age_ms",
    "min_edge_bps",
    "fast_scanner_enabled",
    "fast_scanner_hot_capacity",
    "max_decision_wallets",
    "rest_poll_cap",
    "breakeven_stop_enabled",
    "partial_tp_enabled",
)


def _decision_pipeline_smoke() -> dict[str, Any]:
    from hyper_smart_observer.dydx_v4.decision_intelligence_v2 import (
        BudgetState,
        SessionHealth,
        decision_intelligence_v2,
    )
    from hyper_smart_observer.dydx_v4.tremor_engine import TremorObservation
    from hyper_smart_observer.dydx_v4.tuned_decision import TunedDecisionContext

    obs = TremorObservation(
        market_id="ETH-USD",
        direction="LONG",
        price_move_bps=18.0,
        volume_zscore=2.4,
        flow_imbalance=0.68,
        flow_volume_usdc=25_000.0,
        flow_trade_count=7,
        leading_wallets=3,
        consensus_wallets=3,
        signal_age_ms=2_500,
        edge_remaining_bps=8.0,
        market_regime="TRENDING",
        market_confidence=0.74,
        source="stream",
    )
    result = decision_intelligence_v2(
        obs,
        health=SessionHealth(closed_trades=12, winrate=0.54, profit_factor=1.22),
        budget_state=BudgetState(),
        ctx=TunedDecisionContext(spread_bps=3.0, slippage_bps=4.0, open_positions=0),
    )
    data = result.to_dict()
    required = {"action", "mode", "can_open", "notional_usdc", "tuned", "director", "reasons", "notes", "read_only", "paper_only"}
    missing = sorted(required - set(data))
    return {
        "ok": not missing and data.get("read_only") is True and data.get("paper_only") is True,
        "missing_keys": missing,
        "action": data.get("action"),
        "can_open": data.get("can_open"),
        "notional_usdc": data.get("notional_usdc"),
        "director_present": isinstance(data.get("director"), dict),
        "read_only": data.get("read_only"),
        "paper_only": data.get("paper_only"),
    }


def run_integration_sanity() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        from hyper_smart_observer.dydx_v4.config import DydxV4Config, load_config_from_env
        from hyper_smart_observer.dydx_v4.opportunity_calibration import calibration_summary
        from hyper_smart_observer.dydx_v4.intelligence_director import DirectorAssessment
        from hyper_smart_observer.dydx_v4.paper_profile_memory import profile_bias_for
        from hyper_smart_observer.dydx_v4.wallet_pool_ranker import MAX_LIVE_BATCH, pool_stats
        from hyper_smart_observer.dydx_v4.opportunity_recall import RecallDecision
    except Exception as exc:
        return {
            "ok": False,
            "errors": [f"IMPORT_FAILURE:{type(exc).__name__}:{exc}"],
            "warnings": warnings,
            "read_only": True,
            "paper_only": True,
        }

    cfg = load_config_from_env(DydxV4Config())
    for field in REQUIRED_CONFIG_FIELDS:
        if not hasattr(cfg, field):
            errors.append(f"MISSING_CONFIG_FIELD:{field}")

    if getattr(cfg, "read_only", None) is not True:
        errors.append("CONFIG_NOT_READ_ONLY")
    if getattr(cfg, "paper_only", None) is not True:
        errors.append("CONFIG_NOT_PAPER_ONLY")
    if getattr(cfg, "allow_trading", None) is not False:
        errors.append("CONFIG_ALLOW_TRADING_NOT_FALSE")
    if getattr(cfg, "allow_private_key", None) is not False:
        errors.append("CONFIG_ALLOW_PRIVATE_KEY_NOT_FALSE")

    if int(getattr(cfg, "max_signal_age_ms", 0) or 0) > int(getattr(cfg, "hard_max_signal_age_ms", 0) or 0):
        errors.append("SIGNAL_AGE_GT_HARD_SIGNAL_AGE")
    if int(getattr(cfg, "fast_scanner_hot_capacity", 0) or 0) < 500:
        warnings.append("FAST_SCANNER_HOT_CAPACITY_LOW")
    if int(getattr(cfg, "max_decision_wallets", 0) or 0) < 500:
        warnings.append("DECISION_WALLET_CAP_LOW")
    if int(getattr(cfg, "rest_poll_cap", 0) or 0) < 50:
        warnings.append("REST_POLL_CAP_LOW")

    director = DirectorAssessment(0.0, 0.0, 0.0, 1.0, False, [], [])
    if director.to_dict().get("read_only") is not True or director.to_dict().get("paper_only") is not True:
        errors.append("DIRECTOR_SAFETY_FLAGS_INVALID")

    bias = profile_bias_for("__SANITY__", "LONG", "stream", min_samples=999999)
    bias_dict = bias.to_dict()
    if bias_dict.get("read_only") is not True or bias_dict.get("paper_only") is not True:
        errors.append("PROFILE_MEMORY_SAFETY_FLAGS_INVALID")

    recall = RecallDecision(False, 0.0, [], [])
    recall_dict = recall.to_dict()
    if recall_dict.get("read_only") is not True or recall_dict.get("paper_only") is not True:
        errors.append("RECALL_SAFETY_FLAGS_INVALID")

    if MAX_LIVE_BATCH < 500:
        warnings.append("MAX_LIVE_BATCH_LOW")

    try:
        decision_smoke = _decision_pipeline_smoke()
    except Exception as exc:
        decision_smoke = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
    if decision_smoke.get("ok") is not True:
        errors.append("DECISION_PIPELINE_SMOKE_FAILED")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "config_summary": calibration_summary(cfg),
        "pool_stats": pool_stats(),
        "profile_bias_sample": bias_dict,
        "decision_pipeline_smoke": decision_smoke,
        "read_only": True,
        "paper_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dYdX paper-only integration sanity checks")
    parser.parse_args()
    print(json.dumps(run_integration_sanity(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["REQUIRED_CONFIG_FIELDS", "run_integration_sanity"]
