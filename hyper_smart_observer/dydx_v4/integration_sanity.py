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

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "config_summary": calibration_summary(cfg),
        "pool_stats": pool_stats(),
        "profile_bias_sample": bias_dict,
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
