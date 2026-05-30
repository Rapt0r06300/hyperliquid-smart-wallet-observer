from __future__ import annotations

from dataclasses import dataclass

from hl_observer.config.settings import ExecutionEnvironment, Settings
from hl_observer.hyperliquid.schemas import RiskDecision, SignalDecision
from hl_observer.utils.math import clamp
from hl_observer.risk.gates import RiskContext


@dataclass(slots=True)
class RiskEngine:
    settings: Settings

    def evaluate(self, context: RiskContext) -> RiskDecision:
        gates = {
            "mainnet_forbidden": not self.settings.execution.enable_mainnet_execution
            and self.settings.environment != ExecutionEnvironment.MAINNET,
            "testnet_locked_by_default": not self.settings.execution.enable_testnet_execution
            or self.settings.environment == ExecutionEnvironment.TESTNET,
            "signal_age": context.signal_age_ms <= self.settings.risk.max_signal_age_ms,
            "spread": context.spread_bps <= self.settings.risk.max_spread_bps,
            "slippage": context.slippage_bps <= self.settings.risk.max_slippage_bps,
            "liquidity": context.orderbook_depth_usdc >= self.settings.risk.min_orderbook_depth_usdc,
            "edge_remaining": context.edge_remaining_bps >= self.settings.risk.min_edge_required_bps,
            "gain_assurance": context.gain_assurance_score >= self.settings.risk.min_gain_assurance_score,
            "wallet_score": context.wallet_score >= self.settings.risk.min_wallet_score,
            "signal_score": context.signal_score >= self.settings.risk.min_signal_score,
            "kill_switch": not context.kill_switch_active and not self.settings.risk.kill_switch_active,
            "duplicate_order": not context.duplicate_order_risk,
            "data_gap": not context.data_gap,
            "api_stable": not context.api_unstable,
            "ws_stable": not context.ws_recently_reconnected,
            "reconciliation": not context.reconciliation_uncertain,
        }
        decision = SignalDecision.PAPER_TRADE
        reasons: list[str] = []

        if not gates["mainnet_forbidden"]:
            decision = SignalDecision.REJECT_MAINNET_FORBIDDEN
            reasons.append("mainnet execution forbidden")
        elif not gates["signal_age"]:
            decision = SignalDecision.REJECT_TOO_LATE
            reasons.append("signal is too old")
        elif context.edge_remaining_bps <= 0:
            decision = SignalDecision.REJECT_EDGE_NEGATIVE
            reasons.append("edge remaining is negative")
            gates["edge_remaining"] = False
        elif not gates["edge_remaining"]:
            decision = SignalDecision.REJECT_EDGE_TOO_SMALL
            reasons.append("edge remaining below minimum")
        elif not gates["gain_assurance"]:
            decision = SignalDecision.REJECT_EDGE_TOO_WEAK
            reasons.append(f"gain assurance {context.gain_assurance_score:.1f} too low")
        elif not gates["spread"]:
            decision = SignalDecision.REJECT_SPREAD_TOO_WIDE
            reasons.append("spread too wide")
        elif not gates["slippage"]:
            decision = SignalDecision.REJECT_SLIPPAGE_TOO_HIGH
            reasons.append("slippage too high")
        elif not gates["liquidity"]:
            decision = SignalDecision.REJECT_TOO_ILLIQUID
            reasons.append("orderbook depth too low")
        elif not gates["wallet_score"]:
            decision = SignalDecision.REJECT_WALLET_UNPROVEN
            reasons.append("wallet score too low")
        elif not gates["signal_score"]:
            decision = SignalDecision.OBSERVE_ONLY
            reasons.append("signal score too low")
        elif not gates["kill_switch"]:
            decision = SignalDecision.REJECT_API_UNSTABLE
            reasons.append("kill switch active")
        elif not gates["duplicate_order"]:
            decision = SignalDecision.REJECT_DUPLICATE_ORDER_RISK
            reasons.append("duplicate order risk")
        elif not gates["data_gap"]:
            decision = SignalDecision.REJECT_DATA_GAP
            reasons.append("data gap")
        elif not gates["api_stable"]:
            decision = SignalDecision.REJECT_API_UNSTABLE
            reasons.append("api unstable")
        elif not gates["ws_stable"]:
            decision = SignalDecision.REJECT_WS_RECENTLY_RECONNECTED
            reasons.append("ws recently reconnected")
        elif not gates["reconciliation"]:
            decision = SignalDecision.REJECT_RECONCILIATION_UNCERTAIN
            reasons.append("reconciliation uncertain")
        else:
            reasons.append("all paper gates passed")

        # Dynamic sizing based on Gain Assurance
        # 100% size at GA=80+, scales down linearly to 20% at GA=50
        multiplier = clamp((context.gain_assurance_score - 40.0) / 40.0, 0.2, 1.0)

        return RiskDecision(
            allowed=decision == SignalDecision.PAPER_TRADE,
            decision=decision,
            reasons=reasons,
            gates=gates,
            suggested_size_multiplier=multiplier if decision == SignalDecision.PAPER_TRADE else 0.0,
        )
