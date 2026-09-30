from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc
from uuid import uuid4

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import (
    PaperIntent,
    PaperIntentStatus,
    PaperTrade,
    PaperTradeStatus,
    RiskEvent,
    ScoreBreakdown,
    Signal,
    WalletScoreStatus,
)
from hyper_smart_observer.paper_trading.fees import calculate_fee
from hyper_smart_observer.paper_trading.latency import simulate_latency_timestamp
from hyper_smart_observer.paper_trading.paper_intent import build_paper_intent
from hyper_smart_observer.paper_trading.slippage import apply_slippage, estimate_slippage
from hyper_smart_observer.paper_trading.spread import apply_spread
from hyper_smart_observer.risk_engine.gates import evaluate_paper_intent
from hyper_smart_observer.risk_engine.risk_state import RiskDecision
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import paper_trades_repo, risk_events_repo, scores_repo


@dataclass(frozen=True)
class PaperSimulationResult:
    success: bool
    intent: PaperIntent
    decision: RiskDecision
    trade: PaperTrade | None = None
    message: str = ""


@dataclass(frozen=True)
class PaperCloseResult:
    success: bool
    trade_id: str
    message: str
    net_pnl: float | None = None
    closed_size: float | None = None
    remaining_size: float | None = None
    realized_trade_id: str | None = None


def simulate_entry(signal: Signal, *, price: float, size: float, fee_bps: float = 4.0) -> PaperTrade:
    """Create a local-only legacy paper trade. No network calls, no external orders."""

    slippage = estimate_slippage(price)
    fee = price * size * fee_bps / 10_000.0
    entry_price = price + slippage if signal.side.lower() == "buy" else price - slippage
    return PaperTrade(
        trade_id=str(uuid4()),
        signal_id=signal.signal_id,
        coin=signal.coin,
        side=signal.side,
        entry_price=entry_price,
        size=size,
        simulated_fee=fee,
        simulated_slippage=slippage,
        opened_at=datetime.now(UTC),
        fee_entry=fee,
        slippage_entry=slippage,
        status=PaperTradeStatus.OPEN,
    )


