from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
        return PaperCloseResult(True, trade_id, "Local paper simulation closed.", net_pnl)

    def list_open_trades(self) -> list:
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            return paper_trades_repo.list_open_paper_trades(conn)

    def generate_report(self) -> dict[str, float | int]:
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            open_trades = paper_trades_repo.list_open_paper_trades(conn)
            closed_trades = paper_trades_repo.list_closed_paper_trades(conn, limit=10_000)
        realized_pnl = sum(float(row["net_pnl"] or row["pnl"] or 0.0) for row in closed_trades)
        total_fees = sum(
            float(row["fee_entry"] or row["simulated_fee"] or 0.0) + float(row["fee_exit"] or 0.0)
            for row in [*open_trades, *closed_trades]
        )
        return {
            "starting_equity": self.config.paper_starting_equity,
            "current_equity": self.config.paper_starting_equity + realized_pnl,
            "open_trades": len(open_trades),
            "closed_trades": len(closed_trades),
            "realized_pnl": realized_pnl,
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
