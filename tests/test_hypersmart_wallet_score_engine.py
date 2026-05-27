from datetime import UTC, datetime, timedelta

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import Fill, Wallet, WalletScoreStatus, WalletStatus
from hyper_smart_observer.risk_engine.gates import evaluate_wallet_score_for_research
from hyper_smart_observer.scoring.wallet_score import WalletScoreEngine
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories.fills_repo import insert_fill
from hyper_smart_observer.storage.repositories.scores_repo import get_latest_score
from hyper_smart_observer.storage.repositories.wallet_repo import insert_wallet


def _config(tmp_path, **overrides):
    values = {
        "database_path": tmp_path / "score.sqlite3",
        "min_fills_to_score": 30,
        "min_history_days_to_score": 7,
        "min_closed_pnl_points": 10,
    }
    values.update(overrides)
    return AppConfig(**values)


def _wallet_address(char: str = "a") -> str:
    return "0x" + char * 40


def _insert_wallet_with_fills(config: AppConfig, wallet: str, pnls: list[float]) -> None:
    initialize_database(config)
    start = datetime.now(UTC) - timedelta(days=len(pnls) + 1)
    with get_connection(config) as conn:
        insert_wallet(conn, Wallet(address=wallet, source="test"))
        for index, pnl in enumerate(pnls):
            insert_fill(
                conn,
                Fill(
                    wallet_address=wallet,
                    coin="ETH",
                    side="Close Long",
                    price=100 + index,
                    size=1,
                    fee=0.01,
                    timestamp=start + timedelta(days=index),
                    raw_id=f"{wallet}-{index}",
                    closed_pnl=pnl,
                ),
            )
        conn.commit()


def test_hypersmart_score_wallet_with_valid_data(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet_address("a")
    _insert_wallet_with_fills(config, wallet, [2.0] * 20 + [-1.0] * 10)

    score = WalletScoreEngine(config).score_wallet(wallet)

    assert score.status == WalletScoreStatus.SCORED
    assert score.total_fills == 30
    assert score.usable_fills == 30
    assert score.net_pnl is not None
    assert score.profit_factor == 4.0
    assert score.final_score is not None


def test_hypersmart_score_wallet_without_fills(tmp_path):
    score = WalletScoreEngine(_config(tmp_path)).score_wallet(_wallet_address("b"))

    assert score.status == WalletScoreStatus.INSUFFICIENT_DATA
    assert score.refusal_reason == "NO_LOCAL_FILLS"


def test_hypersmart_score_wallet_with_invalid_fills(tmp_path):
    config = _config(tmp_path, min_fills_to_score=1, min_closed_pnl_points=1)
    wallet = _wallet_address("c")
    initialize_database(config)
    with get_connection(config) as conn:
        insert_wallet(conn, Wallet(address=wallet, source="test"))
        insert_fill(
            conn,
            Fill(
                wallet_address=wallet,
                coin="ETH",
                side="Close Long",
                price=0,
                size=1,
                fee=0,
                timestamp=datetime.now(UTC),
                closed_pnl=1,
            ),
        )
        conn.commit()

    score = WalletScoreEngine(config).score_wallet(wallet)

    assert score.status == WalletScoreStatus.INVALID_DATA


def test_hypersmart_score_wallet_blocked(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet_address("d")
    initialize_database(config)
    with get_connection(config) as conn:
        insert_wallet(conn, Wallet(address=wallet, source="test", status=WalletStatus.BLOCKED))
        conn.commit()

    score = WalletScoreEngine(config).score_wallet(wallet)

    assert score.status == WalletScoreStatus.BLOCKED


def test_hypersmart_score_stored_and_latest_retrievable(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet_address("e")
    _insert_wallet_with_fills(config, wallet, [2.0] * 20 + [-1.0] * 10)

    score = WalletScoreEngine(config).score_and_store_wallet(wallet)
    with get_connection(config) as conn:
        row = get_latest_score(conn, wallet)

    assert score.status == WalletScoreStatus.SCORED
    assert row is not None
    assert row["status"] == "SCORED"


def test_hypersmart_risk_gate_refuses_score_insufficient(tmp_path):
    score = WalletScoreEngine(_config(tmp_path)).score_wallet(_wallet_address("f"))

    decision = evaluate_wallet_score_for_research(score)

    assert not decision.allowed
    assert decision.reason_code == "WALLET_SCORE_NOT_SCORED"


def test_hypersmart_risk_gate_accepts_only_research_observation(tmp_path):
    config = _config(tmp_path)
    wallet = _wallet_address("1")
    _insert_wallet_with_fills(config, wallet, [2.0] * 20 + [-1.0] * 10)
    score = WalletScoreEngine(config).score_wallet(wallet)

    decision = evaluate_wallet_score_for_research(score, config)

    assert decision.allowed
    assert decision.reason_code == "RESEARCH_OBSERVATION_ONLY"
    assert "not a trading signal" in decision.message
