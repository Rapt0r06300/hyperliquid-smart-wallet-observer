from __future__ import annotations

import json
import typer
from pathlib import Path
from collections import Counter
from sqlalchemy import select
from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.models import PositionDeltaModel, MarketSnapshot
from hl_observer.backtest.replay_engine import run_scenario_comparison
from hl_observer.execution.decision_engine import SimulationConfig
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig

app = typer.Typer(name="backtest", help="High-performance Backtest & Replay Command Center.")

@app.command("run")
def run_backtest(
    wallet: str | None = typer.Option(None, "--wallet", help="Target a specific wallet address."),
    limit: int = typer.Option(1000, "--limit", help="Maximum historical events to replay."),
    export: bool = typer.Option(False, "--export", help="Export results to data/reports/."),
):
    """Replays historical leader deltas across multiple scenarios to compare performance."""
    settings = load_settings()
    engine = create_sqlite_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        query = select(PositionDeltaModel).order_by(PositionDeltaModel.exchange_ts.asc())
        if wallet: query = query.where(PositionDeltaModel.wallet_address == wallet)
        deltas = session.scalars(query.limit(limit)).all()

        if not deltas:
            typer.secho("No historical deltas found. Ensure wallets have been backfilled first.", fg="yellow")
            return

        # Load snapshots for dynamic mid price discovery
        snapshots_db = session.scalars(select(MarketSnapshot).order_by(MarketSnapshot.exchange_ts.asc()).limit(500)).all()
        hist_mids = [
            {"timestamp_ms": int(s.exchange_ts), "mids": {c.upper(): float(v) for c, v in s.raw_json.items()}}
            for s in snapshots_db if isinstance(s.raw_json, dict)
        ]

        # Fallback to latest mids if no history
        if not hist_mids:
            snapshot = session.scalars(select(MarketSnapshot).order_by(MarketSnapshot.id.desc()).limit(1)).first()
            mids = {c.upper(): float(v) for c, v in snapshot.raw_json.items()} if snapshot and isinstance(snapshot.raw_json, dict) else {}
        else: mids = hist_mids

        base_cfg = SimulationConfig(
            risk_config=RealtimeCopyRiskConfig(min_edge_required_bps=settings.risk.min_edge_required_bps)
        )

        typer.secho(f"[*] Replaying {len(deltas)} events with dynamic market discovery...", fg="cyan")
        results = run_scenario_comparison(deltas, mids, base_cfg)

        typer.echo("\n" + "="*95)
        typer.secho(f"{'SCENARIO COMPARISON REPORT':^95}", bold=True)
        typer.echo("="*95)
        header = f"{'Scenario':<20} | {'Signals':<7} | {'Trades':<7} | {'Partial':<7} | {'Missed':<7} | {'PnL ($)':<10} | {'ROI %':<8}"
        typer.secho(header, underline=True)

        export_data = {}
        for name, state in results.items():
            trades = state.executed_entries + state.executed_exits
            real_pnl = sum(e.get("estimated_net_pnl_usdc", 0.0) or 0.0 for e in state.ledger_events if e.get("status") == "LOCAL_REPLAY")
            roi = (real_pnl / state.starting_equity_usdt) * 100

            pnl_color = "green" if real_pnl >= 0 else "red"
            row = (
                f"{name:<20} | {state.total_signals:<7} | {trades:<7} | "
                f"{state.partial_fills_count:<7} | {state.missed_fills_count:<7} | "
            )
            typer.echo(row, nl=False)
            typer.secho(f"{real_pnl:>10.2f}", fg=pnl_color, nl=False)
            typer.echo(" | ", nl=False)
            typer.secho(f"{roi:>7.1f}%", fg=pnl_color)

            if export:
                export_data[name] = state.model_dump(mode='json')

        typer.echo("="*95)

        # Breakdown of refusal reasons for the WS_LIKE (default) scenario
        ws_state = results.get("WS_LIKE")
        if ws_state:
            reasons = Counter(e.get("reason") for e in ws_state.ledger_events if e.get("status") == "REFUSED")
            if reasons:
                typer.echo("\n[!] Top Refusal Reasons (WS_LIKE):")
                for reason, count in reasons.most_common(5):
                    typer.echo(f"  - {reason}: {count}")

        if export:
            report_dir = Path("data/reports")
            report_dir.mkdir(parents=True, exist_ok=True)
            wallet_label = wallet or "all_wallets"
            filename = report_dir / f"backtest_{wallet_label}_{len(deltas)}deltas.json"
            filename.write_text(json.dumps(export_data, indent=2))
            typer.secho(f"\n[+] Results exported to {filename}", fg="green")

if __name__ == "__main__":
    app()
