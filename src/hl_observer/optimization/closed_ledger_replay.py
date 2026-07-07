from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from hl_observer.simulation.log_metrics import iter_decision_rows, iter_supplemental_ledger_rows


@dataclass(frozen=True, slots=True)
class ClosedLedgerTrade:
    index: int
    observed_at_ms: int | None
    coin: str
    side: str
    pnl_usdc: float
    gross_pnl_usdc: float
    fee_cost_usdc: float
    notional_usdc: float | None
    action: str
    exit_method: str
    reason: str
    entry_context_found: bool
    dedupe_key: str


@dataclass(frozen=True, slots=True)
class ClosedLedgerReplayConfig:
    name: str
    no_trade: bool = False
    cooldown_after_loss_events: int = 0
    min_notional_usdc: float | None = None
    require_entry_context: bool = False
    excluded_coins: tuple[str, ...] = ()
    diagnostic_only: bool = False


@dataclass(slots=True)
class ClosedLedgerReplayResult:
    config: ClosedLedgerReplayConfig
    total_closed_trades: int = 0
    selected_closed_trades: int = 0
    skipped_closed_trades: int = 0
    skipped_by_cooldown: int = 0
    skipped_by_filter: int = 0
    train_pnl_usdc: float = 0.0
    validation_pnl_usdc: float = 0.0
    holdout_pnl_usdc: float = 0.0
    total_net_pnl_usdc: float = 0.0
    fees_usdc: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    overfit_rejected: bool = False
    holdout_failed_after_selection: bool = False
    selected_as_best: bool = False

    @property
    def selection_score(self) -> float:
        if self.config.diagnostic_only or self.overfit_rejected:
            return -1_000_000.0
        train_validation = self.train_pnl_usdc + self.validation_pnl_usdc
        return min(self.validation_pnl_usdc, train_validation)


@dataclass(frozen=True, slots=True)
class ClosedLedgerReplayReport:
    source_dir: Path
    trades: tuple[ClosedLedgerTrade, ...]
    strategies: tuple[ClosedLedgerReplayResult, ...]
    best: ClosedLedgerReplayResult
    anti_lookahead_policy: str = "causal_closed_ledger_replay_train_validation_selection_holdout_verification"

    @property
    def protection_mode_recommended(self) -> bool:
        return self.best.config.no_trade


def default_closed_ledger_replay_configs() -> tuple[ClosedLedgerReplayConfig, ...]:
    return (
        ClosedLedgerReplayConfig(name="no_trade_baseline", no_trade=True),
        ClosedLedgerReplayConfig(name="observed_all_closed_trades"),
        ClosedLedgerReplayConfig(name="coin_cooldown_after_loss_1", cooldown_after_loss_events=1),
        ClosedLedgerReplayConfig(name="coin_cooldown_after_loss_3", cooldown_after_loss_events=3),
        ClosedLedgerReplayConfig(name="coin_cooldown_after_loss_5", cooldown_after_loss_events=5),
        ClosedLedgerReplayConfig(name="entry_context_only", require_entry_context=True),
        ClosedLedgerReplayConfig(name="notional_at_least_40", min_notional_usdc=40.0),
    )


def run_closed_ledger_replay(
    log_dir: Path,
    configs: tuple[ClosedLedgerReplayConfig, ...] | None = None,
) -> ClosedLedgerReplayReport:
    trades = tuple(_iter_closed_ledger_trades(log_dir))
    configs = configs or default_closed_ledger_replay_configs()
    results = tuple(_evaluate_config(config, trades) for config in configs)
    best = max(results, key=lambda item: item.selection_score) if results else ClosedLedgerReplayResult(
        config=ClosedLedgerReplayConfig(name="no_trade_baseline", no_trade=True)
    )
    best.selected_as_best = True
    return ClosedLedgerReplayReport(source_dir=log_dir, trades=trades, strategies=results, best=best)


