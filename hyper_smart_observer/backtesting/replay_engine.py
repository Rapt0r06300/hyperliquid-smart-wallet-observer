from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.wallet_following_simulator import simulate_wallet_following
from hyper_smart_observer.copy_mode.copy_run_evidence import apply_runtime_leader_exits_with_evidence
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
from hyper_smart_observer.hyperliquid_client import models as common_data_model
from hyper_smart_observer.paper_trading.exit_engine import ExitTrigger, LeaderExitSignal
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from hyper_smart_observer.risk_engine.gates import evaluate_paper_intent


@dataclass(frozen=True)
class PaperReplayEvent:
    """Local replay event using the same paper engine as runtime copy mode."""

    action: str  # OPEN_LONG | OPEN_SHORT | CLOSE_LONG | CLOSE_SHORT | REDUCE
    coin: str
    price: float
    notional: float = 50.0
    ts_ms: int = 0


@dataclass(frozen=True)
class PaperReplayResult:
    opened: int
    closed: int
    skipped: int
    realized_pnl: float
    open_trades: int
    ledger_entries: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaperReplayExport:
    json_path: Path
    csv_path: Path
    markdown_path: Path


class ReplayEngine:
    common_data_model = common_data_model
    edge_calculator = staticmethod(compute_edge_remaining_bps)
    risk_gate = staticmethod(evaluate_paper_intent)
    paper_engine_cls = PaperTradingSimulator

    def replay_closed_pnl(self, wallet_address: str, closed_pnls: list[float]) -> BacktestReport:
        return simulate_wallet_following(wallet_address, closed_pnls)

    def replay_paper_events(
        self,
        config,
        wallet_address: str,
        events: list[PaperReplayEvent],
        *,
        run_id: str = "paper-replay",
    ) -> PaperReplayResult:
        """Replay leader open/reduce/close through the existing PaperTradingSimulator.

        This is a local backtest/simulation path only. It intentionally reuses the
        same PaperEngine and leader-exit evidence adapter as runtime copy-run so
        replay PnL is not computed by a parallel model.
        """

        simulator = self.paper_engine_cls(config)
        opened = 0
        skipped = 0
        warnings: list[str] = []
        ledger_entries = []
        for event in sorted(events, key=lambda item: item.ts_ms):
            action = event.action.upper()
            if action in {"OPEN_LONG", "OPEN_SHORT"}:
                side = "BUY" if action == "OPEN_LONG" else "SELL"
                result = simulator.open_paper_trade(
                    simulator.create_intent_from_wallet_score(
                        wallet_address,
                        event.coin,
                        side,
                        event.price,
                        event.notional,
                    )
                )
                if result.success:
                    opened += 1
                else:
                    skipped += 1
                    warnings.append(result.message)
                continue
            if action in {"CLOSE_LONG", "CLOSE_SHORT", "REDUCE"}:
                trigger = ExitTrigger.LEADER_REDUCE if action == "REDUCE" else ExitTrigger.LEADER_CLOSE
                evidence = apply_runtime_leader_exits_with_evidence(
                    simulator,
                    [
                        LeaderExitSignal(
                            coin=event.coin,
                            trigger=trigger,
                            exit_reference_price=event.price,
                            wallet_address=wallet_address,
                        )
                    ],
                    reports_dir=config.reports_dir,
                    run_id=run_id,
                    write_ledger=False,
                )
                ledger_entries.extend(evidence.ledger_entries)
                skipped += sum(1 for entry in evidence.ledger_entries if entry.decision_type == "PAPER_EXIT_NO_TRADE")
                continue
            skipped += 1
            warnings.append(f"unknown_replay_action:{event.action}")
        report = simulator.generate_report()
        return PaperReplayResult(
            opened=opened,
            closed=int(report["closed_trades"]),
            skipped=skipped,
            realized_pnl=float(report["realized_pnl"]),
            open_trades=int(report["open_trades"]),
            ledger_entries=ledger_entries,
            warnings=warnings,
        )


def write_paper_replay_result(
    result: PaperReplayResult,
    output_dir: Path | str,
    *,
    run_id: str,
    scenario: str = "paper_replay",
) -> PaperReplayExport:
    """Persist a paper replay in JSON/CSV/Markdown without fabricating PnL."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_run = run_id.replace("/", "_").replace("\\", "_").replace(":", "_") or "paper_replay"
    generated_at = datetime.now(timezone.utc).isoformat()
    ledger_rows = [entry.to_row() if hasattr(entry, "to_row") else dict(entry) for entry in result.ledger_entries]
    payload = {
        **asdict(result),
        "ledger_entries": ledger_rows,
        "generated_at": generated_at,
        "scenario": scenario,
        "requested_wallets": 1,
        "simulated_wallets": 1 if result.opened or result.closed else 0,
        "total_usable_trades": result.opened + result.closed,
        "total_skipped_actions": result.skipped,
        "gross_pnl": result.realized_pnl,
        "total_costs": None,
        "net_pnl": result.realized_pnl,
        "max_drawdown": None,
        "disclaimer": "local paper replay only; historical simulation is not future profit",
    }
    json_path = output_dir / f"paper_replay_{safe_run}.json"
    csv_path = output_dir / f"paper_replay_{safe_run}.csv"
    markdown_path = output_dir / f"paper_replay_{safe_run}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["generated_at", "scenario", "opened", "closed", "skipped", "realized_pnl", "open_trades", "warnings"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "generated_at": generated_at,
                "scenario": scenario,
                "opened": result.opened,
                "closed": result.closed,
                "skipped": result.skipped,
                "realized_pnl": result.realized_pnl,
                "open_trades": result.open_trades,
                "warnings": "|".join(result.warnings),
            }
        )
    markdown_path.write_text(
        "\n".join(
            [
                "# Paper Replay Report",
                "",
                f"- generated_at: `{generated_at}`",
                f"- scenario: `{scenario}`",
                f"- opened: `{result.opened}`",
                f"- closed: `{result.closed}`",
                f"- skipped: `{result.skipped}`",
                f"- realized_pnl: `{result.realized_pnl}`",
                f"- open_trades: `{result.open_trades}`",
                "",
                "Local paper replay only. Historical simulation is not future profit.",
            ]
        ),
        encoding="utf-8",
    )
    return PaperReplayExport(json_path=json_path, csv_path=csv_path, markdown_path=markdown_path)
