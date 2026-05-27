from datetime import UTC, datetime

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, Wallet, WalletScoreStatus
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import paper_trades_repo, risk_events_repo, scores_repo
from hyper_smart_observer.storage.repositories.wallet_repo import insert_wallet


def _wallet(char: str = "a") -> str:
    return "0x" + char * 40


def _config(tmp_path, **overrides):
    values = {"database_path": tmp_path / "paper.sqlite3"}
    values.update(overrides)
    return AppConfig(**values)


def _store_score(config: AppConfig, wallet: str, *, status=WalletScoreStatus.SCORED, confidence=90.0, sample=90.0):
    initialize_database(config)
    with get_connection(config) as conn:
        insert_wallet(conn, Wallet(address=wallet, source="test"))
        scores_repo.insert_score_breakdown(
            conn,
            ScoreBreakdown(
                wallet_address=wallet,
                calculated_at=datetime.now(UTC),
                status=status,
                total_fills=50,
                usable_fills=50,
                skipped_fills=0,
                sample_quality_score=sample,
                confidence_score=confidence,
                risk_score=90.0,
                profit_factor=2.0,
                net_pnl=10.0,
                final_score=80.0,
            ),
        )
        conn.commit()


def _intent(config: AppConfig, wallet: str, **overrides):
    simulator = PaperTradingSimulator(config)
    values = {
        "wallet_address": wallet,
        "coin": "ETH",
        "side": "BUY",
        "reference_price": 100.0,
        "requested_notional": 50.0,
    }
    values.update(overrides)
    return simulator.create_intent_from_wallet_score(**values)


def test_hypersmart_paper_refuses_without_wallet_score(tmp_path):
    config = _config(tmp_path)
    simulator = PaperTradingSimulator(config)
    result = simulator.open_paper_trade(_intent(config, _wallet("a")))

    assert not result.success
    assert result.decision.reason_code == "PAPER_WALLET_SCORE_MISSING"


def test_hypersmart_paper_refuses_wallet_score_not_scored(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("b")
    _store_score(config, wallet, status=WalletScoreStatus.INSUFFICIENT_DATA)

    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, wallet))

    assert not result.success
    assert result.decision.reason_code == "PAPER_WALLET_SCORE_NOT_SCORED"


def test_hypersmart_paper_refuses_low_confidence(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("c")
    _store_score(config, wallet, confidence=10.0)

    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, wallet))

    assert not result.success
    assert result.decision.reason_code == "PAPER_CONFIDENCE_TOO_LOW"


def test_hypersmart_paper_refuses_low_sample_quality(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("d")
    _store_score(config, wallet, sample=10.0)

    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, wallet))

    assert not result.success
    assert result.decision.reason_code == "PAPER_SAMPLE_QUALITY_TOO_LOW"


def test_hypersmart_paper_refuses_notional_too_high(tmp_path):
    config = _config(tmp_path, paper_max_position_notional=10.0)
    wallet = _wallet("e")
    _store_score(config, wallet)

    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, wallet, requested_notional=50.0))

    assert not result.success
    assert result.decision.reason_code == "PAPER_NOTIONAL_TOO_HIGH"


def test_hypersmart_paper_refuses_invalid_side(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("f")
    _store_score(config, wallet)

    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, wallet, side="LONG"))

    assert not result.success
    assert result.decision.reason_code == "PAPER_INVALID_SIDE"


def test_hypersmart_paper_refuses_invalid_price(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("1")
    _store_score(config, wallet)

    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, wallet, reference_price=0.0))

    assert not result.success
    assert result.decision.reason_code == "PAPER_INVALID_PRICE"


def test_hypersmart_paper_opens_valid_trade(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("2")
    _store_score(config, wallet)

    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, wallet))

    assert result.success
    assert result.trade is not None
    assert result.trade.entry_price > 100.0
    assert result.trade.fee_entry is not None


def test_hypersmart_paper_closes_valid_trade_with_costs(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("3")
    _store_score(config, wallet)
    simulator = PaperTradingSimulator(config)
    opened = simulator.open_paper_trade(_intent(config, wallet))

    closed = simulator.close_paper_trade(opened.trade.trade_id, 105.0, "test close")

    assert closed.success
    assert closed.net_pnl is not None
    assert closed.net_pnl < 2.5


def test_hypersmart_paper_respects_max_open_trades(tmp_path):
    config = _config(tmp_path, paper_max_open_trades=1)
    wallet = _wallet("4")
    _store_score(config, wallet)
    simulator = PaperTradingSimulator(config)

    first = simulator.open_paper_trade(_intent(config, wallet))
    second = simulator.open_paper_trade(_intent(config, wallet))

    assert first.success
    assert not second.success
    assert second.decision.reason_code == "PAPER_MAX_OPEN_TRADES_REACHED"


def test_hypersmart_paper_risk_event_stored_on_refusal(tmp_path):
    config = _config(tmp_path)
    result = PaperTradingSimulator(config).open_paper_trade(_intent(config, _wallet("5")))

    with get_connection(config) as conn:
        events = risk_events_repo.list_risk_events(conn)

    assert not result.success
    assert events


def test_hypersmart_paper_report_generated(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("6")
    _store_score(config, wallet)
    simulator = PaperTradingSimulator(config)
    simulator.open_paper_trade(_intent(config, wallet))

    report = simulator.generate_report()

    assert report["open_trades"] == 1
    assert report["starting_equity"] == 10_000.0


def test_hypersmart_paper_intent_and_trade_stored(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet("7")
    _store_score(config, wallet)
    simulator = PaperTradingSimulator(config)
    opened = simulator.open_paper_trade(_intent(config, wallet))

    with get_connection(config) as conn:
        intents = paper_trades_repo.list_paper_intents(conn)
        trade = paper_trades_repo.get_paper_trade(conn, opened.trade.trade_id)

    assert intents
    assert trade is not None
