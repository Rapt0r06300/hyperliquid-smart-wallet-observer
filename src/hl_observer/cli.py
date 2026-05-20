from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import typer

from hl_observer.config.loader import load_settings
from hl_observer.config.settings import ExecutionEnvironment
from hl_observer.edge.edge_remaining import compute_edge_remaining
from hl_observer.hyperliquid.endpoints import info_url_for_settings
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient
from hl_observer.hyperliquid.schemas import EdgeRemainingInputs, RiskDecision, SignalDecision
from hl_observer.paper.paper_executor import PaperExecutor
from hl_observer.risk.gates import RiskContext
from hl_observer.risk.risk_engine import RiskEngine
from hl_observer.security.mainnet_guard import assert_mainnet_execution_disabled
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.storage.database import init_db as initialize_database
from hl_observer.testnet.testnet_order_builder import build_testnet_order_intent
from hl_observer.testnet.testnet_executor_locked import LockedTestnetExecutor
from hl_observer.testnet.testnet_safety_gates import TestnetLocked
from hl_observer.utils.logging import configure_logging

app = typer.Typer(
    name="hl_observer",
    help="Hyperliquid Smart-Wallet Observer. Read-only, paper-first, testnet locked.",
    no_args_is_help=True,
)


def _settings() -> object:
    settings = load_settings()
    configure_logging(settings.log_level)
    assert_mainnet_execution_disabled(settings)
    return settings


@app.command()
def doctor() -> None:
    """Check local configuration and safety posture."""
    settings = load_settings()
    configure_logging(settings.log_level)
    checks = {
        "python_3_11_plus": sys.version_info >= (3, 11),
        "readme_present": Path("README.md").exists(),
        "agents_present": Path("AGENTS.md").exists(),
        "env_example_present": Path(".env.example").exists(),
        "mainnet_execution_disabled": not settings.execution.enable_mainnet_execution,
        "testnet_execution_disabled_by_default": not settings.execution.enable_testnet_execution,
        "database_url_configured": bool(settings.database_url),
        "logs_dir_configured": bool(settings.logs_dir),
        "info_endpoint_read_only": info_url_for_settings(settings).endswith("/info"),
    }
    audit = run_safety_audit(".")
    checks["safety_audit_ok"] = audit.ok
    for name, ok in checks.items():
        typer.echo(f"{name}: {'ok' if ok else 'FAIL'}")
    if not all(checks.values()):
        raise typer.Exit(1)


@app.command("init-db")
def init_db() -> None:
    """Initialize the SQLite schema."""
    settings = _settings()
    initialize_database(settings.database_url)
    typer.echo(f"database initialized: {settings.database_url}")


@app.command("safety-audit")
def safety_audit() -> None:
    """Run local safety checks for secrets and forbidden execution paths."""
    result = run_safety_audit(".")
    for name, ok in result.checks.items():
        typer.echo(f"{name}: {'ok' if ok else 'FAIL'}")
    for finding in result.findings:
        typer.echo(f"finding: {finding}")
    if not result.ok:
        raise typer.Exit(1)


@app.command("collect-once")
def collect_once(
    coin: str = typer.Option("BTC", help="Coin to query if fetching l2Book."),
    fetch: bool = typer.Option(False, help="Actually call read-only /info endpoints."),
) -> None:
    """Run one read-only collection pass. Defaults to dry-run."""
    settings = _settings()
    if not fetch:
        typer.echo("dry-run: collect-once would query allMids and l2Book via /info only")
        return

    async def _run() -> None:
        async with HyperliquidInfoClient(
            info_url_for_settings(settings),
            timeout_seconds=settings.hyperliquid.timeout_seconds,
            max_retries=settings.hyperliquid.max_retries,
            backoff_base_seconds=settings.hyperliquid.backoff_base_seconds,
        ) as client:
            mids = await client.all_mids()
            book = await client.l2_book(coin)
            typer.echo(f"allMids_count={len(mids)} l2Book_keys={','.join(book.keys())}")

    asyncio.run(_run())


@app.command("score-wallets")
def score_wallets() -> None:
    """Placeholder for deterministic wallet scoring."""
    _settings()
    typer.echo("score-wallets ready: deterministic wallet scoring modules are available")


@app.command("detect-signals")
def detect_signals() -> None:
    """Placeholder for position-delta signal detection."""
    _settings()
    typer.echo("detect-signals ready: position delta detector and signal scoring are available")


@app.command("paper-run")
def paper_run() -> None:
    """Run a minimal safe paper-trading smoke path."""
    settings = _settings()
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            leader_expected_move_bps=30,
            taker_fee_bps=4,
            spread_cost_bps=2,
            estimated_slippage_bps=3,
            latency_decay_bps=2,
        ),
        min_edge_required_bps=settings.risk.min_edge_required_bps,
    )
    context = RiskContext(
        spread_bps=2,
        estimated_slippage_bps=3,
        orderbook_depth_usdc=10000,
        wallet_score=90,
        signal_score=90,
        edge_remaining_bps=edge.edge_remaining_bps,
        signal_age_ms=100,
    )
    decision = RiskEngine(settings).evaluate(context)
    PaperExecutor().orders
    typer.echo(f"paper-run smoke decision={decision.decision.value} allowed={decision.allowed}")


@app.command("paper-report")
def paper_report() -> None:
    """Report placeholder for paper trading results."""
    _settings()
    typer.echo("paper-report ready: no paper results recorded yet")


@app.command("testnet-check")
def testnet_check(
    confirm_testnet_only: bool = typer.Option(False, "--confirm-testnet-only"),
) -> None:
    """Check locked testnet execution gates without placing any order."""
    settings = _settings()
    risk = RiskDecision(
        allowed=True,
        decision=SignalDecision.TESTNET_CANDIDATE,
        reasons=["check only"],
        gates={"manual_check": True},
    )
    order = build_testnet_order_intent(
        cloid="check-only-cloid",
        coin="BTC",
        side="buy",
        size=0.001,
        limit_price=1.0,
        schedule_cancel_configured=True,
    )
    try:
        result = LockedTestnetExecutor(settings).submit(
            order,
            risk,
            confirm_testnet_only=confirm_testnet_only,
        )
    except TestnetLocked as exc:
        typer.echo(f"testnet locked: {', '.join(exc.reasons)}")
        return
    if settings.environment != ExecutionEnvironment.TESTNET:
        typer.echo("testnet not active")
        return
    typer.echo(f"testnet gates validated: {result['cloid']}")
