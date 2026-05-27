import os
import subprocess
import sys
from datetime import UTC, datetime

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import ScoreBreakdown, Wallet, WalletScoreStatus
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import scores_repo
from hyper_smart_observer.storage.repositories.wallet_repo import insert_wallet


def _wallet(char: str = "a") -> str:
    return "0x" + char * 40


def _setup_score(db_path, wallet):
    config = AppConfig(database_path=db_path)
    initialize_database(config)
    with get_connection(config) as conn:
        insert_wallet(conn, Wallet(address=wallet, source="cli-test"))
        scores_repo.insert_score_breakdown(
            conn,
            ScoreBreakdown(
                wallet_address=wallet,
                calculated_at=datetime.now(UTC),
                status=WalletScoreStatus.SCORED,
                total_fills=50,
                usable_fills=50,
                skipped_fills=0,
                confidence_score=90.0,
                sample_quality_score=90.0,
                risk_score=90.0,
                profit_factor=2.0,
                net_pnl=10.0,
                final_score=80.0,
            ),
        )
        conn.commit()


def _run_cli(db_path, *args):
    env = os.environ.copy()
    env["HYPERSMART_DATABASE_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, "-m", "hyper_smart_observer.app.main", *args],
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_hypersmart_cli_paper_open_works(tmp_path):
    db_path = tmp_path / "paper-cli.sqlite3"
    wallet = _wallet("a")
    _setup_score(db_path, wallet)

    result = _run_cli(
        db_path,
        "--paper-open",
        "--wallet",
        wallet,
        "--coin",
        "ETH",
        "--side",
        "BUY",
        "--reference-price",
        "100",
        "--notional",
        "50",
    )

    assert result.returncode == 0
    assert "LOCAL PAPER SIMULATION ONLY" in result.stdout
    assert "paper_trade_id" in result.stdout


def test_hypersmart_cli_paper_report_works(tmp_path):
    result = _run_cli(tmp_path / "paper-report.sqlite3", "--paper-report")

    assert result.returncode == 0
    assert "LOCAL PAPER SIMULATION ONLY" in result.stdout
    assert "open_trades=0" in result.stdout
