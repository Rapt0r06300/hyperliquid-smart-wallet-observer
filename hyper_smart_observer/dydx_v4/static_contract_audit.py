from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import fields, is_dataclass
from typing import Any


DATACLASS_CONTRACTS: dict[str, tuple[str, ...]] = {
    "DydxV4Config": (
        "read_only",
        "paper_only",
        "allow_trading",
        "allow_private_key",
        "max_signal_age_ms",
        "hard_max_signal_age_ms",
        "fast_scanner_enabled",
        "fast_scanner_hot_capacity",
        "max_decision_wallets",
        "rest_poll_cap",
        "partial_tp_enabled",
        "breakeven_stop_enabled",
    ),
    "TremorObservation": (
        "market_id",
        "direction",
        "signal_age_ms",
        "edge_remaining_bps",
        "leading_wallets",
        "consensus_wallets",
        "source",
    ),
    "DirectorAssessment": (
        "opportunity_score",
        "risk_score",
        "net_score",
        "size_multiplier",
        "hard_block",
        "reasons",
        "notes",
        "read_only",
        "paper_only",
    ),
    "PaperProfileBias": (
        "sample_count",
        "positive_rate",
        "gain_loss_ratio",
        "net_usdc",
        "size_multiplier",
        "hard_block",
        "read_only",
        "paper_only",
    ),
    "RecallDecision": (
        "should_recall",
        "notional_usdc",
        "reasons",
        "notes",
        "read_only",
        "paper_only",
    ),
}


TO_DICT_CONTRACTS: dict[str, tuple[str, ...]] = {
    "DirectorAssessment": (
        "opportunity_score",
        "risk_score",
        "net_score",
        "size_multiplier",
        "hard_block",
        "reasons",
        "notes",
        "read_only",
        "paper_only",
    ),
    "PaperProfileBias": (
        "sample_count",
        "positive_rate",
        "gain_loss_ratio",
        "net_usdc",
        "size_multiplier",
        "hard_block",
        "reasons",
        "notes",
        "read_only",
        "paper_only",
    ),
    "RecallDecision": (
        "should_recall",
        "notional_usdc",
        "reasons",
        "notes",
        "read_only",
        "paper_only",
    ),
}


def _field_names(cls: type) -> set[str]:
    return {f.name for f in fields(cls)} if is_dataclass(cls) else set()


def _missing_keys(data: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    return [key for key in keys if key not in data]


def run_static_contract_audit() -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        from hyper_smart_observer.dydx_v4.config import DydxV4Config, load_config_from_env
        from hyper_smart_observer.dydx_v4.intelligence_director import DirectorAssessment, assess_decision_intelligence
        from hyper_smart_observer.dydx_v4.opportunity_recall import RecallDecision, evaluate_opportunity_recall
        from hyper_smart_observer.dydx_v4.paper_profile_memory import PaperProfileBias, profile_bias_for
        from hyper_smart_observer.dydx_v4.tremor_engine import TremorObservation
    except Exception as exc:
        return {"ok": False, "errors": [f"IMPORT_FAILURE:{type(exc).__name__}:{exc}"], "warnings": warnings, "read_only": True, "paper_only": True}

    classes = {
        "DydxV4Config": DydxV4Config,
        "TremorObservation": TremorObservation,
        "DirectorAssessment": DirectorAssessment,
        "PaperProfileBias": PaperProfileBias,
        "RecallDecision": RecallDecision,
    }
    for name, required in DATACLASS_CONTRACTS.items():
        cls = classes[name]
        if not is_dataclass(cls):
            errors.append(f"NOT_A_DATACLASS:{name}")
            continue
        missing = sorted(set(required) - _field_names(cls))
        if missing:
            errors.append(f"MISSING_DATACLASS_FIELDS:{name}:{missing}")

    cfg = load_config_from_env(DydxV4Config())
    if cfg.read_only is not True or cfg.paper_only is not True or cfg.allow_trading is not False or cfg.allow_private_key is not False:
        errors.append("CONFIG_SAFETY_CONTRACT_BROKEN")

    objects = {
        "DirectorAssessment": DirectorAssessment(1.0, 2.0, 0.0, 1.0, False, [], []),
        "PaperProfileBias": profile_bias_for("__STATIC__", "LONG", "stream", min_samples=999999),
        "RecallDecision": RecallDecision(False, 0.0, [], []),
    }
    for name, required in TO_DICT_CONTRACTS.items():
        obj = objects[name]
        if not hasattr(obj, "to_dict") or not callable(obj.to_dict):
            errors.append(f"MISSING_TO_DICT:{name}")
            continue
        data = obj.to_dict()
        if not isinstance(data, dict):
            errors.append(f"TO_DICT_NOT_DICT:{name}")
            continue
        missing = _missing_keys(data, required)
        if missing:
            errors.append(f"TO_DICT_MISSING_KEYS:{name}:{missing}")
        if data.get("read_only") is not True or data.get("paper_only") is not True:
            errors.append(f"TO_DICT_UNSAFE_FLAGS:{name}")

    sig_director = inspect.signature(assess_decision_intelligence)
    for param in ("tuned", "health", "state", "ctx"):
        if param not in sig_director.parameters:
            errors.append(f"DIRECTOR_SIGNATURE_MISSING:{param}")

    sig_recall = inspect.signature(evaluate_opportunity_recall)
    for param in ("tuned", "director", "reasons"):
        if param not in sig_recall.parameters:
            errors.append(f"RECALL_SIGNATURE_MISSING:{param}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "contracts_checked": sorted(DATACLASS_CONTRACTS),
        "to_dict_checked": sorted(TO_DICT_CONTRACTS),
        "read_only": True,
        "paper_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run static contracts audit for dYdX paper pipeline")
    parser.parse_args()
    report = run_static_contract_audit()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


__all__ = ["DATACLASS_CONTRACTS", "TO_DICT_CONTRACTS", "run_static_contract_audit"]
