from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

try:  # Python 3.11+
    from datetime import UTC
except ImportError:  # Python 3.10 compat
    UTC = timezone.utc
import json
from pathlib import Path
from typing import Any

from hl_observer.arbitrage.dual_venue_hedge_sim import simulate_dual_venue_hedge
from hl_observer.arbitrage.triangular_graph import TriangularEdge, build_triangular_cycles
from hl_observer.arbitrage.triangular_opportunity_detector import detect_triangular_opportunities
from hl_observer.arbitrage.ws_price_discrepancy_detector import detect_ws_price_discrepancies
from hl_observer.analysis.negative_pnl_auditor import (
    V19NegativePnlAudit,
    audit_to_dict,
    build_negative_pnl_audit,
)
from hl_observer.arbitrage.hyperliquid_cex_spread_scanner import (
    CrossExchangeOpportunity,
    scan_hyperliquid_cex_spread,
)
from hl_observer.arbitrage.orderbook_snapshot import OrderBookSnapshot
from hl_observer.backtesting.wallet_following_simulator import simulate_wallet_following
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote, resolve_copy_conflict
from hl_observer.copy_wallet.copy_latency_profiler import profile_copy_latency
from hl_observer.copy_wallet.copy_session_controller import start_copy_session
from hl_observer.copy_wallet.wallet_mirror_runtime import MirrorPipelineResult, run_wallet_mirror_pipeline
from hl_observer.connectors.paper_execution_connector import LocalPaperExecutionConnector
from hl_observer.connectors.standard import PaperOrderRequest
from hl_observer.dashboard.arbitrage_panel import build_arbitrage_panel
from hl_observer.dashboard.copy_wallet_panel import build_copy_wallet_panel
from hl_observer.dashboard.funding_panel import build_funding_panel
from hl_observer.dashboard.loss_attribution_panel import build_loss_attribution_panel
from hl_observer.dashboard.refactor_fusion_panel import build_refactor_fusion_dashboard_payload
from hl_observer.funding.funding_rate_scanner import scan_funding_rates
from hl_observer.risk.concentration_risk_detector import detect_concentration_risk
from hl_observer.risk.liquidity_cliff_detector import detect_liquidity_cliff
from hl_observer.risk.risk_engine_v3 import SessionEntryRiskContext
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.realtime.multi_source_price_stream import PriceEvent
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.strategies.fusion_runtime import FusionRuntimeInput, run_fusion_strategy_runtime


@dataclass(frozen=True, slots=True)
class RefactorFusionRunResult:
    dry_run: bool
    log_dir: Path
    json_path: Path
    dashboard_payload_path: Path
    markdown_path: Path
    audit: V19NegativePnlAudit
    wallet_results: tuple[MirrorPipelineResult, ...]
    arbitrage_results: tuple[CrossExchangeOpportunity, ...]
    dashboard_payload: dict[str, Any]

    @property
    def paper_intents_count(self) -> int:
        return sum(1 for item in self.wallet_results if item.paper_intent is not None)

    @property
    def arbitrage_accepted_count(self) -> int:
        return sum(1 for item in self.arbitrage_results if item.decision == "ACCEPT_PAPER_ARBITRAGE")


