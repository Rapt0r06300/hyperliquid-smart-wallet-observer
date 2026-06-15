from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
from statistics import median
from typing import Any, Iterable


DECISION_LOG_FILES = (
    "simulation_decisions_latest.jsonl",
    "cli_simulation_decisions_latest.jsonl",
    "simulation_decisions_append_only.jsonl",
)
STRUCTURED_DECISION_LOG = ("structured", "decisions.jsonl")


@dataclass(slots=True)
class LogDecisionRow:
    timestamp_ms: int | None
    wallet_address: str | None
    coin: str | None
    action: str
    status: str
    reason: str
    edge_remaining_bps: float | None
    copy_degradation_bps: float | None
    signal_age_ms: int | None
    consensus_wallets: int | None
    notional_usdc: float | None
    estimated_net_pnl_usdc: float
    gross_pnl_usdc: float
    fee_cost_usdc: float


@dataclass(slots=True)
class LogMetricsReport:
    source_dir: Path
    source_files: tuple[Path, ...]
    total_lines: int = 0
    total_json_errors: int = 0
    total_decisions: int = 0
    accepted: int = 0
    refused: int = 0
    positive_events: int = 0
    negative_events: int = 0
    gross_pnl_usdc: float = 0.0
    net_pnl_usdc: float = 0.0
    fees_usdc: float = 0.0
    reasons: Counter[str] = field(default_factory=Counter)
    actions: Counter[str] = field(default_factory=Counter)
    status_counts: Counter[str] = field(default_factory=Counter)
    pnl_by_coin: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    pnl_by_wallet: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    pnl_by_action: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    pnl_by_reason: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    fees_by_action: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    edge_values: list[float] = field(default_factory=list)
    signal_age_values: list[int] = field(default_factory=list)
    edge_sentinel_count: int = 0
    edge_negative_count: int = 0
    edge_positive_count: int = 0
    orphan_close_count: int = 0
    add_without_open_count: int = 0

    @property
    def fee_drag_ratio(self) -> float:
        gross_abs = abs(self.gross_pnl_usdc)
        if gross_abs <= 0:
            return 0.0
        return round(self.fees_usdc / gross_abs, 8)

    @property
    def net_winrate(self) -> float:
        if self.positive_events + self.negative_events == 0:
            return 0.0
        return round(self.positive_events / (self.positive_events + self.negative_events), 8)

    @property
    def profit_factor_net(self) -> float:
        gains = sum(value for value in self.pnl_by_action.values() if value > 0)
        losses = abs(sum(value for value in self.pnl_by_action.values() if value < 0))
        if losses <= 0:
            return 0.0 if gains <= 0 else 999.0
        return round(gains / losses, 8)


def iter_decision_rows(log_dir: Path) -> Iterable[tuple[Path, int, dict[str, Any]]]:
    for path in _existing_decision_files(log_dir):
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    yield path, line_number, {"_json_error": True}
                    continue
                if isinstance(payload, dict):
                    yield path, line_number, payload


def analyze_logs_streaming(log_dir: Path) -> LogMetricsReport:
    report = LogMetricsReport(source_dir=log_dir, source_files=tuple(_existing_decision_files(log_dir)))
    for _path, _line_number, raw in iter_decision_rows(log_dir):
        report.total_lines += 1
        if raw.get("_json_error"):
            report.total_json_errors += 1
            continue
        row = row_from_payload(raw)
        report.total_decisions += 1
        report.actions[row.action] += 1
        report.status_counts[row.status] += 1
        is_refused = row.status == "REFUSED" or row.action in {"NO_TRADE", "REFUSED"}
        if is_refused:
            report.refused += 1
        else:
            report.accepted += 1
        if row.reason and is_refused:
            for reason in split_reasons(row.reason):
                report.reasons[reason] += 1
                report.pnl_by_reason[reason] += row.estimated_net_pnl_usdc
                if reason == "NO_MATCHING_PAPER_POSITION_FOR_CLOSE":
                    report.orphan_close_count += 1
                if reason == "ADD_WITHOUT_ORIGINAL_OPEN_REFUSED":
                    report.add_without_open_count += 1
        elif row.reason:
            for reason in split_reasons(row.reason):
                report.pnl_by_reason[reason] += row.estimated_net_pnl_usdc
        if row.estimated_net_pnl_usdc > 0:
            report.positive_events += 1
        if row.estimated_net_pnl_usdc < 0:
            report.negative_events += 1
        report.gross_pnl_usdc += row.gross_pnl_usdc
        report.net_pnl_usdc += row.estimated_net_pnl_usdc
        report.fees_usdc += row.fee_cost_usdc
        report.pnl_by_action[row.action] += row.estimated_net_pnl_usdc
        report.fees_by_action[row.action] += row.fee_cost_usdc
        if row.coin:
            report.pnl_by_coin[row.coin] += row.estimated_net_pnl_usdc
        if row.wallet_address:
            report.pnl_by_wallet[row.wallet_address] += row.estimated_net_pnl_usdc
        if row.edge_remaining_bps is not None:
            report.edge_values.append(row.edge_remaining_bps)
            if row.edge_remaining_bps <= -9_000:
                report.edge_sentinel_count += 1
            elif row.edge_remaining_bps < 0:
                report.edge_negative_count += 1
            elif row.edge_remaining_bps > 0:
                report.edge_positive_count += 1
        if row.signal_age_ms is not None:
            report.signal_age_values.append(row.signal_age_ms)
    report.gross_pnl_usdc = round(report.gross_pnl_usdc, 8)
    report.net_pnl_usdc = round(report.net_pnl_usdc, 8)
    report.fees_usdc = round(report.fees_usdc, 8)
    return report


