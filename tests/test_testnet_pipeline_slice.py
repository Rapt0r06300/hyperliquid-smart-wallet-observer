from __future__ import annotations

import asyncio

from hl_observer.config.settings import Settings
from hl_observer.decision_engine.local_engine import DecisionAction, LocalDecisionEngine
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.mainnet_readonly_observer.observer import MainnetReadOnlyObserver
from hl_observer.testnet.models import TestnetAction as Action
from hl_observer.testnet.models import TestnetSide as Side


class FakeReadOnlyInfoClient:
    async def all_mids(self) -> dict[str, str]:
        return {"BTC": "60000", "HYPE": "40"}

    async def l2_book(self, coin: str) -> dict[str, object]:
        return {"coin": coin, "levels": []}

    async def clearinghouse_state(self, wallet: str) -> dict[str, object]:
        return {"user": wallet, "assetPositions": []}

    async def user_fills(self, wallet: str) -> list[dict[str, object]]:
        return [{"user": wallet, "coin": "BTC", "px": "60000", "sz": "0.01"}]


def test_mainnet_readonly_observer_returns_partial_public_state_without_execution() -> None:
    observer = MainnetReadOnlyObserver(client=FakeReadOnlyInfoClient())

    observation = asyncio.run(
        observer.observe(
            coins=["BTC"],
            wallets=["0x1111111111111111111111111111111111111111"],
            include_l2=True,
            include_wallet_fills=True,
        )
    )

    assert observation.source == "hyperliquid_mainnet_readonly"
    assert observation.all_mids["BTC"] == 60000.0
    assert "BTC" in observation.l2_books
    assert observation.wallet_states
    assert observation.wallet_fills
    assert observation.errors == []


def test_decision_engine_prepares_testnet_request_after_risk_gates() -> None:
    settings = Settings()
    candidate = SignalCandidate(
        id="sig-testnet-1",
        source_wallet="0x2222222222222222222222222222222222222222",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=60000.0,
        timestamp_ms=1,
        signal_age_ms=100,
        wallet_score=95.0,
        signal_score=90.0,
        edge_remaining_bps=80.0,
        estimated_fee_bps=4.0,
        estimated_spread_bps=1.0,
        estimated_slippage_bps=1.0,
        orderbook_depth_usdc=1_000_000.0,
    )

    decision = LocalDecisionEngine(settings).decide_from_candidate(
        candidate,
        notional_usdc=2.0,
        cloid="decision-testnet-btc-open",
    )

    assert decision.action is DecisionAction.ENTER
    assert decision.order_request is not None
    assert decision.order_request.action is Action.OPEN
    assert decision.order_request.side is Side.LONG
    assert decision.order_request.coin == "BTC"
    assert decision.order_request.source_signal_id == "sig-testnet-1"
    assert decision.evidence["decision_layer"] == "local_decision_engine"