def run_refactor_fusion(
    *,
    log_dir: Path,
    dry_run: bool = True,
    output_data_dir: Path | None = None,
    output_docs_dir: Path | None = None,
) -> RefactorFusionRunResult:
    if not dry_run:
        raise ValueError("refactor-fusion-run is paper/dry-run only")
    data_dir = output_data_dir or Path("data") / "reports"
    docs_dir = output_docs_dir or Path("docs") / "reports"
    data_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)

    audit = build_negative_pnl_audit(log_dir)
    session_context = _session_context_from_audit(audit)
    wallet_results = (_fixture_wallet_mirror(log_dir, session_context=session_context),)
    arbitrage_results = (_fixture_arbitrage(),)
    conflict = resolve_copy_conflict(
        [
            LeaderVote(wallet="0x1111111111111111111111111111111111111111", coin="HYPE", side="LONG", score=2.0),
            LeaderVote(wallet="0x2222222222222222222222222222222222222222", coin="HYPE", side="LONG", score=1.2),
            LeaderVote(wallet="0x3333333333333333333333333333333333333333", coin="HYPE", side="SHORT", score=0.3),
        ]
    )
    liquidity_cliff = detect_liquidity_cliff(
        [{"notional_usdt": 6_000.0}, {"notional_usdt": 5_500.0}, {"notional_usdt": 4_000.0}, {"notional_usdt": 8_000.0}]
    )
    concentration = detect_concentration_risk([100_000.0, 80_000.0, 70_000.0])
    replay = simulate_wallet_following(
        [
            {
                "event_id": "fixture:replay:hype:1",
                "coin": "HYPE",
                "side": "LONG",
                "entry_price": 100.0,
                "exit_price": 101.2,
                "notional_usdt": 75.0,
            }
        ],
        fee_bps=4.0,
        slippage_bps=2.0,
    )
    hedge = simulate_dual_venue_hedge(long_leg_price=100.0, short_leg_price=101.2, net_edge_bps=65.0, min_edge_bps=10.0)
    copy_session = start_copy_session(
        "fixture:copy_session",
        watchlist=("0x1111111111111111111111111111111111111111", "0x2222222222222222222222222222222222222222"),
        copy_ratio=0.05,
    )
    latency_profile = profile_copy_latency([250, 900, 4_000, 6_200], stale_threshold_ms=5_000)
    paper_connector_result = LocalPaperExecutionConnector().submit_paper_order(PaperOrderRequest("HYPE", "LONG", 25.0))
    funding_signals = scan_funding_rates([{"coin": "HYPE", "rates": [0.0, 0.0, 0.0, 0.0, 0.001]}], sigma=2.0)
    price_discrepancies = detect_ws_price_discrepancies(
        [PriceEvent("hyperliquid_fixture", "HYPE", 100.0, 100.1, 1_000), PriceEvent("cex_fixture", "HYPE", 101.0, 101.1, 1_000)],
        min_spread_bps=20.0,
    )
    triangular_cycles = build_triangular_cycles(
        [
            TriangularEdge("USDC", "HYPE", 0.01),
            TriangularEdge("HYPE", "BTC", 0.001),
            TriangularEdge("BTC", "USDC", 101_500.0),
        ]
    )
    triangular = detect_triangular_opportunities(triangular_cycles, min_net_edge_bps=5.0)
    fusion_runtime = run_fusion_strategy_runtime(
        FusionRuntimeInput(
            session_id="fixture:fusion_runtime",
            leader_votes=(
                LeaderVote(wallet="0x1111111111111111111111111111111111111111", coin="HYPE", side="LONG", score=2.0),
                LeaderVote(wallet="0x2222222222222222222222222222222222222222", coin="HYPE", side="LONG", score=1.5),
                LeaderVote(wallet="0x3333333333333333333333333333333333333333", coin="HYPE", side="SHORT", score=0.2),
            ),
            price_events=(
                PriceEvent("hyperliquid_fixture", "HYPE", 100.0, 100.1, 1_000),
                PriceEvent("cex_fixture", "HYPE", 101.0, 101.1, 1_000),
                PriceEvent("hyperliquid_fixture", "BTC", 100_000.0, 100_010.0, 1_100),
            ),
            funding_rows=({"coin": "HYPE", "rates": [0.0, 0.0, 0.0, 0.0, 0.001]},),
            triangular_edges=(
                TriangularEdge("USDC", "HYPE", 0.01),
                TriangularEdge("HYPE", "BTC", 0.001),
                TriangularEdge("BTC", "USDC", 101_500.0),
            ),
            latencies_ms=(250, 900, 4_000, 6_200),
            peak_equity=1_000.0,
            current_equity=998.5,
        )
    )
    loss_panel = build_loss_attribution_panel(audit)
    copy_panel = build_copy_wallet_panel(list(wallet_results))
    arb_panel = build_arbitrage_panel(list(arbitrage_results))
    funding_panel = build_funding_panel(
        [
            {
                "source": "fixture:funding_placeholder",
                "status": "NO_TRADE",
                "reason": "FUNDING_LIVE_SOURCE_NOT_PROVIDED_IN_THIS_RUN",
                "paper_only": True,
                "real_execution": False,
            }
        ]
    )
    payload = build_refactor_fusion_dashboard_payload(
        loss_panel=loss_panel,
        copy_wallet_panel=copy_panel,
        arbitrage_panel=arb_panel,
        funding_panel=funding_panel,
        source_labels=[
            "logs:" + str(log_dir),
            "fixture:refactor_fusion_wallet_copy_e2e",
            "fixture:refactor_fusion_arbitrage_e2e",
            "fixture:fusion_runtime",
        ],
        extra_panels={"fusion_runtime": fusion_runtime.as_dict()},
    )
    result_payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dry_run": True,
        "audit": audit_to_dict(audit),
        "wallet_copy": [item.as_dict() for item in wallet_results],
        "arbitrage": [item.as_dict() for item in arbitrage_results],
        "multi_leader_conflict": {
            "coin": conflict.coin,
            "decision": conflict.decision,
            "winning_side": conflict.winning_side,
            "long_score": conflict.long_score,
            "short_score": conflict.short_score,
            "reasons": list(conflict.reasons),
        },
        "risk_flags": {
            "liquidity_cliff": {
                "blocked": liquidity_cliff.blocked,
                "reason": liquidity_cliff.reason,
                "near_depth_usdt": liquidity_cliff.near_depth_usdt,
                "far_depth_usdt": liquidity_cliff.far_depth_usdt,
                "cliff_ratio": liquidity_cliff.cliff_ratio,
            },
            "concentration": {
                "blocked": concentration.blocked,
                "reason": concentration.reason,
                "top_wallet_share": concentration.top_wallet_share,
            },
        },
        "replay_backtest": {
            "net_pnl_usdt": replay.net_pnl_usdt,
            "equity_curve": list(replay.equity_curve),
            "trade_count": len(replay.trades),
        },
        "dual_venue_hedge": {
            "accepted": hedge.accepted,
            "reason": hedge.reason,
            "net_edge_bps": hedge.net_edge_bps,
            "paper_only": hedge.paper_only,
            "real_execution": hedge.real_execution,
        },
        "copy_session": {
            "session_id": copy_session.session_id,
            "status": copy_session.status,
            "watchlist_count": len(copy_session.watchlist),
            "copy_ratio": copy_session.copy_ratio,
            "paper_only": copy_session.paper_only,
            "real_execution": copy_session.real_execution,
        },
        "latency_profile": {
            "count": latency_profile.count,
            "p50_ms": latency_profile.p50_ms,
            "max_ms": latency_profile.max_ms,
            "stale_count": latency_profile.stale_count,
        },
        "paper_connector": {
            "accepted": paper_connector_result.accepted,
            "order_id": paper_connector_result.order_id,
            "reason": paper_connector_result.reason,
            "paper_only": paper_connector_result.paper_only,
            "real_execution": paper_connector_result.real_execution,
        },
        "funding_signals": [
            {"coin": item.coin, "decision": item.decision, "z_score": item.z_score, "reason": item.reason}
            for item in funding_signals
        ],
        "price_discrepancies": [
            {
                "coin": item.coin,
                "source_a": item.source_a,
                "source_b": item.source_b,
                "spread_bps": item.spread_bps,
                "decision": item.decision,
            }
            for item in price_discrepancies
        ],
        "triangular": [
            {
                "path": list(item.cycle.path),
                "gross_edge_bps": item.gross_edge_bps,
                "cost_bps": item.cost_bps,
                "net_edge_bps": item.net_edge_bps,
                "accepted": item.accepted,
                "reason": item.reason,
            }
            for item in triangular
        ],
        "fusion_runtime": fusion_runtime.as_dict(),
        "dashboard_payload_path": str(data_dir / "refactor_fusion_dashboard_payload.json"),
        "paper_only": True,
        "real_execution": False,
    }
    json_path = data_dir / "refactor_fusion_run.json"
    payload_path = data_dir / "refactor_fusion_dashboard_payload.json"
    markdown_path = docs_dir / "HYPERSMART_REFACTOR_FUSION_RUN.md"
    json_path.write_text(json.dumps(result_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_body = (
        _format_markdown(audit, wallet_results, arbitrage_results, payload_path)
        + "\n\n## Multi-leader / risk / replay\n\n"
        + f"- Conflict resolver: {conflict.decision} side={conflict.winning_side or 'NONE'} reasons={','.join(conflict.reasons) or 'OK'}\n"
        + f"- Liquidity cliff: blocked={liquidity_cliff.blocked} reason={liquidity_cliff.reason}\n"
        + f"- Concentration: blocked={concentration.blocked} share={concentration.top_wallet_share}\n"
        + f"- Replay paper PnL: {replay.net_pnl_usdt:.6f} USDT on {len(replay.trades)} fixture trade(s)\n"
        + f"- Dual venue hedge: accepted={hedge.accepted} reason={hedge.reason} real_execution={hedge.real_execution}\n"
        + "\n## Secondary ports\n\n"
        + f"- Copy session: {copy_session.status}, watchlist={len(copy_session.watchlist)}, paper_only={copy_session.paper_only}\n"
        + f"- Latency profile: p50={latency_profile.p50_ms}ms, stale={latency_profile.stale_count}/{latency_profile.count}\n"
        + f"- Paper connector: accepted={paper_connector_result.accepted}, id={paper_connector_result.order_id}, real_execution={paper_connector_result.real_execution}\n"
        + f"- Funding signals: {len(funding_signals)}\n"
        + f"- WS price discrepancies: {len(price_discrepancies)}\n"
        + f"- Triangular opportunities: {len(triangular)}\n"
        + f"- Fusion runtime paper orders: {len(fusion_runtime.paper_orders)}, no-trades={len(fusion_runtime.no_trade_reasons)}\n"
    )
    markdown_path.write_text(markdown_body, encoding="utf-8")
    return RefactorFusionRunResult(
        dry_run=True,
        log_dir=log_dir,
        json_path=json_path,
        dashboard_payload_path=payload_path,
        markdown_path=markdown_path,
        audit=audit,
        wallet_results=wallet_results,
        arbitrage_results=arbitrage_results,
        dashboard_payload=payload,
    )


def format_refactor_fusion_run(result: RefactorFusionRunResult) -> str:
    fusion = (result.dashboard_payload.get("extra_panels", {}) or {}).get("fusion_runtime", {}) or {}
    fusion_orders = len(fusion.get("paper_orders", []) or [])
    fusion_engine = fusion.get("paper_engine", {}) or {}
    fusion_engine_accepted = fusion_engine.get("accepted_count", 0)
    fusion_discrepancies = len(fusion.get("price_discrepancies", []) or [])
    fusion_funding = len(fusion.get("funding_signals", []) or [])
    fusion_triangular = len(fusion.get("triangular_opportunities", []) or [])
    return "\n".join(
        [
            "refactor_fusion_run=ok",
            f"dry_run={str(result.dry_run).lower()}",
            f"log_dir={result.log_dir}",
            f"wallet_candidates={len(result.wallet_results)}",
            f"paper_intents={result.paper_intents_count}",
            f"arbitrage_opportunities={len(result.arbitrage_results)}",
            f"arbitrage_accepted={result.arbitrage_accepted_count}",
            f"fusion_runtime_orders={fusion_orders}",
            f"fusion_paper_engine_accepted={fusion_engine_accepted}",
            f"fusion_price_discrepancies={fusion_discrepancies}",
            f"fusion_funding_signals={fusion_funding}",
            f"fusion_triangular_opportunities={fusion_triangular}",
            f"json={result.json_path}",
            f"dashboard_payload={result.dashboard_payload_path}",
            f"markdown={result.markdown_path}",
            "paper_only=true",
            "real_execution=false",
        ]
    )


def _fixture_wallet_mirror(log_dir: Path, *, session_context: SessionEntryRiskContext | None = None) -> MirrorPipelineResult:
    observed = int(datetime.now(UTC).timestamp() * 1000)
    delta = LeaderDelta(
        delta_id="fixture:leader_delta:hype:open_long",
        wallet="0x1111111111111111111111111111111111111111",
        coin="HYPE",
        action=LifecycleAction.OPEN_LONG,
        previous_size=0.0,
        current_size=15.0,
        delta_size=15.0,
        observed_at_ms=observed,
        leader_event_time_ms=observed - 250,
        source="fixture:refactor_fusion_wallet_copy_e2e",
        confidence=0.96,
        reason_codes=(),
        evidence_ref="fixture_fill_001",
    )
    return run_wallet_mirror_pipeline(
        delta,
        leader_price=100.0,
        observed_time_ms=observed,
        wallet_score=0.98,
        copyability_score=0.93,
        wallet_rank=1,
        wallet_rank_age_ms=5_000,
        leader_notional_usdt=100_000.0,
        current_mid=100.04,
        spread_bps=1.2,
        fee_bps=2.0,
        slippage_bps=1.8,
        latency_penalty_bps=0.8,
        logs_dir=log_dir,
        leader_expected_edge_bps=72.0,
        session_risk_context=session_context,
    )


def _session_context_from_audit(audit: V19NegativePnlAudit) -> SessionEntryRiskContext:
    return SessionEntryRiskContext(
        net_pnl_usdc=audit.net_pnl_usdc,
        total_decisions=audit.total_decisions,
        accepted=audit.accepted,
        negative_events=audit.negative_events,
        positive_events=audit.positive_events,
        fee_drag_ratio=audit.fee_drag_ratio,
        stale_reason_count=sum(count for reason, count in audit.top_refusal_reasons if "STALE" in reason or "TOO_LATE" in reason),
        edge_negative_count=audit.edge_negative_count,
        edge_sentinel_count=audit.edge_sentinel_count,
        orphan_close_count=audit.orphan_close_count,
        profit_factor_net=audit.profit_factor_net,
        consecutive_losses=audit.consecutive_losses,
        top_losing_coins=tuple((item.key, item.pnl_usdc) for item in audit.losing_coins[:10]),
        top_losing_wallets=tuple((item.key, item.pnl_usdc) for item in audit.losing_wallets[:10]),
        top_losing_actions=tuple((item.key, item.pnl_usdc) for item in audit.losing_actions[:10]),
    )


def _fixture_arbitrage() -> CrossExchangeOpportunity:
    hl = OrderBookSnapshot(
        source="hyperliquid_fixture",
        symbol="HYPE-PERP",
        bid=99.90,
        ask=100.00,
        bid_size=180_000.0,
        ask_size=190_000.0,
        timestamp_ms=1_000,
    )
    cex = OrderBookSnapshot(
        source="cex_fixture",
        symbol="HYPE-USDT",
        bid=101.40,
        ask=101.55,
        bid_size=210_000.0,
        ask_size=220_000.0,
        timestamp_ms=1_000,
    )
    return scan_hyperliquid_cex_spread(
        hyperliquid_book=hl,
        cex_book=cex,
        fee_bps=6.0,
        slippage_bps=4.0,
        latency_penalty_bps=2.0,
        funding_rate=0.0,
    )


def _format_markdown(
    audit: V19NegativePnlAudit,
    wallet_results: tuple[MirrorPipelineResult, ...],
    arbitrage_results: tuple[CrossExchangeOpportunity, ...],
    payload_path: Path,
) -> str:
    lines = [
        "# HyperSmart refactor fusion run",
        "",
        "Scope: runtime actif `src/hl_observer`, simulation locale paper only.",
        "",
        "## PnL audit",
        "",
        f"- Logs: `{audit.log_dir}`",
        f"- PnL net effectif: {audit.net_pnl_usdc:.6f} USDC",
        f"- Protection mode: {str(audit.risk_decision.protection_mode).lower()}",
        "",
        "## Wallet mirror E2E",
        "",
    ]
    for item in wallet_results:
        lines.append(
            f"- {item.candidate.coin} {item.candidate.side}: accepted={item.accepted} "
            f"paper_intent={item.paper_intent is not None} edge={item.edge_estimate.net_edge_bps} "
            f"reasons={','.join(item.no_trade_reasons) or 'OK'}"
        )
        lines.append(
            f"  - Entry cost guard: accepted={item.entry_cost_guard.accepted} "
            f"min_notional={item.entry_cost_guard.required_min_notional_usdt} "
            f"min_edge={item.entry_cost_guard.required_min_edge_bps} "
            f"observed_notional={item.entry_cost_guard.observed_notional_usdt} "
            f"observed_edge={item.entry_cost_guard.observed_edge_bps} "
            f"reasons={','.join(item.entry_cost_guard.reason_codes) or 'OK'}"
        )
    lines.extend(["", "## Arbitrage cross-source E2E", ""])
    for item in arbitrage_results:
        lines.append(
            f"- {item.spread.coin}: decision={item.decision} net_edge={item.spread.net_edge_bps} "
            f"funding_adjusted={item.funding_adjusted_edge_bps} reasons={','.join(item.reason_codes) or 'OK'}"
        )
    lines.extend(
        [
            "",
            "## Dashboard payload",
            "",
            f"- `{payload_path}`",
            "",
            "## Safety",
            "",
            "- paper_only=true",
            "- real_execution=false",
            "- external_order=false",
            "- signature=false",
            "- private_key=false",
            "- fixtures are labeled as fixtures when live source is absent.",
        ]
    )
    return "\n".join(lines)


__all__ = ["RefactorFusionRunResult", "format_refactor_fusion_run", "run_refactor_fusion"]
