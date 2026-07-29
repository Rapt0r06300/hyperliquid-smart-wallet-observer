from __future__ import annotations

import json
import os
from pathlib import Path

from hl_observer.ops.pnl_improvement_lab import (
    HistoricalTrade,
    build_lab_report,
    compute_metrics,
    evaluate_candidate_rules,
    extract_historical_trades,
    write_lab_outputs,
)


def _trade(
    index: int,
    *,
    net: float,
    consensus: int = 1,
    notional: float = 50.0,
    side: str = "LONG",
) -> HistoricalTrade:
    return HistoricalTrade(
        trade_id=f"t-{index}",
        session_id=f"session-{index // 10}",
        source_path="synthetic-ledger.jsonl",
        opened_at_ms=1_000 + index * 10,
        closed_at_ms=1_005 + index * 10,
        coin="BTC" if index % 2 == 0 else "ETH",
        side=side,
        strategy="COPY",
        exit_method="SLTP_TRAILING_STOP" if net > 0 else "SLTP_STOP_LOSS",
        notional_usdt=notional,
        entry_price=100.0,
        exit_price=101.0 if net > 0 else 99.0,
        gross_pnl_usdc=net + 0.05,
        net_pnl_usdc=net,
        fees_reported_usdc=0.05,
        edge_remaining_bps=30.0,
        signal_age_ms=500,
        consensus_wallets=consensus,
        copy_degradation_bps=5.0,
        liquidity_score=0.9,
        leader_score=80.0,
        reconciliation_error_usdc=0.0,
        eligible_for_learning=True,
        exclusion_reasons=(),
    )


def _open_close_rows(index: int, *, legacy: bool = False) -> list[dict]:
    wallet = f"0x{index:040x}"
    coin = f"C{index}"
    key = f"{wallet}|{coin}|LONG"
    open_row = {
        "paper_action_type": "OPEN",
        "timestamp_ms": 1_000 + index * 100,
        "wallet_address": wallet,
        "coin": coin,
        "leader_side": "LONG",
        "entry_price": 100.0,
        "copied_notional_usdt": 50.0,
        "edge_remaining_bps": 25.0,
        "signal_age_ms": 400,
        "fee_cost_usdc": 0.02,
    }
    close_row = {
        "paper_action_type": "CLOSE",
        "timestamp_ms": 1_050 + index * 100,
        "matched_position_key": key,
        "coin": coin,
        "leader_side": "LONG",
        "average_entry_price": 100.0,
        "exit_price": 101.0,
        "gross_pnl_usdc": 0.5,
        "estimated_net_pnl_usdc": 0.45,
        "fee_cost_usdc": 0.05,
        "exit_method": (
            "QUALITY_GUARD_LEGACY_UNEVIDENCED" if legacy else "SLTP_TRAILING_STOP"
        ),
    }
    return [open_row, close_row]


def test_archived_canonical_ledgers_are_read_even_when_stale(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs a envoyer"
    ledger = log_dir / "_archives" / "session_20260101_000000" / "simulation_pnl_ledger_latest.jsonl"
    ledger.parent.mkdir(parents=True)
    rows = [
        *_open_close_rows(1),
        {"bot_decision": "EXTERNAL_GITHUB_PROFILE_EVALUATED", "timestamp_ms": 1_500},
        *_open_close_rows(2, legacy=True),
    ]
    ledger.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.utime(ledger, (1, 1))

    trades, quality = extract_historical_trades(log_dir)

    assert len(trades) == 2
    assert quality["paired_round_trips"] == 2
    assert quality["eligible_round_trips"] == 1
    assert quality["ignored_non_pnl_rows"] == 1
    assert quality["exclusion_reasons"]["LEGACY_UNEVIDENCED_EXIT"] == 1


def test_pnl_is_reconciled_from_prices_and_fixed_notional_comparison_is_fair(
    tmp_path: Path,
) -> None:
    actual_winner = _trade(1, net=10.0, notional=1_000.0)
    small_loser = _trade(2, net=-1.0, notional=10.0)

    metrics = compute_metrics([actual_winner, small_loser], comparison_notional_usdt=50.0)

    assert metrics["net_pnl_actual_usdc"] == 9.0
    assert metrics["normalized_net_usdc"] == -4.5
    assert metrics["comparison_notional_usdt"] == 50.0


def test_rule_selection_never_uses_holdout() -> None:
    prefix: list[HistoricalTrade] = []
    for index in range(48):
        good_consensus = index % 2 == 0
        prefix.append(
            _trade(
                index,
                net=1.0 if good_consensus else -1.5,
                consensus=3 if good_consensus else 1,
            )
        )
    profitable_holdout = [
        _trade(48 + index, net=1.0, consensus=3) for index in range(12)
    ]
    losing_holdout = [
        _trade(48 + index, net=-2.0, consensus=3) for index in range(12)
    ]

    report_a = evaluate_candidate_rules(
        [*prefix, *profitable_holdout],
        min_total_trades=30,
    )
    report_b = evaluate_candidate_rules(
        [*prefix, *losing_holdout],
        min_total_trades=30,
    )
    selected_a = {
        row["key"]: row["selected_before_holdout"] for row in report_a["candidates"]
    }
    selected_b = {
        row["key"]: row["selected_before_holdout"] for row in report_b["candidates"]
    }

    assert report_a["selection_uses_holdout"] is False
    assert report_b["selection_uses_holdout"] is False
    assert selected_a == selected_b
    assert selected_a["consensus_ge_2"] is True
    verdict_a = next(
        row["verdict"] for row in report_a["candidates"] if row["key"] == "consensus_ge_2"
    )
    verdict_b = next(
        row["verdict"] for row in report_b["candidates"] if row["key"] == "consensus_ge_2"
    )
    assert verdict_a == "ROBUST_HOLDOUT"
    assert verdict_b == "FAILED_HOLDOUT"


def test_insufficient_history_is_reported_without_promoting_a_flag() -> None:
    report = evaluate_candidate_rules(
        [_trade(index, net=0.1) for index in range(8)],
        min_total_trades=30,
    )

    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["automatic_activation"] is False
    assert report["candidates"] == []


def test_lab_writes_actionable_json_and_markdown(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs a envoyer"
    ledger = log_dir / "_archives" / "session_20260101_000000" / "simulation_pnl_ledger_latest.jsonl"
    ledger.parent.mkdir(parents=True)
    rows: list[dict] = []
    for index in range(36):
        rows.extend(_open_close_rows(index))
    ledger.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    report = build_lab_report(log_dir, min_total_trades=30)
    json_path, markdown_path = write_lab_outputs(report, tmp_path / "out")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["truth"]["eligible_for_learning"]["trades"] == 36
    assert payload["automatic_activation"] is False
    assert payload["experiment_backlog"]
    assert all(
        item["automatic_activation"] is False
        for item in payload["experiment_backlog"]
    )
    assert "Causes mesurees" in markdown
    assert "Attribution par methode de sortie" in markdown
    assert "Coins recurrents les plus couteux" in markdown
    assert "Pistes robustes" in markdown
    assert "Prochains A/B exacts" in markdown
    assert "Backlog d'experiences priorise" in markdown
    assert payload["experiment_backlog"][0]["experiment_id"] in markdown
    assert "Aucun flag n'est active" in markdown