def row_from_payload(row: dict[str, Any]) -> LogDecisionRow:
    event_type = _to_str(row.get("event_type"))
    action = _to_str(row.get("bot_decision") or row.get("action") or row.get("leader_action") or event_type or "UNKNOWN") or "UNKNOWN"
    status = _row_status(row).upper()
    return LogDecisionRow(
        timestamp_ms=_to_int(row.get("timestamp_ms") or row.get("recorded_at_ms") or row.get("closed_at_ms")),
        wallet_address=_to_str(row.get("wallet_address") or row.get("leader_wallet")),
        coin=_to_str(row.get("coin") or row.get("market_id")),
        action=action.upper(),
        status=status,
        reason=_to_str(row.get("reason")) or "",
        edge_remaining_bps=_to_float(row.get("edge_remaining_bps")),
        copy_degradation_bps=_to_float(row.get("copy_degradation_bps")),
        signal_age_ms=_to_int(row.get("signal_age_ms")),
        consensus_wallets=_to_int(row.get("consensus_wallets") or row.get("wallet_count")),
        notional_usdc=_to_float(row.get("copied_notional_usdt") or row.get("notional") or row.get("notional_usdc") or row.get("size")),
        estimated_net_pnl_usdc=_row_event_net_pnl(row) or 0.0,
        gross_pnl_usdc=_to_float(row.get("gross_pnl_usdc") or row.get("gross_pnl")) or 0.0,
        fee_cost_usdc=_row_event_fee(row) or 0.0,
    )


def split_reasons(reason: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in reason.replace(",", "|").split("|") if part.strip())


def format_logs_analysis(report: LogMetricsReport) -> str:
    edge_stats = _numeric_summary(report.edge_values)
    age_stats = _numeric_summary(report.signal_age_values)
    lines = [
        "logs_analyze=simulation_read_only",
        f"source_dir={report.source_dir}",
        "source_files=" + ",".join(path.name for path in report.source_files),
        f"total_lines={report.total_lines}",
        f"json_errors={report.total_json_errors}",
        f"total_decisions={report.total_decisions}",
        f"accepted={report.accepted}",
        f"refused={report.refused}",
        f"positive_events={report.positive_events}",
        f"negative_events={report.negative_events}",
        f"gross_pnl_usdc={report.gross_pnl_usdc:.6f}",
        f"net_pnl_usdc={report.net_pnl_usdc:.6f}",
        f"fees_usdc={report.fees_usdc:.6f}",
        f"fee_drag_ratio={report.fee_drag_ratio:.6f}",
        f"net_winrate={report.net_winrate:.6f}",
        f"profit_factor_net={report.profit_factor_net:.6f}",
        f"edge_sentinel_count={report.edge_sentinel_count}",
        f"edge_negative_count={report.edge_negative_count}",
        f"edge_positive_count={report.edge_positive_count}",
        f"signal_age_min_ms={age_stats['min']}",
        f"signal_age_p50_ms={age_stats['p50']}",
        f"signal_age_p95_ms={age_stats['p95']}",
        f"signal_age_max_ms={age_stats['max']}",
        f"edge_min_bps={edge_stats['min']}",
        f"edge_p50_bps={edge_stats['p50']}",
        f"edge_p95_bps={edge_stats['p95']}",
        f"edge_max_bps={edge_stats['max']}",
        f"orphan_close_count={report.orphan_close_count}",
        f"add_without_open_count={report.add_without_open_count}",
        "top_refusal_reasons:",
    ]
    lines.extend(f"- {reason}: {count}" for reason, count in report.reasons.most_common(12))
    lines.append("top_losing_coins:")
    lines.extend(_format_rank(report.pnl_by_coin, reverse=False, limit=10))
    lines.append("top_losing_wallets:")
    lines.extend(_format_rank(report.pnl_by_wallet, reverse=False, limit=10))
    lines.append("pnl_by_action:")
    lines.extend(_format_rank(report.pnl_by_action, reverse=True, limit=20))
    lines.append("recommendations:")
    lines.extend(f"- {item}" for item in build_recommendations(report))
    lines.append("execution=forbidden")
    lines.append("simulation_only=true")
    return "\n".join(lines)


