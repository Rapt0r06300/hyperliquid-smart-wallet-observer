from __future__ import annotations

import argparse
import importlib
import json
from typing import Any


CRITICAL_MODULES = (
    "hyper_smart_observer.dydx_v4.config",
    "hyper_smart_observer.dydx_v4.opportunity_calibration",
    "hyper_smart_observer.dydx_v4.tremor_engine",
    "hyper_smart_observer.dydx_v4.tuned_decision",
    "hyper_smart_observer.dydx_v4.decision_intelligence_v2",
    "hyper_smart_observer.dydx_v4.intelligence_director",
    "hyper_smart_observer.dydx_v4.paper_profile_memory",
    "hyper_smart_observer.dydx_v4.wallet_pool_ranker",
    "hyper_smart_observer.dydx_v4.opportunity_recall",
    "hyper_smart_observer.dydx_v4.integration_sanity",
    "hyper_smart_observer.dydx_v4.whale_ranker",
    "hyper_smart_observer.dydx_v4.leaderboard_import_patch",
)


REQUIRED_DECISION_KEYS = (
    "action",
    "mode",
    "can_open",
    "notional_usdc",
    "tuned",
    "director",
    "reasons",
    "notes",
    "read_only",
    "paper_only",
)


def _fail(errors: list[str], code: str, detail: Any = None) -> None:
    errors.append(code if detail is None else f"{code}:{detail}")


