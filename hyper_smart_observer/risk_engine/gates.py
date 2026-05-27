from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig, RuntimeMode
from hyper_smart_observer.hyperliquid_client.models import (
    PaperIntent,
    ScoreBreakdown,
    Signal,
    WalletScoreStatus,
    WalletStatus,
)
from hyper_smart_observer.risk_engine.limits import RiskLimits
from hyper_smart_observer.risk_engine.refusal_reasons import RiskRefusalReason
from hyper_smart_observer.risk_engine.risk_state import RiskDecision


def refuse(reason: RiskRefusalReason, message: str, gates: dict[str, bool] | None = None) -> RiskDecision:
    return RiskDecision(False, reason.value, message, gates or {})


def evaluate_signal(
    signal: Signal | None,
    context: dict,
    config: AppConfig,
    limits: RiskLimits | None = None,
) -> RiskDecision:
    """Deny-by-default signal gate for research/paper/testnet-only flow."""

    limits = limits or RiskLimits()
    gates: dict[str, bool] = {
        "signal_present": signal is not None,
        "mainnet_forbidden": not config.allow_mainnet,
        "mode_allowed": config.mode in {mode.value for mode in RuntimeMode},
        "execution_disabled_or_paper": not config.execution_enabled
        or config.mode == RuntimeMode.PAPER_TRADING.value,
    }
    if signal is None:
        return refuse(RiskRefusalReason.DENY_BY_DEFAULT, "No signal provided.", gates)
    if config.allow_mainnet:
        gates["mainnet_forbidden"] = False
        return refuse(RiskRefusalReason.MAINNET_FORBIDDEN, "Mainnet is forbidden.", gates)
    if not gates["mode_allowed"]:
        return refuse(RiskRefusalReason.MODE_FORBIDDEN, "Mode is not allowed.", gates)
    if context.get("wallet_status") == WalletStatus.BLOCKED.value:
        gates["wallet_not_blocked"] = False
        return refuse(RiskRefusalReason.WALLET_BLOCKED, "Wallet is blocked.", gates)
    sample_size = int(context.get("sample_size") or 0)
    if sample_size < limits.min_sample_size:
        gates["data_sufficient"] = False
        return refuse(RiskRefusalReason.INSUFFICIENT_DATA, "Insufficient sample size.", gates)
    wallet_score = context.get("wallet_score")
    if wallet_score is None:
        gates["score_present"] = False
        return refuse(RiskRefusalReason.SCORE_MISSING, "Wallet score is missing.", gates)
    if float(wallet_score) < limits.min_wallet_score or signal.confidence < limits.min_confidence:
        gates["confidence_minimum"] = False
        return refuse(RiskRefusalReason.CONFIDENCE_TOO_LOW, "Score or confidence too low.", gates)
    if config.testnet_execution_enabled and not config.confirm_testnet_only:
        gates["testnet_confirmed"] = False
        return refuse(
            RiskRefusalReason.TESTNET_CONFIRMATION_REQUIRED,
            "Testnet execution requires explicit confirmation.",
            gates,
        )
    return RiskDecision(True, "PAPER_ALLOWED", "Paper-only signal accepted.", gates)


def allow_only_if_all_gates_pass(decisions: list[RiskDecision]) -> RiskDecision:
    for decision in decisions:
        if not decision.allowed:
            return decision
    return RiskDecision(True, "ALL_GATES_PASSED", "All gates passed.")


def evaluate_wallet_score_for_research(
    score_breakdown: ScoreBreakdown, config: AppConfig | None = None
) -> RiskDecision:
    """Gate a wallet score for observation only.

    Passing this gate never authorizes an order. It only means the score is
    good enough to be shown as a research observation.
    """

    config = config or AppConfig()
    min_confidence = config.score_min_confidence * 100.0
    gates = {
        "scored": score_breakdown.status == WalletScoreStatus.SCORED,
        "sample_quality_minimum": score_breakdown.sample_quality_score >= 60.0,
        "confidence_minimum": score_breakdown.confidence_score >= min_confidence,
        "profit_factor_present": score_breakdown.profit_factor is not None,
        "net_pnl_present": not config.score_require_net_pnl or score_breakdown.net_pnl is not None,
        "risk_not_extreme": score_breakdown.risk_score >= 20.0,
        "execution_forbidden": True,
    }
    if not gates["scored"]:
        return refuse(
            RiskRefusalReason.WALLET_SCORE_NOT_SCORED,
            "Wallet score is not in SCORED status.",
            gates,
        )
    if not gates["sample_quality_minimum"]:
        return refuse(
            RiskRefusalReason.WALLET_SCORE_SAMPLE_LOW,
            "Wallet sample quality is too low for research ranking.",
            gates,
        )
    if not gates["confidence_minimum"]:
        return refuse(
            RiskRefusalReason.WALLET_SCORE_CONFIDENCE_LOW,
            "Wallet score confidence is too low.",
            gates,
        )
    if not gates["profit_factor_present"]:
        return refuse(
            RiskRefusalReason.WALLET_SCORE_PROFIT_FACTOR_MISSING,
            "Profit factor is missing; score remains observation-only rejected.",
            gates,
        )
    if not gates["net_pnl_present"]:
        return refuse(
            RiskRefusalReason.WALLET_SCORE_NET_PNL_MISSING,
            "Net PnL is missing and cannot be invented.",
            gates,
        )
    if not gates["risk_not_extreme"]:
        return refuse(
            RiskRefusalReason.WALLET_SCORE_RISK_TOO_HIGH,
            "Wallet drawdown/risk profile is too high for research ranking.",
            gates,
        )
    return RiskDecision(
        True,
        RiskRefusalReason.RESEARCH_OBSERVATION_ONLY.value,
        "Eligible for research observation only; this is not a trading signal.",
        gates,
    )