def build_recommendations(report: LogMetricsReport) -> tuple[str, ...]:
    recommendations: list[str] = []
    if report.edge_sentinel_count:
        recommendations.append("Rejeter systematiquement edge=-9999: edge non mesurable.")
    if report.reasons["STALE_SIGNAL"] > report.total_decisions * 0.10:
        recommendations.append("Reduire max_signal_age_ms et privilegier WS shortlist/read-only pour les vrais OPEN frais.")
    if report.reasons["NO_MATCHING_PAPER_POSITION_FOR_CLOSE"]:
        recommendations.append("Traiter REDUCE/CLOSE sans position paper comme observe-only, sans modifier le PnL.")
    if report.reasons["ADD_WITHOUT_ORIGINAL_OPEN_REFUSED"] or report.actions["ADD"]:
        recommendations.append("Interdire ADD comme entree initiale sauf OPEN original connu et position deja protegee.")
    if report.fee_drag_ratio > 0.25:
        recommendations.append("Activer fee_drag_guard, min_notional et no_micro_trades: les couts mangent l'edge.")
    if report.net_pnl_usdc < 0:
        recommendations.append("Tester OPEN-only, consensus>=3, min_edge plus haut et cooldown coins/wallets perdants.")
    if not recommendations:
        recommendations.append("Continuer la collecte: pas de cause dominante assez forte dans ces logs.")
    return tuple(recommendations)


def _existing_decision_files(log_dir: Path) -> list[Path]:
    """Return one active decision source, preferring fresh/small logs.

    The dYdX paper engine writes ``logs/structured/decisions.jsonl`` while the
    historical HyperSmart exporter writes under ``logs/logs à envoyer``. Using a
    single prioritized source avoids double-counting the same simulated
    decisions and avoids streaming multi-GB append-only archives during UI QA.
    """

    structured = log_dir.parent.joinpath(*STRUCTURED_DECISION_LOG)
    for path in (
        log_dir / "simulation_decisions_latest.jsonl",
        structured,
        log_dir / "cli_simulation_decisions_latest.jsonl",
        log_dir / "simulation_decisions_append_only.jsonl",
    ):
        if path.exists() and path.stat().st_size > 0:
            return [path]
    return []


def _row_status(row: dict[str, Any]) -> str:
    status = _to_str(row.get("status"))
    if status:
        return status
    event_type = (_to_str(row.get("event_type")) or "").upper()
    if event_type == "NO_TRADE":
        return "REFUSED"
    if event_type.startswith("PAPER_"):
        return "LOCAL_REPLAY"
    return "LOCAL_REPLAY"


def _row_event_net_pnl(row: dict[str, Any]) -> float | None:
    event_type = (_to_str(row.get("event_type")) or "").upper()
    if event_type == "NO_TRADE":
        return 0.0
    if event_type == "PAPER_OPEN":
        fee = _to_float(row.get("fee_paid") or row.get("fee_cost_usdc") or row.get("fee"))
        return -fee if fee is not None else 0.0
    if event_type in {"PAPER_CLOSE", "PAPER_PARTIAL_TP"}:
        pnl = _to_float(row.get("net_pnl") or row.get("event_net_pnl_usdc"))
        return pnl if pnl is not None else 0.0
    return _to_float(row.get("estimated_net_pnl_usdc") or row.get("realized_pnl"))


def _row_event_fee(row: dict[str, Any]) -> float | None:
    event_type = (_to_str(row.get("event_type")) or "").upper()
    if event_type == "PAPER_OPEN":
        return _to_float(row.get("fee_paid") or row.get("fee_cost_usdc") or row.get("fee"))
    if event_type in {"PAPER_CLOSE", "PAPER_PARTIAL_TP"}:
        gross = _to_float(row.get("gross_pnl") or row.get("gross_pnl_usdc"))
        net = _to_float(row.get("net_pnl") or row.get("event_net_pnl_usdc"))
        if gross is not None and net is not None:
            return abs(gross - net)
    return _to_float(row.get("fee_cost_usdc") or row.get("fee"))


def _numeric_summary(values: list[int] | list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "min": round(float(ordered[0]), 6),
        "p50": round(float(median(ordered)), 6),
        "p95": round(float(ordered[p95_index]), 6),
        "max": round(float(ordered[-1]), 6),
    }


def _format_rank(values: dict[str, float], *, reverse: bool, limit: int) -> list[str]:
    ranked = sorted(values.items(), key=lambda item: item[1], reverse=reverse)[:limit]
    return [f"- {key}: {value:.6f}" for key, value in ranked]


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