def write_closed_ledger_replay_reports(report: ClosedLedgerReplayReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "closed_ledger_replay.json"
    md_path = output_dir / "closed_ledger_replay_summary.md"
    json_path.write_text(json.dumps(_report_to_json(report), indent=2), encoding="utf-8")
    md_path.write_text(format_closed_ledger_replay_report(report), encoding="utf-8")
    return json_path, md_path


def format_closed_ledger_replay_report(report: ClosedLedgerReplayReport) -> str:
    lines = [
        "closed_ledger_replay=simulation_only_no_fake_gain",
        f"source_dir={report.source_dir}",
        f"closed_trades_seen={len(report.trades)}",
        f"best_config={report.best.config.name}",
        f"best_train_pnl_usdc={report.best.train_pnl_usdc:.6f}",
        f"best_validation_pnl_usdc={report.best.validation_pnl_usdc:.6f}",
        f"best_holdout_pnl_usdc={report.best.holdout_pnl_usdc:.6f}",
        f"best_total_net_pnl_usdc={report.best.total_net_pnl_usdc:.6f}",
        f"best_selected_closed_trades={report.best.selected_closed_trades}",
        f"protection_mode_recommended={str(report.protection_mode_recommended).lower()}",
        "selection_uses_holdout=false",
        "holdout_is_verification_only=true",
        "strategies:",
    ]
    for result in report.strategies:
        lines.append(
            f"- {result.config.name}: train={result.train_pnl_usdc:.6f} "
            f"validation={result.validation_pnl_usdc:.6f} holdout={result.holdout_pnl_usdc:.6f} "
            f"total={result.total_net_pnl_usdc:.6f} selected={result.selected_closed_trades} "
            f"skipped={result.skipped_closed_trades} cooldown_skips={result.skipped_by_cooldown} "
            f"fees={result.fees_usdc:.6f} wins={result.winning_trades} losses={result.losing_trades} "
            f"selection_score={result.selection_score:.6f} "
            f"overfit_rejected={str(result.overfit_rejected).lower()} "
            f"holdout_failed_after_selection={str(result.holdout_failed_after_selection).lower()}"
        )
    lines.extend(
        [
            "causal_policy=trade_filters_use_only_prior_closed_outcomes",
            "historical_result_is_not_future_profit=true",
            "execution=forbidden",
            "paper_simulation_only=true",
            "profit_guarantee=false",
        ]
    )
    return "\n".join(lines)


def _evaluate_config(
    config: ClosedLedgerReplayConfig,
    trades: tuple[ClosedLedgerTrade, ...],
) -> ClosedLedgerReplayResult:
    result = ClosedLedgerReplayResult(config=config, total_closed_trades=len(trades))
    cooldown_by_coin: dict[str, int] = {}
    total = len(trades)
    excluded = {coin.upper() for coin in config.excluded_coins}
    for trade in trades:
        bucket = _bucket_for_index(trade.index, total)
        accepted = False
        cooldown_skip = False
        if config.no_trade:
            result.skipped_by_filter += 1
        elif trade.coin.upper() in excluded:
            result.skipped_by_filter += 1
        elif config.min_notional_usdc is not None and (
            trade.notional_usdc is None or trade.notional_usdc < config.min_notional_usdc
        ):
            result.skipped_by_filter += 1
        elif config.require_entry_context and not trade.entry_context_found:
            result.skipped_by_filter += 1
        elif cooldown_by_coin.get(trade.coin, 0) > 0:
            cooldown_by_coin[trade.coin] -= 1
            result.skipped_by_cooldown += 1
            cooldown_skip = True
        else:
            accepted = True

        if not accepted:
            result.skipped_closed_trades += 1
            if not cooldown_skip and trade.coin in cooldown_by_coin and cooldown_by_coin[trade.coin] <= 0:
                cooldown_by_coin.pop(trade.coin, None)
            continue

        result.selected_closed_trades += 1
        _apply_trade_pnl(result, trade, bucket)
        if trade.pnl_usdc < 0 and config.cooldown_after_loss_events > 0:
            cooldown_by_coin[trade.coin] = config.cooldown_after_loss_events
    result.train_pnl_usdc = round(result.train_pnl_usdc, 8)
    result.validation_pnl_usdc = round(result.validation_pnl_usdc, 8)
    result.holdout_pnl_usdc = round(result.holdout_pnl_usdc, 8)
    result.total_net_pnl_usdc = round(result.train_pnl_usdc + result.validation_pnl_usdc + result.holdout_pnl_usdc, 8)
    result.fees_usdc = round(result.fees_usdc, 8)
    result.overfit_rejected = result.train_pnl_usdc > 0 and result.validation_pnl_usdc < 0
    result.holdout_failed_after_selection = result.holdout_pnl_usdc < 0
    return result


def _apply_trade_pnl(result: ClosedLedgerReplayResult, trade: ClosedLedgerTrade, bucket: str) -> None:
    if bucket == "train":
        result.train_pnl_usdc += trade.pnl_usdc
    elif bucket == "validation":
        result.validation_pnl_usdc += trade.pnl_usdc
    else:
        result.holdout_pnl_usdc += trade.pnl_usdc
    result.fees_usdc += trade.fee_cost_usdc
    if trade.pnl_usdc > 0:
        result.winning_trades += 1
    elif trade.pnl_usdc < 0:
        result.losing_trades += 1


def _iter_closed_ledger_trades(log_dir: Path) -> Iterable[ClosedLedgerTrade]:
    seen: set[str] = set()
    raw_rows: list[dict[str, Any]] = []
    for _path, _line_number, payload in iter_decision_rows(log_dir):
        raw_rows.append(payload)
    for _path, _line_number, payload in iter_supplemental_ledger_rows(log_dir):
        raw_rows.append(payload)
    raw_rows.sort(key=lambda row: (_to_int(row.get("observed_at_ms") or row.get("timestamp_ms") or row.get("recorded_at_ms")) or 0))
    index = 0
    for payload in raw_rows:
        trade = _trade_from_payload(payload, index=index)
        if trade is None:
            continue
        key = trade.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        yield trade
        index += 1


def _trade_from_payload(payload: dict[str, Any], *, index: int) -> ClosedLedgerTrade | None:
    if payload.get("_json_error") or not isinstance(payload, dict):
        return None
    action = str(
        payload.get("bot_decision")
        or payload.get("bot_replay_action")
        or payload.get("paper_action_type")
        or payload.get("event_type")
        or ""
    ).upper()
    paper_action = str(payload.get("paper_action_type") or "").upper()
    combined = f"{action} {paper_action}"
    if not any(token in combined for token in ("CLOSE", "REDUCE", "EXIT", "STOP_LOSS", "TAKE_PROFIT", "TRAILING_STOP")):
        return None
    pnl = _to_float(payload.get("estimated_net_pnl_usdc") or payload.get("event_net_pnl_usdc") or payload.get("net_pnl"))
    if pnl is None:
        return None
    coin = str(payload.get("coin") or payload.get("market_id") or "UNKNOWN").upper()
    side = str(payload.get("leader_side") or payload.get("side") or payload.get("direction") or "UNKNOWN").upper()
    fee = _to_float(payload.get("fee_cost_usdc") or payload.get("fees_usdc") or payload.get("fee")) or 0.0
    gross = _to_float(payload.get("gross_pnl_usdc") or payload.get("gross_pnl")) or (pnl + fee)
    notional = _to_float(
        payload.get("copied_notional_usdt")
        or payload.get("entry_copied_notional_usdt")
        or payload.get("leader_notional_usdc")
        or payload.get("notional_usdc")
        or payload.get("notional")
    )
    return ClosedLedgerTrade(
        index=index,
        observed_at_ms=_to_int(payload.get("observed_at_ms") or payload.get("timestamp_ms") or payload.get("recorded_at_ms")),
        coin=coin,
        side=side,
        pnl_usdc=float(pnl),
        gross_pnl_usdc=float(gross),
        fee_cost_usdc=float(fee),
        notional_usdc=notional,
        action=action or paper_action or "CLOSE",
        exit_method=str(payload.get("exit_method") or ""),
        reason=str(payload.get("reason") or ""),
        entry_context_found=bool(payload.get("entry_context_found")),
        dedupe_key=_closed_trade_key(payload, pnl),
    )


def _closed_trade_key(payload: dict[str, Any], pnl: float) -> str:
    explicit = (
        payload.get("dedupe_identity")
        or payload.get("paper_position_instance_id")
        or payload.get("v9_paper_order_id")
        or payload.get("source_delta_key")
        or payload.get("delta_key")
    )
    if explicit:
        return "|".join(
            str(part or "")
            for part in (
                payload.get("paper_action_type") or payload.get("bot_replay_action"),
                explicit,
                payload.get("exit_price"),
                pnl,
            )
        )
    return "|".join(
        str(payload.get(key) or "")
        for key in (
            "observed_at_ms",
            "timestamp_ms",
            "coin",
            "leader_side",
            "entry_price",
            "exit_price",
            "estimated_net_pnl_usdc",
        )
    )


def _bucket_for_index(index: int, total_rows: int) -> str:
    if total_rows <= 0:
        return "train"
    train_end = max(1, int(total_rows * 0.60))
    validation_end = max(train_end + 1, int(total_rows * 0.80))
    validation_end = min(validation_end, total_rows)
    if index < train_end:
        return "train"
    if index < validation_end:
        return "validation"
    return "holdout"


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _report_to_json(report: ClosedLedgerReplayReport) -> dict[str, Any]:
    return {
        "source_dir": str(report.source_dir),
        "closed_trades_seen": len(report.trades),
        "best": _result_to_json(report.best),
        "strategies": [_result_to_json(result) for result in report.strategies],
        "anti_lookahead_policy": report.anti_lookahead_policy,
        "protection_mode_recommended": report.protection_mode_recommended,
        "historical_result_is_not_future_profit": True,
        "profit_guarantee": False,
    }


def _result_to_json(result: ClosedLedgerReplayResult) -> dict[str, Any]:
    return {
        "config": asdict(result.config),
        "total_closed_trades": result.total_closed_trades,
        "selected_closed_trades": result.selected_closed_trades,
        "skipped_closed_trades": result.skipped_closed_trades,
        "skipped_by_cooldown": result.skipped_by_cooldown,
        "skipped_by_filter": result.skipped_by_filter,
        "train_pnl_usdc": result.train_pnl_usdc,
        "validation_pnl_usdc": result.validation_pnl_usdc,
        "holdout_pnl_usdc": result.holdout_pnl_usdc,
        "total_net_pnl_usdc": result.total_net_pnl_usdc,
        "fees_usdc": result.fees_usdc,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "selection_score": result.selection_score,
        "overfit_rejected": result.overfit_rejected,
        "holdout_failed_after_selection": result.holdout_failed_after_selection,
        "selected_as_best": result.selected_as_best,
    }