class PaperTradingSimulator:
    """Local paper simulation engine.

    This class never sends an order, never signs payloads and never performs a
    network request. It only writes local paper intents/trades and risk events.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def create_intent_from_wallet_score(
        self,
        wallet_address: str,
        coin: str,
        side: str,
        reference_price: float,
        requested_notional: float,
    ) -> PaperIntent:
        return build_paper_intent(
            wallet_address=wallet_address,
            coin=coin,
            side=side,
            reference_price=reference_price,
            requested_notional=requested_notional,
            source="paper_simulator",
            reason="hypothetical local paper intent",
        )

    def evaluate_intent(self, intent: PaperIntent) -> RiskDecision:
        wallet_score = self._load_latest_score(intent.wallet_address)
        return evaluate_paper_intent(intent, wallet_score, self.config, self._portfolio_state())

    def open_paper_trade(self, intent: PaperIntent) -> PaperSimulationResult:
        initialize_database(self.config)
        decision = self.evaluate_intent(intent)
        if not decision.allowed or intent.status == PaperIntentStatus.INVALID_DATA:
            reason = intent.refusal_reason or decision.reason_code
            rejected = _intent_with_status(intent, PaperIntentStatus.REJECTED_BY_RISK, reason)
            self._store_intent_and_refusal(rejected, decision)
            return PaperSimulationResult(False, rejected, decision, message=decision.message)

        accepted = _intent_with_status(intent, PaperIntentStatus.ACCEPTED_FOR_SIMULATION, None)
        entry_side = accepted.side.upper()
        spread_price = apply_spread(accepted.reference_price, entry_side, self.config.paper_spread_bps)
        entry_price = apply_slippage(spread_price, entry_side, self.config.paper_slippage_bps)
        notional = accepted.requested_notional
        size = notional / entry_price
        fee_entry = calculate_fee(notional, self.config.paper_fee_rate_bps)
        opened_at = simulate_latency_timestamp(accepted.created_at, self.config.paper_latency_ms)
        slippage_entry = abs(entry_price - spread_price) * size
        spread_cost = abs(spread_price - accepted.reference_price) * size
        trade = PaperTrade(
            trade_id=str(uuid4()),
            signal_id=accepted.intent_id,
            intent_id=accepted.intent_id,
            wallet_address=accepted.wallet_address,
            coin=accepted.coin,
            side=entry_side,
            entry_price=entry_price,
            size=size,
            notional=notional,
            simulated_fee=fee_entry,
            simulated_slippage=slippage_entry,
            fee_entry=fee_entry,
            slippage_entry=slippage_entry,
            spread_cost=spread_cost,
            opened_at=opened_at,
            status=PaperTradeStatus.OPEN,
            state=PaperTradeStatus.OPEN.value,
            warnings=[
                "LOCAL PAPER SIMULATION ONLY",
                "Not a trading signal. Not an order.",
            ],
        )
        with get_connection(self.config) as conn:
            paper_trades_repo.insert_paper_intent(conn, accepted)
            paper_trades_repo.insert_paper_trade(conn, trade)
            conn.commit()
        return PaperSimulationResult(True, accepted, decision, trade, decision.message)

    def close_paper_trade(
        self, trade_id: str, exit_reference_price: float, close_reason: str
    ) -> PaperCloseResult:
        if exit_reference_price <= 0:
            return PaperCloseResult(False, trade_id, "Exit reference price must be positive.")
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            row = paper_trades_repo.get_paper_trade(conn, trade_id)
            if row is None:
                return PaperCloseResult(False, trade_id, "Paper trade not found.")
            if (row["status"] or row["state"]) != PaperTradeStatus.OPEN.value:
                return PaperCloseResult(False, trade_id, "Paper trade is not open.")
            close_side = "SELL" if row["side"].upper() == "BUY" else "BUY"
            spread_price = apply_spread(exit_reference_price, close_side, self.config.paper_spread_bps)
            exit_price = apply_slippage(spread_price, close_side, self.config.paper_slippage_bps)
            size = float(row["size"])
            notional_exit = exit_price * size
            fee_exit = calculate_fee(notional_exit, self.config.paper_fee_rate_bps)
            slippage_exit = abs(exit_price - spread_price) * size
            spread_cost = float(row["spread_cost"] or 0.0) + abs(spread_price - exit_reference_price) * size
            if row["side"].upper() == "BUY":
                gross_pnl = (exit_price - float(row["entry_price"])) * size
            else:
                gross_pnl = (float(row["entry_price"]) - exit_price) * size
            fee_entry = float(row["fee_entry"] or row["simulated_fee"] or 0.0)
            net_pnl = gross_pnl - fee_entry - fee_exit
            closed_at = simulate_latency_timestamp(datetime.now(UTC), self.config.paper_latency_ms)
            paper_trades_repo.update_paper_trade_close(
                conn,
                trade_id=trade_id,
                exit_price=exit_price,
                fee_exit=fee_exit,
                slippage_exit=slippage_exit,
                spread_cost=spread_cost,
                closed_at=closed_at.isoformat(),
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                close_reason=close_reason,
            )
            conn.commit()
        return PaperCloseResult(
            True,
            trade_id,
            "Local paper simulation closed.",
            net_pnl,
            closed_size=size,
            remaining_size=0.0,
            realized_trade_id=trade_id,
        )

    def partial_close_paper_trade(
        self,
        trade_id: str,
        exit_reference_price: float,
        close_reason: str,
        *,
        fraction: float,
    ) -> PaperCloseResult:
        if exit_reference_price <= 0:
            return PaperCloseResult(False, trade_id, "Exit reference price must be positive.")
        if fraction <= 0:
            return PaperCloseResult(False, trade_id, "Partial close fraction must be positive.")
        if fraction >= 0.999:
            return self.close_paper_trade(trade_id, exit_reference_price, close_reason)

        initialize_database(self.config)
        with get_connection(self.config) as conn:
            row = paper_trades_repo.get_paper_trade(conn, trade_id)
            if row is None:
                return PaperCloseResult(False, trade_id, "Paper trade not found.")
            if (row["status"] or row["state"]) != PaperTradeStatus.OPEN.value:
                return PaperCloseResult(False, trade_id, "Paper trade is not open.")

            close_ratio = min(0.998, max(0.001, float(fraction)))
            original_size = float(row["size"])
            if original_size <= 0:
                return PaperCloseResult(False, trade_id, "Paper trade size is not positive.")
            closed_size = original_size * close_ratio
            remaining_size = original_size - closed_size
            if remaining_size <= max(original_size * 0.001, 1e-12):
                return self.close_paper_trade(trade_id, exit_reference_price, close_reason)

            close_side = "SELL" if row["side"].upper() == "BUY" else "BUY"
            spread_price = apply_spread(exit_reference_price, close_side, self.config.paper_spread_bps)
            exit_price = apply_slippage(spread_price, close_side, self.config.paper_slippage_bps)
            notional_exit = exit_price * closed_size
            fee_exit = calculate_fee(notional_exit, self.config.paper_fee_rate_bps)
            slippage_exit = abs(exit_price - spread_price) * closed_size
            exit_spread_cost = abs(spread_price - exit_reference_price) * closed_size

            entry_price = float(row["entry_price"])
            if row["side"].upper() == "BUY":
                gross_pnl = (exit_price - entry_price) * closed_size
            else:
                gross_pnl = (entry_price - exit_price) * closed_size

            fee_entry_total = float(row["fee_entry"] or row["simulated_fee"] or 0.0)
            slippage_entry_total = float(row["slippage_entry"] or row["simulated_slippage"] or 0.0)
            spread_cost_total = float(row["spread_cost"] or 0.0)
            simulated_fee_total = float(row["simulated_fee"] or fee_entry_total)
            simulated_slippage_total = float(row["simulated_slippage"] or slippage_entry_total)
            original_notional = float(row["notional"] or (entry_price * original_size))

            allocated_fee_entry = fee_entry_total * close_ratio
            allocated_slippage_entry = slippage_entry_total * close_ratio
            allocated_spread_entry = spread_cost_total * close_ratio
            allocated_simulated_fee = simulated_fee_total * close_ratio
            allocated_simulated_slippage = simulated_slippage_total * close_ratio
            allocated_notional = original_notional * close_ratio

            remaining_fee_entry = max(0.0, fee_entry_total - allocated_fee_entry)
            remaining_slippage_entry = max(0.0, slippage_entry_total - allocated_slippage_entry)
            remaining_spread_cost = max(0.0, spread_cost_total - allocated_spread_entry)
            remaining_simulated_fee = max(0.0, simulated_fee_total - allocated_simulated_fee)
            remaining_simulated_slippage = max(0.0, simulated_slippage_total - allocated_simulated_slippage)
            remaining_notional = max(0.0, original_notional - allocated_notional)

            net_pnl = gross_pnl - allocated_fee_entry - fee_exit
            closed_at = simulate_latency_timestamp(datetime.now(UTC), self.config.paper_latency_ms)
            partial_trade_id = f"{trade_id}:partial:{uuid4().hex[:8]}"
            partial_trade = PaperTrade(
                trade_id=partial_trade_id,
                signal_id=row["signal_id"],
                intent_id=row["intent_id"],
                wallet_address=row["wallet_address"],
                coin=row["coin"],
                side=row["side"],
                entry_price=entry_price,
                exit_price=exit_price,
                size=closed_size,
                notional=allocated_notional,
                simulated_fee=allocated_simulated_fee,
                simulated_slippage=allocated_simulated_slippage,
                fee_entry=allocated_fee_entry,
                fee_exit=fee_exit,
                slippage_entry=allocated_slippage_entry,
                slippage_exit=slippage_exit,
                spread_cost=allocated_spread_entry + exit_spread_cost,
                opened_at=datetime.fromisoformat(row["opened_at"]),
                closed_at=closed_at,
                pnl=net_pnl,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                state=PaperTradeStatus.CLOSED.value,
                status=PaperTradeStatus.CLOSED,
                close_reason=close_reason,
                warnings=[
                    "LOCAL PAPER SIMULATION ONLY",
                    "Partial close mirrors a leader reduce; not an order.",
                ],
            )
            paper_trades_repo.insert_paper_trade(conn, partial_trade)
            paper_trades_repo.update_paper_trade_after_partial(
                conn,
                trade_id=trade_id,
                remaining_size=remaining_size,
                remaining_notional=remaining_notional,
                remaining_simulated_fee=remaining_simulated_fee,
                remaining_simulated_slippage=remaining_simulated_slippage,
                remaining_fee_entry=remaining_fee_entry,
                remaining_slippage_entry=remaining_slippage_entry,
                remaining_spread_cost=remaining_spread_cost,
            )
            conn.commit()
        return PaperCloseResult(
            True,
            trade_id,
            "Local paper simulation partially reduced.",
            net_pnl,
            closed_size=closed_size,
            remaining_size=remaining_size,
            realized_trade_id=partial_trade_id,
        )

    def list_open_trades(self) -> list:
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            return paper_trades_repo.list_open_paper_trades(conn)

    def generate_report(self, current_mids: dict[str, float] | None = None) -> dict[str, float | int]:
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            open_trades = paper_trades_repo.list_open_paper_trades(conn)
            closed_trades = paper_trades_repo.list_closed_paper_trades(conn, limit=10_000)
        realized_pnl = sum(float(row["net_pnl"] or row["pnl"] or 0.0) for row in closed_trades)
        total_fees = sum(
            float(row["fee_entry"] or row["simulated_fee"] or 0.0) + float(row["fee_exit"] or 0.0)
            for row in [*open_trades, *closed_trades]
        )
        start = float(self.config.paper_starting_equity)
        max_drawdown = _realized_max_drawdown(closed_trades, start)
        unrealized_pnl = _unrealized_pnl(open_trades, current_mids)
        return {
            "starting_equity": start,
            "current_equity": start + realized_pnl,
            "open_trades": len(open_trades),
            "closed_trades": len(closed_trades),
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "equity": start + realized_pnl + unrealized_pnl,
            "max_drawdown": max_drawdown,
            "total_fees": total_fees,
        }

    def _load_latest_score(self, wallet_address: str) -> ScoreBreakdown | None:
        with get_connection(self.config) as conn:
            row = scores_repo.get_latest_score(conn, wallet_address)
        if row is None:
            return None
        try:
            status = WalletScoreStatus(row["status"])
        except (TypeError, ValueError):
            status = WalletScoreStatus.INSUFFICIENT_DATA
        return ScoreBreakdown(
            wallet_address=row["wallet_address"],
            calculated_at=datetime.fromisoformat(row["calculated_at"]),
            status=status,
            total_fills=int(row["total_trades"]),
            usable_fills=int(row["usable_fills"] or row["total_trades"] or 0),
            skipped_fills=int(row["skipped_fills"] or 0),
            sample_quality_score=float(row["sample_quality_score"] or 0.0),
            confidence_score=float(row["confidence_score"] or 0.0),
            risk_score=float(row["risk_score"] or 0.0),
            profit_factor=row["profit_factor"],
            net_pnl=row["net_pnl"] if "net_pnl" in row.keys() else row["pnl_net"],
            final_score=row["final_score"],
            refusal_reason=row["refusal_reason"],
        )

    def _portfolio_state(self) -> dict[str, int]:
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            return {"open_trades": len(paper_trades_repo.list_open_paper_trades(conn))}

    def _store_intent_and_refusal(self, intent: PaperIntent, decision: RiskDecision) -> None:
        if not self.config.paper_store_refusals:
            return
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            paper_trades_repo.insert_paper_intent(conn, intent)
            risk_events_repo.insert_risk_event(
                conn,
                RiskEvent(
                    severity="INFO",
                    component="paper_trading",
                    reason_code=decision.reason_code,
                    message=decision.message,
                    blocked_action="open_local_paper_simulation",
                    context={
                        "wallet_address": intent.wallet_address,
                        "coin": intent.coin,
                        "side": intent.side,
                        "notional": intent.requested_notional,
                    },
                ),
            )
            conn.commit()


def _intent_with_status(
    intent: PaperIntent, status: PaperIntentStatus, refusal_reason: str | None
) -> PaperIntent:
    return PaperIntent(
        intent_id=intent.intent_id,
        wallet_address=intent.wallet_address,
        coin=intent.coin,
        side=intent.side,
        reference_price=intent.reference_price,
        requested_notional=intent.requested_notional,
        created_at=intent.created_at,
        source=intent.source,
        reason=intent.reason,
        score_snapshot_id=intent.score_snapshot_id,
        status=status,
        refusal_reason=refusal_reason,
        warnings=intent.warnings,
    )


def _realized_max_drawdown(closed_rows, starting_equity: float) -> float:
    """Max peak-to-trough drawdown of the REALIZED equity curve (closed trades)."""
    equity = float(starting_equity)
    peak = equity
    max_dd = 0.0
    for row in sorted(closed_rows, key=lambda r: (r["closed_at"] or "")):
        equity += float(row["net_pnl"] or row["pnl"] or 0.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _unrealized_pnl(open_rows, current_mids: dict | None) -> float:
    """Mark-to-market latent PnL of OPEN paper trades. 0.0 when no mids provided
    (no fabrication: latent is only computed against real read-only mids)."""
    if not current_mids:
        return 0.0
    mids = {str(k).upper(): float(v) for k, v in current_mids.items()}
    total = 0.0
    for row in open_rows:
        try:
            coin = str(row["coin"]).upper()
        except (IndexError, KeyError):
            continue
        mid = mids.get(coin)
        if mid is None:
            continue
        size = float(row["size"])
        entry = float(row["entry_price"])
        sign = 1.0 if str(row["side"]).upper() == "BUY" else -1.0
        total += (mid - entry) * size * sign
    return total