def _decision_case(obs_kwargs: dict[str, Any], health_kwargs: dict[str, Any] | None = None, ctx_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    from hyper_smart_observer.dydx_v4.decision_intelligence_v2 import (
        BudgetState,
        SessionHealth,
        decision_intelligence_v2,
    )
    from hyper_smart_observer.dydx_v4.tremor_engine import TremorObservation
    from hyper_smart_observer.dydx_v4.tuned_decision import TunedDecisionContext

    result = decision_intelligence_v2(
        TremorObservation(**obs_kwargs),
        health=SessionHealth(**(health_kwargs or {})),
        budget_state=BudgetState(),
        ctx=TunedDecisionContext(**(ctx_kwargs or {})),
    )
    return result.to_dict()


def _base_obs(**overrides: Any) -> dict[str, Any]:
    data = {
        "market_id": "ETH-USD",
        "direction": "LONG",
        "price_move_bps": 22.0,
        "volume_zscore": 2.8,
        "flow_imbalance": 0.70,
        "flow_volume_usdc": 30_000.0,
        "flow_trade_count": 8,
        "leading_wallets": 3,
        "consensus_wallets": 3,
        "signal_age_ms": 2_000,
        "edge_remaining_bps": 9.0,
        "market_regime": "TRENDING",
        "market_confidence": 0.75,
        "source": "stream",
    }
    data.update(overrides)
    return data


def run_mega_audit() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    imported: list[str] = []

    for module_name in CRITICAL_MODULES:
        try:
            importlib.import_module(module_name)
            imported.append(module_name)
        except Exception as exc:
            _fail(errors, "IMPORT_ERROR", f"{module_name}:{type(exc).__name__}:{exc}")

    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings, "imported": imported, "read_only": True, "paper_only": True}

    from hyper_smart_observer.dydx_v4.config import DydxV4Config, load_config_from_env
    from hyper_smart_observer.dydx_v4.integration_sanity import run_integration_sanity
    from hyper_smart_observer.dydx_v4.opportunity_calibration import calibration_summary
    from hyper_smart_observer.dydx_v4.paper_profile_memory import profile_bias_for
    from hyper_smart_observer.dydx_v4.wallet_pool_ranker import MAX_LIVE_BATCH, wallet_pool_batch

    cfg = load_config_from_env(DydxV4Config())
    if cfg.read_only is not True:
        _fail(errors, "CFG_READ_ONLY_FALSE")
    if cfg.paper_only is not True:
        _fail(errors, "CFG_PAPER_ONLY_FALSE")
    if cfg.allow_trading is not False:
        _fail(errors, "CFG_ALLOW_TRADING_TRUE")
    if cfg.allow_private_key is not False:
        _fail(errors, "CFG_ALLOW_PRIVATE_KEY_TRUE")
    if cfg.max_signal_age_ms > cfg.hard_max_signal_age_ms:
        _fail(errors, "CFG_SIGNAL_AGE_CONFLICT")
    if cfg.fast_scanner_hot_capacity < 500:
        _fail(errors, "CFG_HOT_CAPACITY_TOO_LOW")
    if cfg.max_decision_wallets < 500:
        _fail(errors, "CFG_DECISION_WALLETS_TOO_LOW")
    if cfg.rest_poll_cap < 50:
        _fail(errors, "CFG_REST_POLL_TOO_LOW")

    sanity = run_integration_sanity()
    if sanity.get("ok") is not True:
        _fail(errors, "INTEGRATION_SANITY_FAILED", sanity.get("errors"))

    decision_cases = {
        "strong": _decision_case(
            _base_obs(),
            health_kwargs={"closed_trades": 12, "winrate": 0.54, "profit_factor": 1.22},
            ctx_kwargs={"spread_bps": 3.0, "slippage_bps": 4.0, "open_positions": 0},
        ),
        "no_edge": _decision_case(
            _base_obs(edge_remaining_bps=0.0),
            health_kwargs={"closed_trades": 12, "winrate": 0.54, "profit_factor": 1.22},
            ctx_kwargs={"spread_bps": 3.0, "slippage_bps": 4.0, "open_positions": 0},
        ),
        "weak_session": _decision_case(
            _base_obs(),
            health_kwargs={"closed_trades": 60, "winrate": 0.40, "profit_factor": 0.8, "consecutive_losses": 4, "daily_pnl_usdc": -20.0},
            ctx_kwargs={"spread_bps": 5.0, "slippage_bps": 6.0, "open_positions": 1},
        ),
    }
    for name, data in decision_cases.items():
        missing = [key for key in REQUIRED_DECISION_KEYS if key not in data]
        if missing:
            _fail(errors, "DECISION_RESULT_MISSING_KEYS", f"{name}:{missing}")
        if data.get("read_only") is not True or data.get("paper_only") is not True:
            _fail(errors, "DECISION_RESULT_UNSAFE_FLAGS", name)
    if decision_cases["no_edge"].get("can_open") is True:
        _fail(errors, "NO_EDGE_CASE_CAN_OPEN")
    if decision_cases["weak_session"].get("can_open") is True and float(decision_cases["weak_session"].get("notional_usdc") or 0.0) > float(decision_cases["strong"].get("notional_usdc") or 0.0):
        _fail(errors, "WEAK_SESSION_NOTIONAL_GT_STRONG")

    class Dummy:
        def __init__(self, address: str, score: float) -> None:
            self.address = address
            self.score = score

    pool = wallet_pool_batch([Dummy(f"w{i}", 1000.0 - i) for i in range(1000)], limit=2500, scorer=lambda x: x.score)
    if len(pool) > MAX_LIVE_BATCH:
        _fail(errors, "WALLET_POOL_EXCEEDS_MAX_LIVE_BATCH")
    if len(pool) == 0:
        _fail(errors, "WALLET_POOL_EMPTY_ON_NONEMPTY_INPUT")

    profile = profile_bias_for("__SANITY__", "LONG", "stream", min_samples=999999).to_dict()
    if profile.get("read_only") is not True or profile.get("paper_only") is not True:
        _fail(errors, "PROFILE_BIAS_UNSAFE_FLAGS")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "imported": imported,
        "config_summary": calibration_summary(cfg),
        "integration_sanity": sanity,
        "decision_cases": decision_cases,
        "wallet_pool_sample_size": len(pool),
        "profile_bias_sample": profile,
        "read_only": True,
        "paper_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mega audit for the dYdX paper pipeline")
    parser.parse_args()
    report = run_mega_audit()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


__all__ = ["CRITICAL_MODULES", "REQUIRED_DECISION_KEYS", "run_mega_audit"]
