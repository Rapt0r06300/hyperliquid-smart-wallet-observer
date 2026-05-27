from datetime import UTC, datetime

from hyper_smart_observer.hyperliquid_client.models import (
    Fill,
    RiskEvent,
    Signal,
    SignalState,
    Wallet,
    WalletScore,
    WalletStatus,
)


def test_hypersmart_create_wallet():
    wallet = Wallet(address="0x" + "1" * 40, source="manual")

    assert wallet.status == WalletStatus.DISCOVERED


def test_hypersmart_create_fill():
    fill = Fill(
        wallet_address="0x" + "1" * 40,
        coin="ETH",
        side="buy",
        price=100.0,
        size=1.0,
        fee=0.1,
        timestamp=datetime.now(UTC),
    )

    assert fill.coin == "ETH"


def test_hypersmart_create_wallet_score():
    score = WalletScore(wallet_address="0x" + "1" * 40, calculated_at=datetime.now(UTC), total_trades=0)

    assert score.final_score is None


def test_hypersmart_create_signal():
    signal = Signal(
        signal_id="sig-1",
        wallet_address="0x" + "1" * 40,
        coin="BTC",
        side="buy",
        confidence=0.2,
        created_at=datetime.now(UTC),
        state=SignalState.OBSERVED,
        reason="observed only",
    )

    assert signal.state == SignalState.OBSERVED


def test_hypersmart_create_risk_event():
    event = RiskEvent(
        severity="CRITICAL",
        component="safety",
        reason_code="MAINNET_FORBIDDEN",
        message="blocked",
        blocked_action="execute",
    )

    assert event.event_id