def evaluate_paper_intent(
    intent: PaperIntent,
    wallet_score: ScoreBreakdown | None,
    config: AppConfig,
    portfolio_state: dict,
) -> RiskDecision:
    """Evaluate a local paper intent before any simulation is opened."""

    gates = {
        "paper_enabled": config.enable_paper_trading,
        "mode_allowed": config.mode in {mode.value for mode in RuntimeMode},
        "no_execution_enabled": not config.execution_enabled and not config.testnet_execution_enabled,
        "wallet_score_present": wallet_score is not None,
        "side_valid": intent.side.upper() in {"BUY", "SELL"},
        "price_valid": intent.reference_price > 0,
        "notional_valid": intent.requested_notional > 0,
        "notional_within_limit": intent.requested_notional <= config.paper_max_position_notional,
        "open_trade_limit": int(portfolio_state.get("open_trades", 0)) < config.paper_max_open_trades,
    }
    if not gates["paper_enabled"]:
        return refuse(RiskRefusalReason.PAPER_TRADING_DISABLED, "Paper trading is disabled.", gates)
    if not gates["mode_allowed"]:
        return refuse(RiskRefusalReason.MODE_FORBIDDEN, "Runtime mode is not allowed.", gates)
    if not gates["no_execution_enabled"]:
        return refuse(
            RiskRefusalReason.EXECUTION_DISABLED,
            "Paper simulation refuses when execution/testnet flags are enabled.",
            gates,
        )
    if wallet_score is None:
        return refuse(
            RiskRefusalReason.PAPER_WALLET_SCORE_MISSING,
            "Wallet score is required before local paper simulation.",
            gates,
        )
    gates["wallet_score_scored"] = wallet_score.status == WalletScoreStatus.SCORED
    gates["wallet_confidence_minimum"] = (
        wallet_score.confidence_score >= config.paper_min_wallet_confidence * 100.0
    )
    gates["wallet_sample_quality_minimum"] = (
        wallet_score.sample_quality_score >= config.paper_min_sample_quality * 100.0
    )
    if not gates["wallet_score_scored"]:
        return refuse(
            RiskRefusalReason.PAPER_WALLET_SCORE_NOT_SCORED,
            "Wallet score is not SCORED.",
            gates,
        )
    if not gates["wallet_confidence_minimum"]:
        return refuse(
            RiskRefusalReason.PAPER_CONFIDENCE_TOO_LOW,
            "Wallet score confidence is too low for paper simulation.",
            gates,
        )
    if not gates["wallet_sample_quality_minimum"]:
        return refuse(
            RiskRefusalReason.PAPER_SAMPLE_QUALITY_TOO_LOW,
            "Wallet sample quality is too low for paper simulation.",
            gates,
        )
    if not gates["side_valid"]:
        return refuse(RiskRefusalReason.PAPER_INVALID_SIDE, "Paper side must be BUY or SELL.", gates)
    if not gates["price_valid"]:
        return refuse(RiskRefusalReason.PAPER_INVALID_PRICE, "Reference price must be positive.", gates)
    if not gates["notional_valid"]:
        return refuse(
            RiskRefusalReason.PAPER_INVALID_NOTIONAL,
            "Requested notional must be positive.",
            gates,
        )
    if not gates["notional_within_limit"]:
        return refuse(
            RiskRefusalReason.PAPER_NOTIONAL_TOO_HIGH,
            "Requested paper notional exceeds configured limit.",
            gates,
        )
    if not gates["open_trade_limit"]:
        return refuse(
            RiskRefusalReason.PAPER_MAX_OPEN_TRADES_REACHED,
            "Maximum open paper simulations reached.",
            gates,
        )
    return RiskDecision(
        True,
        RiskRefusalReason.PAPER_SIMULATION_ONLY.value,
        "Accepted for local paper simulation only. Not a trading signal. Not an order.",
        gates,
        decision_scope="PAPER_SIMULATION_ONLY",
    )
