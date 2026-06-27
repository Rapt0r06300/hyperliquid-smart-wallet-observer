from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Callable

from hl_observer.simulation.log_metrics import LogDecisionRow, iter_decision_rows, row_from_payload, split_reasons


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    name: str
    max_signal_age_ms: int | None = None
    min_edge_remaining_bps: float | None = None
    max_copy_degradation_bps: float | None = None
    min_consensus_wallets: int | None = None
    open_only: bool = False
    disable_add_as_entry: bool = True
    reject_edge_sentinel: bool = True
    no_micro_trades_usdc: float | None = None


@dataclass(slots=True)
class StrategyResult:
    config: StrategyConfig
    total_events: int = 0
    selected_events: int = 0
    rejected_events: int = 0
    train_pnl_usdc: float = 0.0
    validation_pnl_usdc: float = 0.0
    holdout_pnl_usdc: float = 0.0
    total_net_pnl_usdc: float = 0.0
    fees_usdc: float = 0.0
    positive_events: int = 0
    negative_events: int = 0
    overfit_rejected: bool = False
    holdout_failed_after_selection: bool = False
    selected_as_best: bool = False

    @property
    def selection_score(self) -> float:
        """Score used for selection; deliberately excludes holdout.

        The holdout window is a final verification surface. Using it to pick the
        best config would leak future information into the simulated strategy.
        """

        if self.overfit_rejected:
            return -1_000_000.0
        train_validation_pnl = self.train_pnl_usdc + self.validation_pnl_usdc
        return min(self.validation_pnl_usdc, train_validation_pnl)


@dataclass(frozen=True, slots=True)
class OptimizationReport:
    source_dir: Path
    strategies: tuple[StrategyResult, ...]
    best: StrategyResult
    no_trade_baseline_pnl_usdc: float = 0.0
    anti_overfit_policy: str = "selection_uses_train_validation_only_holdout_is_verification_no_lookahead"

    @property
    def protection_mode_recommended(self) -> bool:
        return self.best.config.name == "no_trade_baseline"


def default_strategy_configs() -> tuple[StrategyConfig, ...]:
    return (
        StrategyConfig(name="no_trade_baseline", min_edge_remaining_bps=999_999),
        StrategyConfig(name="open_only_fresh_edge25", open_only=True, max_signal_age_ms=4_000, min_edge_remaining_bps=25),
        StrategyConfig(name="open_only_fresh_edge60", open_only=True, max_signal_age_ms=4_000, min_edge_remaining_bps=60),
        StrategyConfig(name="consensus3_edge25", max_signal_age_ms=8_000, min_edge_remaining_bps=25, min_consensus_wallets=3),
        StrategyConfig(name="strict_latency_edge40", max_signal_age_ms=2_000, min_edge_remaining_bps=40, max_copy_degradation_bps=10),
        StrategyConfig(name="no_micro_edge40", max_signal_age_ms=8_000, min_edge_remaining_bps=40, no_micro_trades_usdc=25),
        StrategyConfig(name="high_edge_only", max_signal_age_ms=15_000, min_edge_remaining_bps=80),
    )


def run_strategy_tournament(log_dir: Path, configs: tuple[StrategyConfig, ...] | None = None) -> OptimizationReport:
    configs = configs or default_strategy_configs()
    results = [StrategyResult(config=config) for config in configs]
    total_rows = _count_valid_rows(log_dir)
    valid_index = 0
    for _path, _line_number, payload in iter_decision_rows(log_dir):
        if payload.get("_json_error"):
            continue
        row = row_from_payload(payload)
        bucket = _bucket_for_index(valid_index, total_rows)
        valid_index += 1
        for result in results:
            result.total_events += 1
            if _strategy_accepts(result.config, row):
                result.selected_events += 1
                _apply_pnl(result, row, bucket)
            else:
                result.rejected_events += 1
    for result in results:
        result.total_net_pnl_usdc = round(result.train_pnl_usdc + result.validation_pnl_usdc + result.holdout_pnl_usdc, 8)
        result.train_pnl_usdc = round(result.train_pnl_usdc, 8)
        result.validation_pnl_usdc = round(result.validation_pnl_usdc, 8)
        result.holdout_pnl_usdc = round(result.holdout_pnl_usdc, 8)
        result.fees_usdc = round(result.fees_usdc, 8)
        result.overfit_rejected = (
            result.train_pnl_usdc > 0
            and result.validation_pnl_usdc < 0
        )
        result.holdout_failed_after_selection = result.holdout_pnl_usdc < 0
    best = max(results, key=lambda item: item.selection_score)
    best.selected_as_best = True
    return OptimizationReport(source_dir=log_dir, strategies=tuple(results), best=best)


