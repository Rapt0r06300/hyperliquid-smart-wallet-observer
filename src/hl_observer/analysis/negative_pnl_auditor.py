from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping

from hl_observer.optimization.profit_optimizer import OptimizationReport, run_strategy_tournament
from hl_observer.risk.risk_engine_v3 import (
    V19RiskDecision,
    decision_to_dict,
    evaluate_v19_risk_gates,
    format_v19_risk_decision,
    quarantine_suggestions_from_breakdowns,
)
from hl_observer.simulation.decision_replay_analyzer import default_logs_to_send_dir
from hl_observer.simulation.log_metrics import LogMetricsReport, analyze_logs_streaming, build_recommendations


@dataclass(frozen=True, slots=True)
class LossBucket:
    key: str
    pnl_usdc: float


@dataclass(frozen=True, slots=True)
class SnapshotPnL:
    source_path: Path | None
    starting_equity_usdt: float | None
    current_equity_usdt: float | None
    net_pnl_usdc: float | None
    realized_pnl_usdc: float | None
    unrealized_pnl_usdc: float | None
    total_costs_paid_usdc: float | None
    entry_costs_paid_usdc: float | None
    exit_costs_paid_usdc: float | None
    closed_trades: int | None
    open_positions: int | None
    decision_log_net_pnl_usdc: float | None
    decision_log_fees_usdc: float | None
    decision_log_events: int | None
    status: str

    @property
    def available(self) -> bool:
        return self.source_path is not None and self.net_pnl_usdc is not None


@dataclass(frozen=True, slots=True)
class ExportState:
    source_path: Path | None
    updated_at_ms: int | None
    exported_event_keys_count: int | None
    status: str


@dataclass(frozen=True, slots=True)
class V19NegativePnlAudit:
    log_dir: Path
    source_files: tuple[str, ...]
    total_decisions: int
    accepted: int
    refused: int
    positive_events: int
    negative_events: int
    net_pnl_usdc: float
    pnl_truth_mode: str
    session_portfolio_net_pnl_usdc: float | None
    decision_log_net_pnl_usdc: float
    snapshot_net_pnl_usdc: float | None
    snapshot_decision_log_net_pnl_usdc: float | None
    snapshot_decision_log_fees_usdc: float | None
    snapshot_decision_log_events: int | None
    pnl_divergence_usdc: float | None
    snapshot_current_equity_usdt: float | None
    snapshot_starting_equity_usdt: float | None
    snapshot_realized_pnl_usdc: float | None
    snapshot_unrealized_pnl_usdc: float | None
    snapshot_total_costs_paid_usdc: float | None
    snapshot_closed_trades: int | None
    snapshot_open_positions: int | None
    snapshot_status: str
    gross_pnl_usdc: float
    fees_usdc: float
    fee_drag_ratio: float
    winrate: float
    profit_factor_net: float
    consecutive_losses: int
    max_consecutive_losses: int
    edge_sentinel_count: int
    edge_negative_count: int
    edge_positive_count: int
    orphan_close_count: int
    add_without_open_count: int
    top_refusal_reasons: tuple[tuple[str, int], ...]
    losing_coins: tuple[LossBucket, ...]
    losing_wallets: tuple[LossBucket, ...]
    losing_actions: tuple[LossBucket, ...]
    losing_reasons: tuple[LossBucket, ...]
    recommendations: tuple[str, ...]
    risk_decision: V19RiskDecision
    strategy_best_name: str
    strategy_protection_recommended: bool
    export_state_source_path: str | None
    export_state_updated_at_ms: int | None
    exported_event_keys_count: int | None
    latest_source_age_seconds: float | None = None
    pnl_reliability_status: str = "UNKNOWN"
    pnl_reliability_findings: tuple[str, ...] = ()
    strategy_summary: dict[str, Any] = field(default_factory=dict)


