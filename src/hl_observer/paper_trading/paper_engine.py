from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from hashlib import sha256

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.schemas import RiskDecision
from hl_observer.paper_trading.canonical_execution import (
    CausalMarketSnapshot,
    PaperExecutionIntent,
    execute_paper_intent,
)
from hl_observer.paper_trading.exec_model import (
    ExecModelConfig,
    ExecResult,
    book_notional_for_quantity,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.liquidity_consumption import LiquidityConsumptionLedger
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.simulation.paper_ledger import PaperLedger


@dataclass(frozen=True, slots=True)
class PaperEngineConfig:
    starting_cash_usdt: float = 1_000.0
    max_position_usdt: float = 40.0  # Margin per position.
    # Backward-compatible name: this setting has always capped margin, not
    # gross notional. New callers should prefer max_total_margin_usdt.
    max_total_exposure_usdt: float = 1_200.0
    max_total_margin_usdt: float | None = None
    max_open_positions: int = 60
    leverage: float = 1.0
    default_top_depth_usdt: float | None = None
    strict_execution_truth: bool = True
    max_execution_book_age_ms: int = 5_000
    min_execution_fill_ratio: float = 0.0
    exec_model: ExecModelConfig = field(default_factory=ExecModelConfig)


@dataclass(frozen=True, slots=True)
class PaperPosition:
    position_id: str
    coin: str
    side: str  # LONG | SHORT
    quantity: float
    entry_price: float
    notional_usdt: float
    opened_at_ms: int
    source_delta_id: str
    leader_wallet: str
    margin_locked_usdt: float = 0.0
    leverage_effective: float = 1.0
    leg_notional_usdt: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class PaperTrade:
    trade_id: str
    action: str  # OPEN | REDUCE | CLOSE | NO_TRADE
    coin: str
    side: str
    quantity: float
    fill_price: float | None
    notional_usdt: float
    realized_pnl_usdt: float
    fees_and_cost_bps: float
    source_delta_id: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    requested_notional_usdt: float = 0.0
    filled_notional_usdt: float = 0.0
    missed_notional_usdt: float = 0.0
    fill_ratio: float = 0.0
    cost_status: str = "NOT_APPLICABLE"
    execution_snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class PaperDecisionResult:
    accepted: bool
    risk_decision: RiskDecision
    trade: PaperTrade | None
    position: PaperPosition | None
    cash_usdt: float
    equity_usdt: float
    realized_pnl_usdt: float
    unrealized_pnl_usdt: float
    drawdown_usdt: float
    reason_codes: tuple[str, ...]
    evidence_hash: str
    ledger_snapshot: dict[str, object] | None = None
    decision_context: dict[str, object] = field(default_factory=dict)


class PaperEngine:
    """Local-only paper engine for V12 vertical slices.

    The engine mutates only in-memory simulated state. It never creates a venue
    order, never signs, and never calls an external endpoint.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        config: PaperEngineConfig | None = None,
        ledger: PaperLedger | None = None,
        liquidity_ledger: LiquidityConsumptionLedger | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.config = config or PaperEngineConfig()
        self._risk_engine = RiskEngine(self.settings)
        self.cash_usdt = float(self.config.starting_cash_usdt)
        self.realized_pnl_usdt = 0.0
        self._positions: dict[str, PaperPosition] = {}
        self._high_water_equity = self.cash_usdt
        self.ledger = ledger or PaperLedger(starting_balance_usdc=self.cash_usdt)
        self.liquidity_ledger = liquidity_ledger or LiquidityConsumptionLedger()

    @property
    def positions(self) -> tuple[PaperPosition, ...]:
        return tuple(self._positions.values())

    def restore_position(
        self,
        position: PaperPosition,
        *,
        refs: dict[str, object] | None = None,
    ) -> None:
        """Restore one recorded paper position without inventing a new fill.

        Runtime adapters may restart while a paper position remains open.  The
        recorded effective entry price and quantity are therefore imported as
        an opening ledger event with zero additional fee.  Calling this method
        twice for the same identity is idempotent; conflicting identities are
        rejected instead of silently changing economic history.
        """

        existing = self._positions.get(position.position_id)
        if existing is not None:
            if existing != position:
                raise ValueError("paper position restore identity conflict")
            return
        if (
            not _finite_positive_or_false(position.quantity)
            or not _finite_positive_or_false(position.entry_price)
            or not _finite_positive_or_false(position.notional_usdt)
            or position.side not in {"LONG", "SHORT"}
        ):
            raise ValueError("invalid paper position restore payload")
        self._positions[position.position_id] = position
        self.ledger.open_position(
            coin=position.coin,
            side=position.side,
            notional_usdc=position.notional_usdt,
            quantity=position.quantity,
            fill_price=position.entry_price,
            timestamp_ms=position.opened_at_ms,
            fee_bps=0.0,
            leverage_effective=max(1.0, position.leverage_effective),
            leg_notional_usd=position.leg_notional_usdt or (position.notional_usdt,),
            leg_direction=((1 if position.side == "LONG" else -1),),
            position_id=position.position_id,
            refs={
                "restore": "RECORDED_PAPER_POSITION",
                "no_new_fill": True,
                **dict(refs or {}),
            },
        )

    def apply_delta(
        self,
        delta: LeaderDelta,
        *,
        market_price: float,
        observed_at_ms: int,
        edge_remaining_bps: float,
        spread_bps: float,
        estimated_slippage_bps: float,
        top_depth_usdt: float | None,
        wallet_score: float,
        signal_score: float,
        marks: dict[str, float] | None = None,
        margin_scale: float = 1.0,
        decision_context: dict[str, object] | None = None,
        execution_truth: ExecutionTruth | None = None,
        queue_ahead_usdt: float = 0.0,
        queue_depletion_usdt: float | None = None,
        traded_through_usdt: float | None = None,
        adverse_selection_bps: float | None = None,
    ) -> PaperDecisionResult:
        reasons: list[str] = list(delta.reason_codes)
        signal_age_ms = max(0, observed_at_ms - (delta.leader_event_time_ms or observed_at_ms))
        context = dict(decision_context or {})
        context.update(
            {
                "leader_delta_id": delta.delta_id,
                "leader_wallet": delta.wallet,
                "leader_action": getattr(delta.action, "value", str(delta.action)),
                "leader_event_time_ms": delta.leader_event_time_ms,
                "source": delta.source,
                "evidence_ref": delta.evidence_ref,
                "signal_age_ms": signal_age_ms,
                "edge_remaining_bps": edge_remaining_bps,
                "spread_bps": spread_bps,
                "estimated_slippage_bps": estimated_slippage_bps,
                "configured_top_depth_usdt": top_depth_usdt,
                "wallet_score": wallet_score,
                "signal_score": signal_score,
                "execution_snapshot_id": execution_truth.snapshot_id if execution_truth else None,
                "execution_source": execution_truth.source if execution_truth else None,
            }
        )
        if not _finite_positive_or_false(market_price):
            reasons.append("MARKET_PRICE_INVALID")
        for name, value in (
            ("EDGE_REMAINING_INVALID", edge_remaining_bps),
            ("SPREAD_INVALID", spread_bps),
            ("SLIPPAGE_INVALID", estimated_slippage_bps),
            ("WALLET_SCORE_INVALID", wallet_score),
            ("SIGNAL_SCORE_INVALID", signal_score),
            ("MARGIN_SCALE_INVALID", margin_scale),
        ):
            if not _finite_or_false(value):
                reasons.append(name)
        if execution_truth is not None and execution_truth.coin != str(delta.coin).upper():
            reasons.append("EXECUTION_BOOK_COIN_MISMATCH")
        if self.config.strict_execution_truth and execution_truth is None:
            reasons.append("NO_LIVE_EXECUTABLE_BOOK")
        if not delta.safe_for_paper_candidate and not delta.is_exit_or_reduce:
            reasons.append("DELTA_NOT_SAFE_FOR_PAPER")

        risk_depth = _risk_depth(execution_truth)
        if risk_depth is None and not self.config.strict_execution_truth:
            risk_depth = top_depth_usdt
        context["top_depth_usdt"] = risk_depth
        risk_context = RiskContext(
            spread_bps=_finite_or_default(spread_bps),
            estimated_slippage_bps=_finite_or_default(estimated_slippage_bps),
            orderbook_depth_usdc=_finite_or_default(risk_depth),
            wallet_score=_finite_or_default(wallet_score),
            signal_score=_finite_or_default(signal_score),
            edge_remaining_bps=_finite_or_default(edge_remaining_bps),
            signal_age_ms=signal_age_ms,
            data_gap=not _finite_positive_or_false(market_price) or (
                self.config.strict_execution_truth and execution_truth is None
            ),
        )
        risk_decision = self._risk_engine.evaluate(risk_context)
        if not risk_decision.allowed and not delta.is_exit_or_reduce:
            reasons.extend(risk_decision.reasons)

        if reasons or not _finite_positive_or_false(market_price):
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, reasons, decision_context=context),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=reasons,
                decision_context=context,
            )

        if delta.is_exit_or_reduce:
            return self._apply_exit_delta(
                delta,
                market_price=market_price,
                observed_at_ms=observed_at_ms,
                risk_decision=risk_decision,
                marks=marks,
                decision_context=context,
                execution_truth=execution_truth,
            )

        side = _side_for_entry(delta)
        if side is None:
            reasons.append("ENTRY_SIDE_UNKNOWN")
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, reasons, decision_context=context),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=reasons,
                decision_context=context,
            )
        if len(self._positions) >= self.config.max_open_positions:
            reasons.append("MAX_OPEN_POSITIONS_REACHED")
        margin_cap = self._margin_cap_usdt()
        if self._margin_locked_usdt() >= margin_cap:
            reasons.append("MAX_TOTAL_EXPOSURE_REACHED")
        if reasons:
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, reasons, decision_context=context),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=reasons,
                decision_context=context,
            )

        # margin (capital deployed) is capped; the position controls margin*leverage of notional.
        # margin_scale (<=1.0) permet un sizing proportionnel (consensus whale)
        # sans jamais dépasser le cap de position ni l'exposition restante.
        safe_scale = min(1.0, max(0.1, float(margin_scale or 1.0)))
        margin = min(
            self.config.max_position_usdt * safe_scale,
            max(0.0, margin_cap - self._margin_locked_usdt()),
        )
        notional = margin * max(1.0, float(self.config.leverage))
        # BUG CORRIGE (chasse aux bugs PnL 2026-07-11) — LA LATENCE N'ETAIT PAS TRANSMISE.
        # `spread_bps` et `estimated_slippage_bps` sont recus en parametres, servent au RiskContext
        # (donc a DECIDER)... et n'arrivaient JAMAIS jusqu'au prix de fill. Quant a `latency_sec`,
        # il n'etait pas passe du tout : il valait 0, alors qu'on copie un leader avec un retard
        # MEDIAN MESURE de 57 secondes. Resultat : le prix d'entree paper etait celui du leader,
        # sans le moindre cout de copie -- et dans 8 cas sur 20 le bot entrait a un prix MEILLEUR
        # que le marche, ce qui est physiquement impossible.
        _signal_age_ms = max(0, observed_at_ms - (delta.leader_event_time_ms or observed_at_ms))
        canonical_execution = execute_paper_intent(
            _paper_intent_for_delta(
                delta,
                side=side,
                action=(
                    "ADD"
                    if delta.action in {LifecycleAction.ADD, LifecycleAction.INCREASE}
                    else "OPEN"
                ),
                notional_usdt=notional,
                observed_at_ms=observed_at_ms,
                decision_context=context,
            ),
            CausalMarketSnapshot(
                coin=delta.coin,
                reference_mid=market_price,
                decision_ts_ms=observed_at_ms,
                execution_truth=execution_truth,
                source=execution_truth.source if execution_truth is not None else "paper_engine_compat",
            ),
            config=self.config.exec_model,
            strict_book=self.config.strict_execution_truth,
            min_fill_ratio=self.config.min_execution_fill_ratio,
            max_book_age_ms=self.config.max_execution_book_age_ms,
            top_depth_usdc=top_depth_usdt,
            is_maker=_maker_execution_style_enabled(),
            latency_sec=_signal_age_ms / 1000.0,
            queue_ahead_usdc=queue_ahead_usdt,
            queue_depletion_usdc=queue_depletion_usdt,
            traded_through_usdc=traded_through_usdt,
            adverse_selection_bps=adverse_selection_bps,
            liquidity_ledger=self.liquidity_ledger,
        )
        exec_result = canonical_execution.execution
        context["canonical_execution_plan_id"] = canonical_execution.plan.plan_id
        context["canonical_ledger_event_id"] = canonical_execution.ledger_event.event_id
        context["execution_result"] = _execution_context(exec_result)
        execution_reasons = _execution_refusal_reasons(exec_result, strict=self.config.strict_execution_truth)
        if execution_reasons:
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, execution_reasons, decision_context=context),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=execution_reasons,
                decision_context=context,
            )
        assert exec_result.fill_price is not None
        assert exec_result.net_cost_bps is not None
        quantity = exec_result.filled_quantity
        filled_notional = exec_result.filled_notional_usdc

        existing = self._find_entry_position(delta, side)
        if delta.action in {LifecycleAction.ADD, LifecycleAction.INCREASE} and existing is None:
            execution_reasons = ["NO_MATCHING_PAPER_POSITION_FOR_ADD"]
            return self._result(
                accepted=False,
                risk_decision=risk_decision,
                trade=self._no_trade(delta, execution_reasons, decision_context=context),
                position=None,
                marks=marks or {delta.coin: market_price},
                reasons=execution_reasons,
                decision_context=context,
            )
        if existing is not None:
            position_id = existing.position_id
            total_quantity = existing.quantity + quantity
            average_entry = (
                existing.quantity * existing.entry_price + quantity * exec_result.fill_price
            ) / total_quantity
            position = replace(
                existing,
                quantity=total_quantity,
                entry_price=average_entry,
                notional_usdt=existing.notional_usdt + filled_notional,
                source_delta_id=delta.delta_id,
                margin_locked_usdt=(
                    existing.margin_locked_usdt
                    + filled_notional / max(1.0, float(self.config.leverage))
                ),
                leg_notional_usdt=(
                    existing.notional_usdt + filled_notional,
                ),
            )
            trade_action = "ADD"
        else:
            position_id = _id(
                "paperpos",
                delta.wallet.lower(),
                delta.coin.upper(),
                side,
                observed_at_ms,
            )
            position = PaperPosition(
                position_id=position_id,
                coin=delta.coin,
                side=side,
                quantity=quantity,
                entry_price=exec_result.fill_price,
                notional_usdt=filled_notional,
                opened_at_ms=observed_at_ms,
                source_delta_id=delta.delta_id,
                leader_wallet=delta.wallet,
                margin_locked_usdt=(
                    filled_notional / max(1.0, float(self.config.leverage))
                ),
                leverage_effective=max(1.0, float(self.config.leverage)),
                leg_notional_usdt=(filled_notional,),
            )
            trade_action = "OPEN"
        self._positions[position_id] = position
        self.ledger.open_position(
            coin=delta.coin,
            side=side,
            notional_usdc=filled_notional,
            quantity=quantity,
            fill_price=exec_result.fill_price,
            timestamp_ms=observed_at_ms,
            fee_bps=0.0,
            leverage_effective=max(1.0, float(self.config.leverage)),
            leg_notional_usd=(filled_notional,),
            leg_direction=((1 if side == "LONG" else -1),),
            position_id=position_id,
            refs=_ledger_refs(
                delta,
                exec_result=exec_result,
                paper_position_id=position_id,
                decision_context=context,
            ),
        )
        trade = PaperTrade(
            trade_id=_id("papertrade", position_id, trade_action, observed_at_ms),
            action=trade_action,
            coin=delta.coin,
            side=side,
            quantity=quantity,
            fill_price=exec_result.fill_price,
            notional_usdt=filled_notional,
            realized_pnl_usdt=0.0,
            fees_and_cost_bps=exec_result.net_cost_bps,
            source_delta_id=delta.delta_id,
            requested_notional_usdt=exec_result.requested_notional_usdc,
            filled_notional_usdt=filled_notional,
            missed_notional_usdt=exec_result.missed_notional_usdc,
            fill_ratio=exec_result.fill_ratio,
            cost_status=exec_result.cost_status,
            execution_snapshot_id=exec_result.execution_snapshot_id,
        )
        return self._result(
            accepted=True,
            risk_decision=risk_decision,
            trade=trade,
            position=position,
            marks=marks or {delta.coin: market_price},
            reasons=(),
            decision_context=context,
        )

    def mark_to_market(
        self, marks: dict[str, float], *, liquidatable_marks: dict[str, float] | None = None
    ) -> tuple[float, float, float]:
        clean_marks = _clean_marks_for_ledger(marks)
        unrealized = sum(
            _position_unrealized(
                position,
                clean_marks.get(position.coin, position.entry_price),
            )
            for position in self._positions.values()
        )
        equity = self.cash_usdt + self.realized_pnl_usdt + unrealized
        self._high_water_equity = max(self._high_water_equity, equity)
        drawdown = max(0.0, self._high_water_equity - equity)
        self.ledger.mark_to_market(
            clean_marks, timestamp_ms=int(time.time() * 1000), liquidatable_marks=liquidatable_marks
        )
        return round(equity, 8), round(unrealized, 8), round(drawdown, 8)

    def mark_to_market_depuis_bbo(
        self, marks: dict[str, float], bbo: dict[str, object]
    ) -> tuple[float, float, float]:
        """P1A câblage : construit les marks LIQUIDABLES (LONG@bid, SHORT@ask) depuis le BBO CAUSAL et
        marque le ledger avec — l'equity AUTORITAIRE (`authoritative_equity_usdc`) devient alors mesurable
        au lieu de rester `UNMEASURABLE_NO_EXECUTABLE_EXIT`. `bbo` = {coin: {"bid":.., "ask":..}}.
        Sans bid/ask exécutable pour une position, elle reste UNMEASURABLE — jamais un repli sur le mid."""
        from hl_observer.simulation.liquidatable_marks import marks_depuis_bbo

        liq = marks_depuis_bbo(self.ledger.positions.values(), bbo)
        return self.mark_to_market(marks, liquidatable_marks=liq)

    def _apply_exit_delta(
        self,
        delta: LeaderDelta,
        *,
        market_price: float,
        observed_at_ms: int,
        risk_decision: RiskDecision,
        marks: dict[str, float] | None,
        decision_context: dict[str, object],
        execution_truth: ExecutionTruth | None,
    ) -> PaperDecisionResult:
        position = self._find_position_for_exit(delta, decision_context=decision_context)
        reasons: list[str] = []
        if position is None:
            reasons.append("NO_MATCHING_PAPER_POSITION_FOR_CLOSE")
            return self._result(
                False,
                risk_decision,
                self._no_trade(delta, reasons, decision_context=decision_context),
                None,
                marks or {delta.coin: market_price},
                reasons,
                decision_context=decision_context,
            )

        close_fraction = 1.0 if delta.action in {LifecycleAction.CLOSE_LONG, LifecycleAction.CLOSE_SHORT} else _reduce_fraction(position, delta)
        requested_close_quantity = position.quantity * close_fraction
        exit_side = "SELL" if position.side == "LONG" else "BUY"
        requested_close_notional = book_notional_for_quantity(
            execution_truth,
            side=exit_side,
            quantity=requested_close_quantity,
            fallback_price=market_price,
        )
        canonical_execution = execute_paper_intent(
            _paper_intent_for_delta(
                delta,
                side=position.side,
                action="CLOSE" if close_fraction >= 0.999 else "REDUCE",
                notional_usdt=requested_close_notional,
                observed_at_ms=observed_at_ms,
                decision_context=decision_context,
            ),
            CausalMarketSnapshot(
                coin=delta.coin,
                reference_mid=market_price,
                decision_ts_ms=observed_at_ms,
                execution_truth=execution_truth,
                source=execution_truth.source if execution_truth is not None else "paper_engine_compat",
            ),
            config=self.config.exec_model,
            strict_book=self.config.strict_execution_truth,
            min_fill_ratio=self.config.min_execution_fill_ratio,
            max_book_age_ms=self.config.max_execution_book_age_ms,
            top_depth_usdc=None,
            is_maker=False,
            latency_sec=max(
                0,
                observed_at_ms - (delta.leader_event_time_ms or observed_at_ms),
            )
            / 1000.0,
            liquidity_ledger=self.liquidity_ledger,
        )
        exit_exec = canonical_execution.execution
        decision_context["canonical_execution_plan_id"] = canonical_execution.plan.plan_id
        decision_context["canonical_ledger_event_id"] = canonical_execution.ledger_event.event_id
        decision_context["execution_result"] = _execution_context(exit_exec)
        reasons.extend(
            _execution_refusal_reasons(
                exit_exec,
                strict=self.config.strict_execution_truth,
            )
        )
        if reasons:
            return self._result(
                False,
                risk_decision,
                self._no_trade(delta, reasons, decision_context=decision_context),
                position,
                marks or {delta.coin: market_price},
                reasons,
                decision_context=decision_context,
            )
        assert exit_exec.fill_price is not None
        assert exit_exec.net_cost_bps is not None
        close_quantity = min(requested_close_quantity, exit_exec.filled_quantity)
        if close_quantity <= 0:
            reasons.append("NO_EXECUTABLE_EXIT_FILL")
            return self._result(
                False,
                risk_decision,
                self._no_trade(delta, reasons, decision_context=decision_context),
                position,
                marks or {delta.coin: market_price},
                reasons,
                decision_context=decision_context,
            )
        close_notional = close_quantity * exit_exec.fill_price
        gross = _closed_pnl(position, close_quantity, exit_exec.fill_price)
        # ``simulate_execution`` already returns an all-in effective fill price:
        # entry and exit prices include spread, slippage, taker fee and latency.
        # Subtracting ``net_cost_bps`` again here double-counts exit costs and
        # creates unexplained negative PnL spikes. Keep costs in the trade
        # evidence, but let the all-in fill prices drive accounting.
        realized = gross
        self.realized_pnl_usdt += realized
        remaining_quantity = position.quantity - close_quantity
        if remaining_quantity <= 1e-12:
            del self._positions[position.position_id]
        else:
            self._positions[position.position_id] = replace(
                position,
                quantity=remaining_quantity,
                notional_usdt=remaining_quantity * position.entry_price,
                margin_locked_usdt=(
                    remaining_quantity
                    * position.entry_price
                    / max(1.0, position.leverage_effective)
                ),
                leg_notional_usdt=(
                    remaining_quantity * position.entry_price,
                ),
            )
        self.ledger.reduce_or_close(
            coin=position.coin,
            side=position.side,
            quantity=close_quantity,
            fill_price=exit_exec.fill_price,
            timestamp_ms=observed_at_ms,
            fee_bps=0.0,
            position_id=position.position_id,
            reason="leader_exit" if remaining_quantity <= 1e-12 else "leader_reduce",
            refs=_ledger_refs(
                delta,
                exec_result=exit_exec,
                paper_position_id=position.position_id,
                decision_context=decision_context,
            ),
        )
        trade = PaperTrade(
            trade_id=_id("papertrade", position.position_id, "EXIT", observed_at_ms),
            action="CLOSE" if close_fraction >= 0.999 else "REDUCE",
            coin=position.coin,
            side=position.side,
            quantity=close_quantity,
            fill_price=exit_exec.fill_price,
            notional_usdt=close_notional,
            realized_pnl_usdt=realized,
            fees_and_cost_bps=exit_exec.net_cost_bps,
            source_delta_id=delta.delta_id,
            requested_notional_usdt=exit_exec.requested_notional_usdc,
            filled_notional_usdt=exit_exec.filled_notional_usdc,
            missed_notional_usdt=exit_exec.missed_notional_usdc,
            fill_ratio=exit_exec.fill_ratio,
            cost_status=exit_exec.cost_status,
            execution_snapshot_id=exit_exec.execution_snapshot_id,
        )
        return self._result(
            True,
            risk_decision,
            trade,
            self._positions.get(position.position_id),
            marks or {delta.coin: market_price},
            (),
            decision_context=decision_context,
        )

    def _find_entry_position(self, delta: LeaderDelta, side: str) -> PaperPosition | None:
        matches = [
            position
            for position in self._positions.values()
            if position.coin == delta.coin
            and position.side == side
            and position.leader_wallet.lower() == delta.wallet.lower()
        ]
        return matches[0] if len(matches) == 1 else None

    def _find_position_for_exit(
        self,
        delta: LeaderDelta,
        *,
        decision_context: dict[str, object],
    ) -> PaperPosition | None:
        target_side = _side_for_exit(delta)
        explicit_id = delta.source_position_id or decision_context.get("paper_position_id")
        if explicit_id is not None:
            position = self._positions.get(str(explicit_id))
            if position is None:
                return None
            if position.coin != delta.coin or (
                target_side is not None and position.side != target_side
            ):
                return None
            if position.leader_wallet.lower() != delta.wallet.lower():
                return None
            return position
        matches = [
            position
            for position in self._positions.values()
            if position.coin == delta.coin
            and (target_side is None or position.side == target_side)
            and position.leader_wallet.lower() == delta.wallet.lower()
        ]
        return matches[0] if len(matches) == 1 else None

    def _gross_exposure_usdt(self) -> float:
        return sum(
            sum(position.leg_notional_usdt)
            if position.leg_notional_usdt
            else position.notional_usdt
            for position in self._positions.values()
        )

    def _margin_locked_usdt(self) -> float:
        return sum(
            position.margin_locked_usdt
            if position.margin_locked_usdt > 0
            else (
                position.notional_usdt
                / max(1.0, position.leverage_effective)
            )
            for position in self._positions.values()
        )

    def _margin_cap_usdt(self) -> float:
        explicit = getattr(self.config, "max_total_margin_usdt", None)
        if explicit is not None:
            return max(0.0, float(explicit))
        return max(0.0, float(self.config.max_total_exposure_usdt))

    def _no_trade(
        self,
        delta: LeaderDelta,
        reasons: list[str] | tuple[str, ...],
        *,
        decision_context: dict[str, object] | None = None,
    ) -> PaperTrade:
        deduped_reasons = tuple(dict.fromkeys(reasons))
        refs = {
            "leader_delta_id": delta.delta_id,
            "leader_wallet": delta.wallet,
            "leader_action": getattr(delta.action, "value", str(delta.action)),
            "source": delta.source,
            "evidence_ref": delta.evidence_ref,
            "paper_engine": "NO_REAL_ORDER_LOCAL_ONLY",
        }
        refs.update(decision_context or {})
        self.ledger.no_trade(
            coin=delta.coin,
            reason="|".join(deduped_reasons) if deduped_reasons else "NO_TRADE",
            timestamp_ms=int(delta.observed_at_ms or time.time() * 1000),
            refs=refs,
        )
        return PaperTrade(
            trade_id=_id("notrade", delta.delta_id),
            action="NO_TRADE",
            coin=delta.coin,
            side="NONE",
            quantity=0.0,
            fill_price=None,
            notional_usdt=0.0,
            realized_pnl_usdt=0.0,
            fees_and_cost_bps=0.0,
            source_delta_id=delta.delta_id,
            reason_codes=deduped_reasons,
        )

    def _result(
        self,
        accepted: bool,
        risk_decision: RiskDecision,
        trade: PaperTrade | None,
        position: PaperPosition | None,
        marks: dict[str, float],
        reasons: list[str] | tuple[str, ...],
        *,
        decision_context: dict[str, object] | None = None,
    ) -> PaperDecisionResult:
        equity, unrealized, drawdown = self.mark_to_market(marks)
        payload = (
            accepted,
            getattr(risk_decision.decision, "value", str(risk_decision.decision)),
            tuple(reasons),
            trade.trade_id if trade else None,
            position.position_id if position else None,
            equity,
            self.realized_pnl_usdt,
            unrealized,
        )
        return PaperDecisionResult(
            accepted=accepted,
            risk_decision=risk_decision,
            trade=trade,
            position=position,
            cash_usdt=self.cash_usdt,
            equity_usdt=equity,
            realized_pnl_usdt=round(self.realized_pnl_usdt, 8),
            unrealized_pnl_usdt=unrealized,
            drawdown_usdt=drawdown,
            reason_codes=tuple(dict.fromkeys(reasons)),
            evidence_hash=_id("pevidence", *payload),
            ledger_snapshot=self.ledger.snapshot(),
            decision_context=dict(decision_context or {}),
        )


def _side_for_entry(delta: LeaderDelta) -> str | None:
    if delta.action == LifecycleAction.OPEN_LONG:
        return "LONG"
    if delta.action == LifecycleAction.OPEN_SHORT:
        return "SHORT"
    if delta.action in {LifecycleAction.ADD, LifecycleAction.INCREASE}:
        if delta.current_size > 0:
            return "LONG"
        if delta.current_size < 0:
            return "SHORT"
    return None


def _side_for_exit(delta: LeaderDelta) -> str | None:
    if delta.action == LifecycleAction.CLOSE_LONG:
        return "LONG"
    if delta.action == LifecycleAction.CLOSE_SHORT:
        return "SHORT"
    if delta.action == LifecycleAction.REDUCE:
        if delta.previous_size > 0 or delta.current_size > 0:
            return "LONG"
        if delta.previous_size < 0 or delta.current_size < 0:
            return "SHORT"
    return None


def _paper_intent_for_delta(
    delta: LeaderDelta,
    *,
    side: str,
    action: str,
    notional_usdt: float,
    observed_at_ms: int,
    decision_context: dict[str, object],
) -> PaperExecutionIntent:
    """Create the canonical strategy intent after risk admission.

    ``PaperEngine`` remains responsible for risk and position accounting.  The
    resulting intent is consumed only by the local canonical fill core.
    """

    return PaperExecutionIntent(
        strategy_id=str(
            decision_context.get("strategy_id")
            or decision_context.get("strategy_family")
            or "leader_delta_copy_follow"
        ),
        coin=str(delta.coin).upper(),
        position_side=str(side).upper(),
        action=str(action).upper(),
        target_notional_usdc=float(notional_usdt),
        confidence=float(delta.confidence),
        reasons=tuple(delta.reason_codes),
        created_at_ms=int(observed_at_ms),
    )


def _position_unrealized(position: PaperPosition, mark: float) -> float:
    if position.side == "LONG":
        return (mark - position.entry_price) * position.quantity
    return (position.entry_price - mark) * position.quantity


def _closed_pnl(position: PaperPosition, quantity: float, exit_price: float) -> float:
    if position.side == "LONG":
        return (exit_price - position.entry_price) * quantity
    return (position.entry_price - exit_price) * quantity


def _ledger_refs(
    delta: LeaderDelta,
    *,
    exec_result: ExecResult,
    paper_position_id: str,
    decision_context: dict[str, object] | None = None,
) -> dict[str, object]:
    context = dict(decision_context or {})
    candidate_id = str(context.get("candidate_id") or delta.delta_id)
    strategy_id = str(context.get("strategy_id") or "leader_delta_copy_follow")
    strategy_family = str(context.get("strategy_family") or "COPY_FOLLOW")
    source_signal_id = str(context.get("source_signal_id") or delta.delta_id)
    execution_id = str(
        context.get("execution_id")
        or _id(
            "paperexec",
            candidate_id,
            paper_position_id,
            exec_result.execution_snapshot_id or "no-snapshot",
        )
    )
    return {
        "candidate_id": candidate_id,
        "strategy_id": strategy_id,
        "strategy_family": strategy_family,
        "position_instance_id": paper_position_id,
        "source_signal_id": source_signal_id,
        "execution_id": execution_id,
        "ledger_scope": str(context.get("ledger_scope") or "STRICT").upper(),
        "leader_delta_id": delta.delta_id,
        "leader_wallet": delta.wallet,
        "leader_action": getattr(delta.action, "value", str(delta.action)),
        "leader_event_time_ms": delta.leader_event_time_ms,
        "source": delta.source,
        "evidence_ref": delta.evidence_ref,
        "paper_position_id": paper_position_id,
        "embedded_cost_model": "fill_price_includes_spread_slippage_fee_latency",
        "embedded_net_cost_bps": _optional_round(exec_result.net_cost_bps),
        "embedded_slippage_bps": _optional_round(exec_result.slippage_bps),
        "embedded_fee_bps": _optional_round(exec_result.fee_bps),
        "embedded_latency_bps": round(float(exec_result.latency_bps), 8),
        "requested_notional_usdc": exec_result.requested_notional_usdc,
        "filled_notional_usdc": exec_result.filled_notional_usdc,
        "missed_notional_usdc": exec_result.missed_notional_usdc,
        "fill_ratio": exec_result.fill_ratio,
        "execution_reason": exec_result.reason,
        "execution_cost_status": exec_result.cost_status,
        "execution_snapshot_id": exec_result.execution_snapshot_id,
        "paper_engine": "NO_REAL_ORDER_LOCAL_ONLY",
    }


def _clean_marks_for_ledger(marks: dict[str, float]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for coin, raw_price in marks.items():
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            clean[str(coin).upper()] = price
    return clean


def _finite_or_false(value: object) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed)


def _finite_positive_or_false(value: object) -> bool:
    if not _finite_or_false(value):
        return False
    return float(value) > 0


def _finite_or_default(value: object, default: float = 0.0) -> float:
    return float(value) if _finite_or_false(value) else float(default)


def _risk_depth(execution_truth: ExecutionTruth | None) -> float | None:
    if execution_truth is None:
        return None
    return min(
        execution_truth.visible_notional("BUY"),
        execution_truth.visible_notional("SELL"),
    )


def _execution_context(result: ExecResult) -> dict[str, object]:
    return {
        "requested_notional_usdc": result.requested_notional_usdc,
        "filled_notional_usdc": result.filled_notional_usdc,
        "missed_notional_usdc": result.missed_notional_usdc,
        "filled_quantity": result.filled_quantity,
        "fill_ratio": result.fill_ratio,
        "partial": result.partial,
        "missed": result.missed,
        "reason": result.reason,
        "cost_status": result.cost_status,
        "net_cost_bps": result.net_cost_bps,
        "execution_snapshot_id": result.execution_snapshot_id,
    }


def _execution_refusal_reasons(result: ExecResult, *, strict: bool) -> list[str]:
    reasons: list[str] = []
    if result.fill_price is None or result.filled_notional_usdc <= 0:
        reasons.append(result.reason or "NO_EXECUTABLE_FILL")
    if strict and result.cost_status != "MEASURED":
        reasons.append("EXECUTION_COST_UNMEASURABLE")
    if strict and result.execution_snapshot_id is None:
        reasons.append("EXECUTION_SNAPSHOT_MISSING")
    if result.net_cost_bps is None:
        reasons.append("EXECUTION_COST_UNMEASURABLE")
    if not _finite_positive_or_false(result.filled_quantity):
        reasons.append("EXECUTION_QUANTITY_INVALID")
    return list(dict.fromkeys(reasons))


def _optional_round(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), 8)


def _reduce_fraction(position: PaperPosition, delta: LeaderDelta) -> float:
    previous_abs = abs(delta.previous_size)
    current_abs = abs(delta.current_size)
    if previous_abs <= 0 or current_abs >= previous_abs:
        return 1.0
    return max(0.0, min(1.0, (previous_abs - current_abs) / previous_abs))


def _id(prefix: str, *parts: object) -> str:
    material = "|".join(str(part) for part in parts)
    return prefix + ":" + sha256(material.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "PaperDecisionResult",
    "PaperEngine",
    "PaperEngineConfig",
    "PaperPosition",
    "PaperTrade",
]

def _maker_execution_style_enabled() -> bool:
    """Mode grinder: fills passifs maker (recherche X/web 2026-07-07).

    Les bots multi-mini-positions ne survivent aux frais que parce qu'ils
    paient maker (~1.5 bps, rebates possibles) au lieu de taker (4.5 bps +
    spread + slippage). Défaut OFF: activation via replay A/B uniquement.
    """

    import os

    return str(os.environ.get("HYPERSMART_EXECUTION_STYLE", "taker")).strip().lower() == "maker"