def write_optimization_reports(report: OptimizationReport, output_dir: Path) -> tuple[Path, Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tournament_path = output_dir / "strategy_tournament.json"
    best_path = output_dir / "best_profit_config.json"
    walk_path = output_dir / "walk_forward_profit_validation.json"
    summary_path = output_dir / "profit_optimization_summary.md"
    tournament_path.write_text(json.dumps(_report_to_json(report), indent=2), encoding="utf-8")
    best_path.write_text(json.dumps(asdict(report.best.config), indent=2), encoding="utf-8")
    walk_path.write_text(json.dumps(_walk_forward_json(report), indent=2), encoding="utf-8")
    summary_path.write_text(format_optimization_report(report), encoding="utf-8")
    return tournament_path, best_path, walk_path, summary_path


def format_optimization_report(report: OptimizationReport) -> str:
    lines = [
        "profit_optimization=simulation_only_no_fake_gain",
        f"source_dir={report.source_dir}",
        f"best_config={report.best.config.name}",
        f"best_train_pnl_usdc={report.best.train_pnl_usdc:.6f}",
        f"best_validation_pnl_usdc={report.best.validation_pnl_usdc:.6f}",
        f"best_holdout_pnl_usdc={report.best.holdout_pnl_usdc:.6f}",
        f"best_total_net_pnl_usdc={report.best.total_net_pnl_usdc:.6f}",
        f"best_selected_events={report.best.selected_events}",
        f"best_holdout_failed_after_selection={str(report.best.holdout_failed_after_selection).lower()}",
        f"protection_mode_recommended={str(report.protection_mode_recommended).lower()}",
        "selection_uses_holdout=false",
        "holdout_is_verification_only=true",
        "strategies:",
    ]
    for result in report.strategies:
        lines.append(
            f"- {result.config.name}: train={result.train_pnl_usdc:.6f} "
            f"validation={result.validation_pnl_usdc:.6f} holdout={result.holdout_pnl_usdc:.6f} "
            f"total={result.total_net_pnl_usdc:.6f} selected={result.selected_events} "
            f"selection_score={result.selection_score:.6f} "
            f"overfit_rejected={str(result.overfit_rejected).lower()} "
            f"holdout_failed_after_selection={str(result.holdout_failed_after_selection).lower()}"
        )
    lines.extend(
        [
            "no_trade_baseline_pnl_usdc=0.000000",
            "anti_overfit=train_validation_selection_holdout_verification_only",
            "beginner_summary="
            + (
                "Mode protection recommande: les strategies candidates perdent apres couts sur ces logs."
                if report.protection_mode_recommended
                else "Une strategie candidate bat no-trade sur train/validation; verifier le holdout avant confiance."
            ),
            "execution=forbidden",
            "paper_simulation_only=true",
            "profit_guarantee=false",
        ]
    )
    return "\n".join(lines)


def _strategy_accepts(config: StrategyConfig, row: LogDecisionRow) -> bool:
    if config.name == "no_trade_baseline":
        return False
    if row.status == "REFUSED":
        return False
    action = row.action.upper()
    if not _is_paper_trade_action(action):
        return False
    reasons = set(split_reasons(row.reason))
    if config.open_only and not _is_entry_action(action):
        return False
    if config.disable_add_as_entry and _is_add_as_initial_entry_action(action):
        return False
    if "NO_MATCHING_PAPER_POSITION_FOR_CLOSE" in reasons:
        return False
    edge = row.edge_remaining_bps
    if config.reject_edge_sentinel and (edge is None or edge <= -9_000):
        return False
    if config.min_edge_remaining_bps is not None and (edge is None or edge < config.min_edge_remaining_bps):
        return False
    if config.max_signal_age_ms is not None and (row.signal_age_ms is None or row.signal_age_ms > config.max_signal_age_ms):
        return False
    if config.max_copy_degradation_bps is not None and (
        row.copy_degradation_bps is None or row.copy_degradation_bps > config.max_copy_degradation_bps
    ):
        return False
    if config.min_consensus_wallets is not None and (row.consensus_wallets is None or row.consensus_wallets < config.min_consensus_wallets):
        return False
    if config.no_micro_trades_usdc is not None and (row.notional_usdc is None or row.notional_usdc < config.no_micro_trades_usdc):
        return False
    return True


def _is_paper_trade_action(action: str) -> bool:
    action = action.upper()
    if action in {"NO_TRADE", "REFUSED", "STATE_CLEANUP"}:
        return False
    if "IGNORED" in action or "DUPLICATE" in action:
        return False
    return action.startswith("PAPER_")


def _is_entry_action(action: str) -> bool:
    action = action.upper()
    if "ADD" in action or "INCREASE" in action:
        return False
    return (
        "OPEN" in action
        or "ENTRY_REPLAYED" in action
        or action in {"PAPER_ENTRY_REPLAYED", "PAPER_CONSENSUS_ENTRY_REPLAYED"}
    )


def _is_add_as_initial_entry_action(action: str) -> bool:
    action = action.upper()
    return (
        "JOIN_ADD_AS_ENTRY" in action
        or "ADD_ENTRY" in action
        or action in {"PAPER_JOIN_ADD_AS_ENTRY", "PAPER_CONSENSUS_ADD_ENTRY_REPLAYED"}
    )


def _apply_pnl(result: StrategyResult, row: LogDecisionRow, bucket: str) -> None:
    pnl = row.estimated_net_pnl_usdc
    if bucket == "train":
        result.train_pnl_usdc += pnl
    elif bucket == "validation":
        result.validation_pnl_usdc += pnl
    else:
        result.holdout_pnl_usdc += pnl
    result.fees_usdc += row.fee_cost_usdc
    if pnl > 0:
        result.positive_events += 1
    if pnl < 0:
        result.negative_events += 1


def _bucket_for_index(index: int, total_rows: int | None = None) -> str:
    if total_rows is None or total_rows <= 0:
        modulo = index % 10
        if modulo < 6:
            return "train"
        if modulo < 8:
            return "validation"
        return "holdout"
    train_end = max(1, int(total_rows * 0.60))
    validation_end = max(train_end + 1, int(total_rows * 0.80))
    validation_end = min(validation_end, total_rows)
    if index < train_end:
        return "train"
    if index < validation_end:
        return "validation"
    return "holdout"


def _count_valid_rows(log_dir: Path) -> int:
    total = 0
    for _path, _line_number, payload in iter_decision_rows(log_dir):
        if not payload.get("_json_error"):
            total += 1
    return total


def _report_to_json(report: OptimizationReport) -> dict:
    return {
        "source_dir": str(report.source_dir),
        "best": _result_to_json(report.best),
        "strategies": [_result_to_json(result) for result in report.strategies],
        "no_trade_baseline_pnl_usdc": report.no_trade_baseline_pnl_usdc,
        "anti_overfit_policy": report.anti_overfit_policy,
        "protection_mode_recommended": report.protection_mode_recommended,
    }


def _result_to_json(result: StrategyResult) -> dict:
    return {
        "config": asdict(result.config),
        "total_events": result.total_events,
        "selected_events": result.selected_events,
        "rejected_events": result.rejected_events,
        "train_pnl_usdc": result.train_pnl_usdc,
        "validation_pnl_usdc": result.validation_pnl_usdc,
        "holdout_pnl_usdc": result.holdout_pnl_usdc,
        "total_net_pnl_usdc": result.total_net_pnl_usdc,
        "fees_usdc": result.fees_usdc,
        "positive_events": result.positive_events,
        "negative_events": result.negative_events,
        "selection_score": result.selection_score,
        "overfit_rejected": result.overfit_rejected,
        "holdout_failed_after_selection": result.holdout_failed_after_selection,
        "selected_as_best": result.selected_as_best,
    }


def _walk_forward_json(report: OptimizationReport) -> dict:
    return {
        "best_config": report.best.config.name,
        "selection_uses_holdout": False,
        "holdout_is_verification_only": True,
        "protection_mode_recommended": report.protection_mode_recommended,
        "windows": {
            "train": report.best.train_pnl_usdc,
            "validation": report.best.validation_pnl_usdc,
            "holdout": report.best.holdout_pnl_usdc,
        },
        "accepted": not report.best.overfit_rejected and not report.best.holdout_failed_after_selection,
        "warning": "historical simulation is not future profit",
    }