def build_negative_pnl_audit(log_dir: Path | None = None) -> V19NegativePnlAudit:
    effective_log_dir = log_dir or default_logs_to_send_dir()
    prefer_append_only = os.environ.get("HYPERSMART_PNL_AUDIT_PREFER_APPEND_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    metrics = analyze_logs_streaming(effective_log_dir, prefer_append_only=prefer_append_only)
    tournament = run_strategy_tournament(effective_log_dir)
    snapshot = _load_snapshot_pnl(effective_log_dir)
    export_state = _load_export_state(effective_log_dir)
    effective_net_pnl_usdc, pnl_truth_mode = _effective_net_pnl_and_mode(metrics, snapshot)
    effective_fees_usdc = _effective_fees(metrics, snapshot)
    effective_fee_drag_ratio = _effective_fee_drag_ratio(metrics, snapshot, effective_net_pnl_usdc, effective_fees_usdc)
    fallback_prefix = "DECISION_LOG_CACHE" if pnl_truth_mode == "snapshot_embedded_decision_log" else "SESSION_PORTFOLIO"
    losing_coins = _effective_fallback_buckets(
        _to_buckets(metrics.pnl_by_coin), effective_net_pnl_usdc, f"{fallback_prefix}_UNATTRIBUTED_COIN"
    )
    losing_wallets = _effective_fallback_buckets(
        _to_buckets(metrics.pnl_by_wallet), effective_net_pnl_usdc, f"{fallback_prefix}_UNATTRIBUTED_WALLET"
    )
    losing_actions = _effective_fallback_buckets(
        _to_buckets(metrics.pnl_by_action), effective_net_pnl_usdc, f"{fallback_prefix}_UNATTRIBUTED_ACTION"
    )
    losing_reasons = _effective_fallback_buckets(
        _to_buckets(metrics.pnl_by_reason), effective_net_pnl_usdc, f"{fallback_prefix}_SNAPSHOT_DIVERGENCE"
    )
    pnl_divergence = _pnl_divergence(snapshot, metrics)
    latest_source_age_seconds = _latest_source_age_seconds(metrics, snapshot, export_state)
    reliability_status, reliability_findings = _pnl_reliability(
        latest_source_age_seconds=latest_source_age_seconds,
        pnl_divergence=pnl_divergence,
        snapshot=snapshot,
        metrics=metrics,
    )
    decision = evaluate_v19_risk_gates(
        net_pnl_usdc=effective_net_pnl_usdc,
        total_decisions=metrics.total_decisions,
        accepted=metrics.accepted,
        negative_events=metrics.negative_events,
        positive_events=metrics.positive_events,
        fee_drag_ratio=effective_fee_drag_ratio,
        stale_reason_count=metrics.reasons["STALE_SIGNAL"]
        + metrics.reasons["REJECT_TOO_LATE"]
        + metrics.reasons["opportunity stale signal"]
        + metrics.reasons["entry deltas too old for copy"],
        edge_negative_count=metrics.edge_negative_count,
        edge_sentinel_count=metrics.edge_sentinel_count,
        orphan_close_count=metrics.orphan_close_count,
        profit_factor_net=metrics.profit_factor_net,
        consecutive_losses=metrics.consecutive_losses,
        strategy_protection_recommended=tournament.protection_mode_recommended,
        top_losing_coins=tuple((item.key, item.pnl_usdc) for item in losing_coins[:10]),
        top_losing_wallets=tuple((item.key, item.pnl_usdc) for item in losing_wallets[:10]),
    )
    return V19NegativePnlAudit(
        log_dir=effective_log_dir,
        source_files=tuple(str(path) for path in metrics.source_files),
        total_decisions=metrics.total_decisions,
        accepted=metrics.accepted,
        refused=metrics.refused,
        positive_events=metrics.positive_events,
        negative_events=metrics.negative_events,
        net_pnl_usdc=round(effective_net_pnl_usdc, 8),
        pnl_truth_mode=pnl_truth_mode,
        session_portfolio_net_pnl_usdc=_round_optional(snapshot.net_pnl_usdc),
        decision_log_net_pnl_usdc=round(metrics.net_pnl_usdc, 8),
        snapshot_net_pnl_usdc=_round_optional(snapshot.net_pnl_usdc),
        snapshot_decision_log_net_pnl_usdc=_round_optional(snapshot.decision_log_net_pnl_usdc),
        snapshot_decision_log_fees_usdc=_round_optional(snapshot.decision_log_fees_usdc),
        snapshot_decision_log_events=snapshot.decision_log_events,
        pnl_divergence_usdc=_round_optional(pnl_divergence),
        snapshot_current_equity_usdt=_round_optional(snapshot.current_equity_usdt),
        snapshot_starting_equity_usdt=_round_optional(snapshot.starting_equity_usdt),
        snapshot_realized_pnl_usdc=_round_optional(snapshot.realized_pnl_usdc),
        snapshot_unrealized_pnl_usdc=_round_optional(snapshot.unrealized_pnl_usdc),
        snapshot_total_costs_paid_usdc=_round_optional(snapshot.total_costs_paid_usdc),
        snapshot_closed_trades=snapshot.closed_trades,
        snapshot_open_positions=snapshot.open_positions,
        snapshot_status=snapshot.status,
        gross_pnl_usdc=round(metrics.gross_pnl_usdc, 8),
        fees_usdc=round(effective_fees_usdc, 8),
        fee_drag_ratio=effective_fee_drag_ratio,
        winrate=metrics.net_winrate,
        profit_factor_net=metrics.profit_factor_net,
        consecutive_losses=metrics.consecutive_losses,
        max_consecutive_losses=metrics.max_consecutive_losses,
        edge_sentinel_count=metrics.edge_sentinel_count,
        edge_negative_count=metrics.edge_negative_count,
        edge_positive_count=metrics.edge_positive_count,
        orphan_close_count=metrics.orphan_close_count,
        add_without_open_count=metrics.add_without_open_count,
        top_refusal_reasons=tuple(metrics.reasons.most_common(20)),
        losing_coins=losing_coins,
        losing_wallets=losing_wallets,
        losing_actions=losing_actions,
        losing_reasons=losing_reasons,
        recommendations=tuple(_build_v19_recommendations(metrics, snapshot, effective_net_pnl_usdc)),
        risk_decision=decision,
        strategy_best_name=tournament.best.config.name,
        strategy_protection_recommended=tournament.protection_mode_recommended,
        export_state_source_path=str(export_state.source_path) if export_state.source_path else None,
        export_state_updated_at_ms=export_state.updated_at_ms,
        exported_event_keys_count=export_state.exported_event_keys_count,
        latest_source_age_seconds=_round_optional(latest_source_age_seconds),
        pnl_reliability_status=reliability_status,
        pnl_reliability_findings=tuple(reliability_findings),
        strategy_summary=_strategy_summary(tournament),
    )


def audit_to_dict(audit: V19NegativePnlAudit) -> dict[str, Any]:
    return {
        "log_dir": str(audit.log_dir),
        "source_files": list(audit.source_files),
        "total_decisions": audit.total_decisions,
        "accepted": audit.accepted,
        "refused": audit.refused,
        "positive_events": audit.positive_events,
        "negative_events": audit.negative_events,
        "net_pnl_usdc": audit.net_pnl_usdc,
        "pnl_truth_mode": audit.pnl_truth_mode,
        "session_portfolio_net_pnl_usdc": audit.session_portfolio_net_pnl_usdc,
        "decision_log_net_pnl_usdc": audit.decision_log_net_pnl_usdc,
        "snapshot_net_pnl_usdc": audit.snapshot_net_pnl_usdc,
        "snapshot_decision_log_net_pnl_usdc": audit.snapshot_decision_log_net_pnl_usdc,
        "snapshot_decision_log_fees_usdc": audit.snapshot_decision_log_fees_usdc,
        "snapshot_decision_log_events": audit.snapshot_decision_log_events,
        "pnl_divergence_usdc": audit.pnl_divergence_usdc,
        "snapshot_current_equity_usdt": audit.snapshot_current_equity_usdt,
        "snapshot_starting_equity_usdt": audit.snapshot_starting_equity_usdt,
        "snapshot_realized_pnl_usdc": audit.snapshot_realized_pnl_usdc,
        "snapshot_unrealized_pnl_usdc": audit.snapshot_unrealized_pnl_usdc,
        "snapshot_total_costs_paid_usdc": audit.snapshot_total_costs_paid_usdc,
        "snapshot_closed_trades": audit.snapshot_closed_trades,
        "snapshot_open_positions": audit.snapshot_open_positions,
        "snapshot_status": audit.snapshot_status,
        "gross_pnl_usdc": audit.gross_pnl_usdc,
        "fees_usdc": audit.fees_usdc,
        "fee_drag_ratio": audit.fee_drag_ratio,
        "winrate": audit.winrate,
        "profit_factor_net": audit.profit_factor_net,
        "consecutive_losses": audit.consecutive_losses,
        "max_consecutive_losses": audit.max_consecutive_losses,
        "edge_sentinel_count": audit.edge_sentinel_count,
        "edge_negative_count": audit.edge_negative_count,
        "edge_positive_count": audit.edge_positive_count,
        "orphan_close_count": audit.orphan_close_count,
        "add_without_open_count": audit.add_without_open_count,
        "top_refusal_reasons": list(audit.top_refusal_reasons),
        "losing_coins": [asdict(item) for item in audit.losing_coins],
        "losing_wallets": [asdict(item) for item in audit.losing_wallets],
        "losing_actions": [asdict(item) for item in audit.losing_actions],
        "losing_reasons": [asdict(item) for item in audit.losing_reasons],
        "recommendations": list(audit.recommendations),
        "risk_decision": decision_to_dict(audit.risk_decision),
        "quarantine_suggestions": quarantine_suggestions_from_breakdowns(
            {item.key: item.pnl_usdc for item in audit.losing_coins},
            {item.key: item.pnl_usdc for item in audit.losing_wallets},
            {item.key: item.pnl_usdc for item in audit.losing_actions},
        ),
        "strategy_best_name": audit.strategy_best_name,
        "strategy_protection_recommended": audit.strategy_protection_recommended,
        "export_state_source_path": audit.export_state_source_path,
        "export_state_updated_at_ms": audit.export_state_updated_at_ms,
        "exported_event_keys_count": audit.exported_event_keys_count,
        "latest_source_age_seconds": audit.latest_source_age_seconds,
        "pnl_reliability_status": audit.pnl_reliability_status,
        "pnl_reliability_findings": list(audit.pnl_reliability_findings),
        "strategy_summary": audit.strategy_summary,
        "paper_only": True,
        "real_execution": False,
        "future_profit_guarantee": False,
    }


def write_negative_pnl_audit(audit: V19NegativePnlAudit, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "hypersmart_v19_negative_pnl_audit.json"
    md_path = output_dir / "HYPERSMART_V19_NEGATIVE_PNL_AUDIT.md"
    json_path.write_text(json.dumps(audit_to_dict(audit), indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(format_negative_pnl_audit(audit), encoding="utf-8")
    return json_path, md_path


def format_negative_pnl_audit(audit: V19NegativePnlAudit) -> str:
    lines = [
        "# HyperSmart V19 - audit PnL negatif",
        "",
        "Scope: simulation locale paper, lecture seule, aucune action externe reelle.",
        "",
        "## Resume",
        "",
        f"- Logs: `{audit.log_dir}`",
        f"- Decisions analysees: {audit.total_decisions}",
        f"- Acceptees: {audit.accepted}",
        f"- Refusees: {audit.refused}",
        f"- PnL net paper effectif: {audit.net_pnl_usdc:.6f} USDC",
        f"- Mode verite PnL: {audit.pnl_truth_mode}",
        f"- PnL portefeuille session: {_format_optional(audit.session_portfolio_net_pnl_usdc)} USDC",
        f"- PnL net des logs decision: {audit.decision_log_net_pnl_usdc:.6f} USDC",
        f"- PnL net snapshot session: {_format_optional(audit.snapshot_net_pnl_usdc)} USDC",
        f"- PnL decision log embarque snapshot: {_format_optional(audit.snapshot_decision_log_net_pnl_usdc)} USDC",
        f"- Divergence equity apres latent: {_format_optional(audit.pnl_divergence_usdc)} USDC",
        f"- Equity snapshot: {_format_optional(audit.snapshot_current_equity_usdt)} USDT",
        f"- Trades fermes snapshot: {audit.snapshot_closed_trades if audit.snapshot_closed_trades is not None else 'absent'}",
        f"- Positions ouvertes snapshot: {audit.snapshot_open_positions if audit.snapshot_open_positions is not None else 'absent'}",
        f"- Statut snapshot: {audit.snapshot_status}",
        f"- PnL brut paper: {audit.gross_pnl_usdc:.6f} USDC",
        f"- Frais: {audit.fees_usdc:.6f} USDC",
        f"- Fee drag ratio: {audit.fee_drag_ratio:.6f}",
        f"- Winrate evenementiel: {audit.winrate:.6f}",
        f"- Profit factor net: {audit.profit_factor_net:.6f}",
        f"- Pertes consecutives actuelles: {audit.consecutive_losses}",
        f"- Pire serie de pertes: {audit.max_consecutive_losses}",
        f"- Protection mode: {str(audit.risk_decision.protection_mode).lower()}",
        f"- Strategy tournament best: {audit.strategy_best_name}",
        f"- Export state updated_at_ms: {audit.export_state_updated_at_ms if audit.export_state_updated_at_ms is not None else 'absent'}",
        f"- Exported event keys: {audit.exported_event_keys_count if audit.exported_event_keys_count is not None else 'absent'}",
        f"- Fraicheur derniere source: {_format_optional(audit.latest_source_age_seconds)} secondes",
        f"- Fiabilite PnL: {audit.pnl_reliability_status}",
        "",
        "## Fiabilite du PnL",
        "",
    ]
    if audit.pnl_reliability_findings:
        lines.extend(f"- {item}" for item in audit.pnl_reliability_findings)
    else:
        lines.append("- OK: snapshot, logs et fraicheur ne montrent pas de divergence bloquante.")
    lines.extend([
        "",
        "## Perte par coin",
        "",
    ])
    lines.extend(_format_buckets(audit.losing_coins))
    lines.extend(["", "## Perte par wallet", ""])
    lines.extend(_format_buckets(audit.losing_wallets))
    lines.extend(["", "## Perte par action/strategie", ""])
    lines.extend(_format_buckets(audit.losing_actions))
    lines.extend(["", "## Perte/refus par raison", ""])
    lines.extend(_format_buckets(audit.losing_reasons))
    lines.extend(["", "## Top raisons de refus", ""])
    lines.extend(f"- {reason}: {count}" for reason, count in audit.top_refusal_reasons[:20])
    lines.extend(["", "## RiskEngine V19", "", "```text", format_v19_risk_decision(audit.risk_decision), "```"])
    lines.extend(["", "## Recommandations", ""])
    lines.extend(f"- {item}" for item in audit.recommendations)
    lines.extend(
        [
            "",
            "## Verites de securite",
            "",
            "- real_execution=false",
            "- paper_simulation_only=true",
            "- no_private_key=true",
            "- no_external_order=true",
            "- future_profit_guarantee=false",
        ]
    )
    return "\n".join(lines)


def _to_buckets(values: Mapping[str, float], *, limit: int = 20) -> tuple[LossBucket, ...]:
    ranked = sorted(((key, float(value)) for key, value in values.items() if value < 0), key=lambda item: item[1])
    return tuple(LossBucket(key=key, pnl_usdc=round(value, 8)) for key, value in ranked[:limit])


def _rank_negative(values: Mapping[str, float], *, limit: int = 10) -> tuple[tuple[str, float], ...]:
    return tuple((item.key, item.pnl_usdc) for item in _to_buckets(values, limit=limit))


def _snapshot_fallback_buckets(items: tuple[LossBucket, ...], snapshot: SnapshotPnL, key: str) -> tuple[LossBucket, ...]:
    if items or snapshot.net_pnl_usdc is None or snapshot.net_pnl_usdc >= 0:
        return items
    return (LossBucket(key=key, pnl_usdc=round(float(snapshot.net_pnl_usdc), 8)),)


def _effective_fallback_buckets(items: tuple[LossBucket, ...], effective_net_pnl_usdc: float, key: str) -> tuple[LossBucket, ...]:
    if items or effective_net_pnl_usdc >= 0:
        return items
    return (LossBucket(key=key, pnl_usdc=round(float(effective_net_pnl_usdc), 8)),)


def _format_buckets(items: tuple[LossBucket, ...]) -> list[str]:
    if not items:
        return ["- Aucun bucket perdant detecte dans les logs lus."]
    return [f"- {item.key}: {item.pnl_usdc:.6f} USDC" for item in items]


def _load_snapshot_pnl(log_dir: Path) -> SnapshotPnL:
    path = log_dir / "simulation_snapshot_latest.json"
    if not path.exists():
        return _empty_snapshot("missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return SnapshotPnL(
            source_path=path,
            starting_equity_usdt=None,
            current_equity_usdt=None,
            net_pnl_usdc=None,
            realized_pnl_usdc=None,
            unrealized_pnl_usdc=None,
            total_costs_paid_usdc=None,
            entry_costs_paid_usdc=None,
            exit_costs_paid_usdc=None,
            closed_trades=None,
            open_positions=None,
            decision_log_net_pnl_usdc=None,
            decision_log_fees_usdc=None,
            decision_log_events=None,
            status=f"unreadable:{exc.__class__.__name__}",
        )
    if not isinstance(payload, dict):
        return SnapshotPnL(
            source_path=path,
            starting_equity_usdt=None,
            current_equity_usdt=None,
            net_pnl_usdc=None,
            realized_pnl_usdc=None,
            unrealized_pnl_usdc=None,
            total_costs_paid_usdc=None,
            entry_costs_paid_usdc=None,
            exit_costs_paid_usdc=None,
            closed_trades=None,
            open_positions=None,
            decision_log_net_pnl_usdc=None,
            decision_log_fees_usdc=None,
            decision_log_events=None,
            status="invalid_payload",
        )
    bot = _dict(payload.get("bot_simulation"))
    equity = _dict(payload.get("equity"))
    starting = _first_number(
        bot.get("starting_equity_usdt"),
        equity.get("starting_equity_usdt"),
        payload.get("starting_equity_usdt"),
    )
    current = _first_number(
        bot.get("current_equity_usdt"),
        equity.get("current_equity_usdt"),
        bot.get("free_equity_usdt"),
        equity.get("free_equity_usdt"),
    )
    net = _first_number(
        bot.get("estimated_net_pnl_usdc"),
        bot.get("realized_net_pnl_usdc"),
        equity.get("bot_net_pnl_usdc"),
        equity.get("current_pnl_usdc"),
        equity.get("realized_pnl_usdc"),
    )
    if net is None and current is not None and starting is not None:
        net = current - starting
    return SnapshotPnL(
        source_path=path,
        starting_equity_usdt=starting,
        current_equity_usdt=current,
        net_pnl_usdc=net,
        realized_pnl_usdc=_first_number(bot.get("realized_net_pnl_usdc"), equity.get("realized_pnl_usdc")),
        unrealized_pnl_usdc=_first_number(bot.get("unrealized_pnl_usdc"), equity.get("unrealized_pnl_usdc")),
        total_costs_paid_usdc=_first_number(bot.get("total_costs_paid_usdc"), equity.get("bot_costs_paid_usdc")),
        entry_costs_paid_usdc=_first_number(bot.get("entry_costs_paid_usdc")),
        exit_costs_paid_usdc=_first_number(bot.get("exit_costs_paid_usdc")),
        closed_trades=_first_int(bot.get("closed_trades")),
        open_positions=_first_int(bot.get("open_local_positions"), len(bot.get("open_positions") or []) if isinstance(bot.get("open_positions"), list) else None),
        decision_log_net_pnl_usdc=_first_number(
            _dict(payload.get("decision_log_pnl")).get("closed_log_event_pnl_usdc"),
            equity.get("decision_log_total_pnl_usdc"),
        ),
        decision_log_fees_usdc=_first_number(_dict(payload.get("decision_log_pnl")).get("fees_usdc")),
        decision_log_events=_first_int(_dict(payload.get("decision_log_pnl")).get("events"), equity.get("decision_log_events")),
        status="ok",
    )


def _empty_snapshot(status: str) -> SnapshotPnL:
    return SnapshotPnL(
        source_path=None,
        starting_equity_usdt=None,
        current_equity_usdt=None,
        net_pnl_usdc=None,
        realized_pnl_usdc=None,
        unrealized_pnl_usdc=None,
        total_costs_paid_usdc=None,
        entry_costs_paid_usdc=None,
        exit_costs_paid_usdc=None,
        closed_trades=None,
        open_positions=None,
        decision_log_net_pnl_usdc=None,
        decision_log_fees_usdc=None,
        decision_log_events=None,
        status=status,
    )


def _load_export_state(log_dir: Path) -> ExportState:
    path = log_dir / "simulation_export_state.json"
    if not path.exists():
        return ExportState(source_path=None, updated_at_ms=None, exported_event_keys_count=None, status="missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return ExportState(source_path=path, updated_at_ms=None, exported_event_keys_count=None, status=f"unreadable:{exc.__class__.__name__}")
    if not isinstance(payload, dict):
        return ExportState(source_path=path, updated_at_ms=None, exported_event_keys_count=None, status="invalid_payload")
    event_keys = payload.get("exported_event_keys")
    return ExportState(
        source_path=path,
        updated_at_ms=_first_int(payload.get("updated_at_ms")),
        exported_event_keys_count=len(event_keys) if isinstance(event_keys, list) else None,
        status="ok",
    )


def _effective_net_pnl_and_mode(metrics: LogMetricsReport, snapshot: SnapshotPnL) -> tuple[float, str]:
    if snapshot.net_pnl_usdc is not None and abs(float(snapshot.net_pnl_usdc)) > 1e-12:
        return float(snapshot.net_pnl_usdc), "session_portfolio_snapshot"
    if snapshot.decision_log_net_pnl_usdc is not None and abs(float(snapshot.decision_log_net_pnl_usdc)) > 1e-12:
        return float(snapshot.decision_log_net_pnl_usdc), "snapshot_embedded_decision_log"
    if abs(float(metrics.net_pnl_usdc)) > 1e-12:
        return float(metrics.net_pnl_usdc), "decision_log_files"
    if snapshot.net_pnl_usdc is not None:
        return float(snapshot.net_pnl_usdc), "session_portfolio_snapshot_zero"
    return float(metrics.net_pnl_usdc), "decision_log_files_zero"


def _effective_fees(metrics: LogMetricsReport, snapshot: SnapshotPnL) -> float:
    if snapshot.decision_log_fees_usdc is not None and abs(metrics.fees_usdc) <= 1e-12:
        return float(snapshot.decision_log_fees_usdc)
    if snapshot.total_costs_paid_usdc is not None and abs(metrics.fees_usdc) <= 1e-12:
        return float(snapshot.total_costs_paid_usdc)
    if snapshot.total_costs_paid_usdc is not None:
        return max(float(metrics.fees_usdc), float(snapshot.total_costs_paid_usdc))
    if snapshot.decision_log_fees_usdc is not None:
        return max(float(metrics.fees_usdc), float(snapshot.decision_log_fees_usdc))
    return float(metrics.fees_usdc)


def _effective_fee_drag_ratio(
    metrics: LogMetricsReport,
    snapshot: SnapshotPnL,
    effective_net_pnl_usdc: float,
    effective_fees_usdc: float,
) -> float:
    ratios = [float(metrics.fee_drag_ratio)]
    if snapshot.total_costs_paid_usdc is not None:
        denominator = max(abs(effective_net_pnl_usdc), abs(metrics.gross_pnl_usdc), abs(effective_fees_usdc), 1e-9)
        ratios.append(float(snapshot.total_costs_paid_usdc) / denominator)
    if snapshot.decision_log_fees_usdc is not None:
        denominator = max(abs(effective_net_pnl_usdc), abs(metrics.gross_pnl_usdc), abs(effective_fees_usdc), 1e-9)
        ratios.append(float(snapshot.decision_log_fees_usdc) / denominator)
    return round(max(ratios), 8)


def _pnl_divergence(snapshot: SnapshotPnL, metrics: LogMetricsReport) -> float | None:
    if snapshot.net_pnl_usdc is None:
        return None
    candidates: list[float] = []
    if snapshot.decision_log_net_pnl_usdc is not None:
        candidates.append(float(snapshot.decision_log_net_pnl_usdc))
    if abs(float(metrics.net_pnl_usdc)) > 1e-12:
        candidates.append(float(metrics.net_pnl_usdc))
    if not candidates:
        return None
    # Decision logs mostly represent realized/closed events. A live portfolio
    # snapshot also includes unrealized mark-to-market PnL. Treat that latent
    # component as expected, and prefer the decision source that best reconciles
    # the portfolio. This handles the normal case where latest.jsonl is a rolling
    # window while append_only.jsonl still contains the full session ledger.
    def gap(decision_net: float) -> float:
        expected_portfolio_net = float(decision_net)
        if snapshot.unrealized_pnl_usdc is not None:
            expected_portfolio_net += float(snapshot.unrealized_pnl_usdc)
        return float(snapshot.net_pnl_usdc) - expected_portfolio_net

    return min((gap(candidate) for candidate in candidates), key=lambda value: abs(value))


def _latest_source_age_seconds(
    metrics: LogMetricsReport,
    snapshot: SnapshotPnL,
    export_state: ExportState,
) -> float | None:
    paths: list[Path] = []
    paths.extend(metrics.source_files)
    if snapshot.source_path is not None:
        paths.append(snapshot.source_path)
    if export_state.source_path is not None:
        paths.append(export_state.source_path)
    mtimes: list[float] = []
    for path in paths:
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return None
    return max(0.0, time.time() - max(mtimes))


def _pnl_reliability(
    *,
    latest_source_age_seconds: float | None,
    pnl_divergence: float | None,
    snapshot: SnapshotPnL,
    metrics: LogMetricsReport,
) -> tuple[str, list[str]]:
    findings: list[str] = []
    stale = latest_source_age_seconds is None or latest_source_age_seconds > 60.0
    divergence_threshold = _pnl_divergence_tolerance_usdc(snapshot)
    divergent = pnl_divergence is not None and abs(float(pnl_divergence)) > divergence_threshold
    auxiliary_history = _decision_history_is_auxiliary(metrics)
    if stale:
        if latest_source_age_seconds is None:
            findings.append("STALE_OR_MISSING_INPUTS: aucune source recente ne permet de valider le PnL courant.")
        else:
            findings.append(
                f"STALE_INPUTS: derniere source agee de {latest_source_age_seconds:.1f}s; relancer le launcher avant de conclure sur le PnL."
            )
    if divergent:
        if snapshot.available and auxiliary_history:
            findings.append(
                f"AUXILIARY_DECISION_LOG_MISMATCH: le snapshot portefeuille actif est utilise comme verite PnL; les logs de decisions sont volumineux ou multi-session et divergent de {float(pnl_divergence):.6f} USDC (tolerance {divergence_threshold:.4f})."
            )
            divergent = False
        else:
            findings.append(
                f"DIVERGENT_PNL: snapshot portefeuille et logs de decisions, apres prise en compte du latent ouvert, divergent de {float(pnl_divergence):.6f} USDC (tolerance {divergence_threshold:.4f})."
            )
    if snapshot.available and metrics.total_decisions == 0:
        findings.append("SNAPSHOT_ONLY: le portefeuille existe mais aucun log decision n'a ete analyse.")
    if not snapshot.available and metrics.total_decisions == 0:
        findings.append("NO_PNL_EVIDENCE: ni snapshot portefeuille ni decisions exploitables.")
    if stale and divergent:
        return "STALE_AND_DIVERGENT", findings
    if divergent:
        return "DIVERGENT", findings
    if stale:
        return "STALE", findings
    if findings:
        return "DEGRADED", findings
    return "OK", findings


def _build_v19_recommendations(
    metrics: LogMetricsReport,
    snapshot: SnapshotPnL,
    effective_net_pnl_usdc: float,
) -> list[str]:
    recommendations = list(build_recommendations(metrics))
    pnl_divergence = _pnl_divergence(snapshot, metrics)
    if (
        snapshot.available
        and pnl_divergence is not None
        and abs(float(pnl_divergence)) > _pnl_divergence_tolerance_usdc(snapshot)
    ):
        if _decision_history_is_auxiliary(metrics):
            recommendations.append(
                "PnL courant: utiliser le snapshot portefeuille comme source de verite; les logs de decisions volumineux restent utiles pour l'attribution des pertes, mais ne doivent pas ecraser la session active."
            )
        else:
            recommendations.append(
                "Reconciliation obligatoire: le snapshot portefeuille diverge des logs de decisions meme apres prise en compte du latent ouvert. Utiliser le snapshot comme source PnL session et corriger l'export des trades fermes."
            )
    if metrics.accepted == 0 and metrics.total_decisions > 0:
        recommendations.append(
            "Le moteur ne demarre pas car toutes les entrees sont refusees: ameliorer fraicheur/source/liquidite avant de desserrer le risque."
        )
    total = max(1, metrics.total_decisions)
    if metrics.reasons["LIQUIDITY_TOO_LOW"] / total > 0.30:
        recommendations.append(
            "La liquidite bloque trop de signaux: prioriser les marches profonds, rejeter les micro-coins et recalculer depth/spread avant toute entree paper."
        )
    if metrics.reasons["SINGLE_WALLET_EDGE_TOO_LOW"] / total > 0.25:
        recommendations.append(
            "Les signaux mono-wallet sont trop faibles: exiger cluster/consensus frais ou leader exceptionnel avant sizing paper."
        )
    if metrics.reasons["EDGE_REMAINING_TOO_LOW"] / total > 0.30:
        recommendations.append(
            "Edge restant insuffisant: recalibrer expected edge apres couts, augmenter min_edge et tracer chaque composant cout/retard dans evidence_chain."
        )
    stale_count = (
        metrics.reasons["STALE_SIGNAL"]
        + metrics.reasons["REJECT_TOO_LATE"]
        + metrics.reasons["opportunity stale signal"]
        + metrics.reasons["entry deltas too old for copy"]
    )
    if stale_count / total > 0.10:
        recommendations.append(
            "Fraicheur insuffisante: renforcer WS read-only, timestamps de reception, discard apres age court, et ne pas recycler d'anciens deltas."
        )
    if effective_net_pnl_usdc < 0 and snapshot.total_costs_paid_usdc and snapshot.total_costs_paid_usdc > abs(effective_net_pnl_usdc) * 0.20:
        recommendations.append(
            "Les couts sont significatifs face au PnL: appliquer min edge net plus strict, TP/SL paper apres couts et cooldown apres trade perdant."
        )
    deduped = _dedupe(recommendations)
    if len(deduped) > 1:
        deduped = [item for item in deduped if not item.startswith("Continuer la collecte:")]
    return deduped


def _strategy_summary(report: OptimizationReport) -> dict[str, Any]:
    return {
        "best_config": report.best.config.name,
        "best_train_pnl_usdc": report.best.train_pnl_usdc,
        "best_validation_pnl_usdc": report.best.validation_pnl_usdc,
        "best_holdout_pnl_usdc": report.best.holdout_pnl_usdc,
        "best_total_net_pnl_usdc": report.best.total_net_pnl_usdc,
        "best_selected_events": report.best.selected_events,
        "protection_mode_recommended": report.protection_mode_recommended,
        "selection_uses_holdout": False,
        "holdout_is_verification_only": True,
    }


def _pnl_divergence_tolerance_usdc(snapshot: SnapshotPnL) -> float:
    """Small live-export tolerance between snapshot and append-only logs.

    The dashboard writes portfolio snapshots, decision logs, and export-state
    files at slightly different instants. A few cents of difference can happen
    while an open position is being marked to market or after local exit costs
    are estimated. Larger gaps remain flagged as accounting bugs.
    """

    open_positions = max(0, int(snapshot.open_positions or 0))
    return max(0.05, 0.02 * open_positions)


def _decision_history_is_auxiliary(metrics: LogMetricsReport) -> bool:
    """Return true when decision logs are too large to be a single live PnL truth.

    The launcher keeps an append-only forensic trail for debugging. On long runs
    that file can span multiple UI snapshots or even previous attempts before a
    non-destructive rotation. It must still be analyzed for loss attribution, but
    it should not override a fresh portfolio snapshot in the PnL truth chain.
    """

    try:
        decisions_threshold = int(float(os.getenv("HYPERSMART_PNL_AUDIT_HISTORY_DECISIONS_AUX_THRESHOLD", "50000")))
    except ValueError:
        decisions_threshold = 50000
    if metrics.total_decisions >= max(1, decisions_threshold):
        return True

    try:
        bytes_threshold = int(float(os.getenv("HYPERSMART_PNL_AUDIT_HISTORY_BYTES_AUX_THRESHOLD", str(200 * 1024 * 1024))))
    except ValueError:
        bytes_threshold = 200 * 1024 * 1024
    for path in metrics.source_files:
        try:
            if path.stat().st_size >= max(1, bytes_threshold):
                return True
        except OSError:
            continue
    return False


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _round_optional(value: float | None) -> float | None:
    return None if value is None else round(float(value), 8)


def _format_optional(value: float | None) -> str:
    return "absent" if value is None else f"{value:.6f}"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
