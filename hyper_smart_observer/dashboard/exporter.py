from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.consensus import detect_position_consensus
from hyper_smart_observer.copy_mode.repository import list_latest_leader_deltas, list_latest_signal_candidates, list_no_trade_decisions, list_shortlist
from hyper_smart_observer.runtime.runtime_check import format_runtime_report, scan_runtime_files
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import paper_trades_repo, risk_events_repo, scores_repo


def export_dashboard(config: AppConfig, output_path: Path | None = None) -> Path:
    initialize_database(config)
    output_dir = config.dashboard_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_path or output_dir / "hypersmart_dashboard.html"
    with get_connection(config) as conn:
        scores = scores_repo.list_latest_scores(conn, limit=25)
        open_trades = paper_trades_repo.list_open_paper_trades(conn)
        closed_trades = paper_trades_repo.list_closed_paper_trades(conn, limit=25)
        risk_events = risk_events_repo.list_risk_events(conn, limit=25)
        shortlist = list_shortlist(conn, limit=25)
        leader_deltas = list_latest_leader_deltas(conn, limit=25)
        copy_signals = list_latest_signal_candidates(conn, limit=25)
        no_trade = list_no_trade_decisions(conn, limit=25)
        source_health = list(conn.execute("SELECT * FROM source_health ORDER BY checked_at DESC LIMIT 25"))
        api_health = list(conn.execute("SELECT * FROM api_health ORDER BY checked_at DESC LIMIT 25"))
    consensus_positions = detect_position_consensus(leader_deltas, min_wallets=2, window_seconds=300)
    simulation_reports = _load_simulation_reports(config.reports_dir)
    runtime_report = scan_runtime_files(config)
    html = _render_html(
        runtime_report=format_runtime_report(runtime_report),
        scores=scores,
        open_trades=open_trades,
        closed_trades=closed_trades,
        risk_events=risk_events,
        shortlist=shortlist,
        leader_deltas=leader_deltas,
        copy_signals=copy_signals,
        no_trade=no_trade,
        consensus_positions=consensus_positions,
        source_health=source_health,
        api_health=api_health,
        simulation_reports=simulation_reports,
    )
    output_path.write_text(html, encoding="utf-8")
    return output_path


def _render_html(
    *,
    runtime_report: str,
    scores,
    open_trades,
    closed_trades,
    risk_events,
    shortlist,
    leader_deltas,
    copy_signals,
    no_trade,
    consensus_positions,
    source_health,
    api_health,
    simulation_reports,
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>HyperSmart Observer - Read Only Dashboard</title>
  <style>
    body {{ background:#05070d; color:#e8faff; font-family:Consolas, monospace; margin:0; padding:24px; }}
    h1,h2 {{ color:#00d9ff; }}
    .badge {{ border:1px solid #00ff88; color:#00ff88; padding:6px 10px; display:inline-block; margin:4px; }}
    .panel {{ border:1px solid #0b6f82; background:#0b1020; padding:16px; margin:16px 0; border-radius:8px; }}
    .tabs {{ margin:18px 0; display:flex; flex-wrap:wrap; gap:8px; }}
    .tabs a {{ color:#e8faff; border:1px solid #0b6f82; padding:8px 10px; text-decoration:none; background:#081326; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid #123; padding:8px; text-align:left; }}
    .warn {{ color:#ffb020; }}
  </style>
</head>
<body>
  <h1>HyperSmart Observer</h1>
  <p>Hyperliquid Explorer / Wallet Observer - Local Read-Only Dashboard</p>
  <div>
    <span class="badge">READ ONLY</span><span class="badge">NO EXCHANGE</span><span class="badge">NO ORDERS</span>
    <span class="badge">NO SIGNATURES</span><span class="badge">NO MAINNET</span><span class="badge">NO TESTNET EXECUTOR</span>
    <span class="badge">PAPER LOCAL ONLY</span><span class="badge">RESEARCH ONLY</span>
  </div>
  <nav class="tabs" aria-label="Dashboard tabs">
    <a href="#simulation">Simulation</a>
    <a href="#copy-status">Copy Status</a>
    <a href="#consensus">Consensus</a>
    <a href="#leaderboard">Leaderboard</a>
    <a href="#signals">Signals</a>
    <a href="#paper">Paper Local</a>
    <a href="#safety">Safety</a>
  </nav>
  <section id="runtime" class="panel"><h2>Runtime / Archive Readiness</h2><pre>{escape(runtime_report)}</pre></section>
  <section id="collection" class="panel"><h2>Data Collection Status</h2><p>REST /info: configured read-only. Explorer observer: disabled by default. WebSocket monitor: disabled by default.</p></section>
  <section id="simulation" class="panel"><h2>Simulation</h2><p>Local historical follow replay. No mock USDC wallet, no faucet, no order, no execution. Results are notional estimates after costs.</p>{_simulation_table(simulation_reports)}</section>
  <section id="consensus" class="panel"><h2>Consensus Positions</h2><p>Checks whether several watched wallets opened or increased the same coin and direction inside a bounded window. Research-only: consensus can also mean crowding or late-entry risk, never guaranteed profit.</p>{_consensus_table(consensus_positions)}</section>
  <section id="copy-status" class="panel"><h2>Copy Status</h2><p>Architecture 3 jobs: leaderboard shortlist, copy loop dry-run, reports/no-trade. Polling default: 300 seconds. Paper mock USDC only when using paper portfolio modules.</p></section>
  <section class="panel"><h2>Top Wallets Followed</h2>{_shortlist_table(shortlist)}</section>
  <section id="leaderboard" class="panel"><h2>Leaderboard Shortlist</h2>{_shortlist_table(shortlist)}</section>
  <section class="panel"><h2>Leader Activity</h2><p>Leader deltas are shown from local snapshots and stored copy signal candidates. Ambiguous deltas stay UNKNOWN.</p></section>
  <section class="panel"><h2>Latest Deltas</h2>{_delta_table(leader_deltas)}</section>
  <section id="signals" class="panel"><h2>Signal Candidates</h2>{_signal_table(copy_signals)}</section>
  <section class="panel"><h2>No-Trade Report</h2>{_no_trade_table(no_trade)}</section>
  <section class="panel"><h2>Edge Remaining</h2>{_edge_table(copy_signals)}</section>
  <section class="panel"><h2>Copy Degradation</h2>{_degradation_table(copy_signals)}</section>
  <section class="panel"><h2>Source Failures</h2>{_source_health_table(source_health)}</section>
  <section class="panel"><h2>Wallet Discovery</h2><p>Discovery candidates appear after imports, explorer fixtures, WS observations or local fills. No wallet is invented.</p></section>
  <section class="panel"><h2>Smart Wallet Rankings</h2>{_scores_table(scores)}</section>
  <section class="panel"><h2>Position Lifecycle</h2><p>Openings, closings, reductions, increases and UNKNOWN actions are reconstructed from local data only.</p></section>
  <section class="panel"><h2>Pattern Detector</h2><p>Patterns require enough evidence. Historical patterns are research-only.</p></section>
  <section class="panel"><h2>Backtests / Replays</h2><p>Backtests are local simulations with fees, spread, slippage and latency assumptions.</p></section>
  <section id="paper" class="panel"><h2>Paper Trading</h2>{_paper_table(open_trades, closed_trades)}</section>
  <section class="panel"><h2>Risk Events</h2>{_risk_table(risk_events)}</section>
  <section id="safety" class="panel"><h2>Safety Audit</h2><p>Read-only dashboard. No wallet connection, no secret form, no execution controls, no mainnet controls.</p></section>
  <section class="panel"><h2>Archive Audit</h2><p>Desktop clean archive only. Root ZIP/7Z/RAR files are warnings and excluded from clean archives.</p></section>
  <section class="panel"><h2>API Limits Status</h2>{_api_health_table(api_health)}</section>
  <section class="panel"><h2>Limitations</h2><p>No guaranteed profit. Historical PnL is not future PnL. Paper trading is approximate. No order execution exists.</p></section>
</body></html>"""


def _load_simulation_reports(reports_dir: Path) -> list[dict[str, Any]]:
    if not reports_dir.exists():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("multi_wallet_follow_simulation_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["_path"] = str(path)
        reports.append(payload)
    return reports


def _scores_table(rows) -> str:
    if not rows:
        return "<p>No scores stored.</p>"
    lines = ["<table><tr><th>Wallet</th><th>Status</th><th>Confidence</th><th>Final</th><th>Reason</th></tr>"]
    for row in rows:
        lines.append(f"<tr><td>{escape(str(row['wallet_address']))}</td><td>{escape(str(row['status']))}</td><td>{row['confidence_score']}</td><td>{row['final_score']}</td><td>{escape(str(row['refusal_reason']))}</td></tr>")
    lines.append("</table>")
    return "".join(lines)


def _paper_table(open_rows, closed_rows) -> str:
    return f"<p>Open paper simulations: {len(open_rows)}. Closed paper simulations: {len(closed_rows)}.</p>"


def _simulation_table(reports: list[dict[str, Any]]) -> str:
    if not reports:
        return "<p>No local simulation report stored yet. Use --simulate-copy-wallet or --simulate-copy-wallets-file after collecting local fills.</p>"
    lines = [
        "<table><tr><th>Generated</th><th>Scenario</th><th>Wallets</th><th>Usable</th><th>Gross</th><th>Costs</th><th>Net</th><th>Max DD</th><th>Report</th></tr>"
    ]
    for report in reports:
        lines.append(
            "<tr>"
            f"<td>{escape(str(report.get('generated_at', '')))}</td>"
            f"<td>{escape(str(report.get('scenario', '')))}</td>"
            f"<td>{escape(str(report.get('simulated_wallets', 0)))}/{escape(str(report.get('requested_wallets', 0)))}</td>"
            f"<td>{escape(str(report.get('total_usable_trades', 0)))}</td>"
            f"<td>{escape(str(report.get('gross_pnl', 0.0)))}</td>"
            f"<td>{escape(str(report.get('total_costs', 0.0)))}</td>"
            f"<td>{escape(str(report.get('net_pnl', 0.0)))}</td>"
            f"<td>{escape(str(report.get('max_drawdown', 0.0)))}</td>"
            f"<td>{escape(str(report.get('_path', '')))}</td>"
            "</tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _consensus_table(rows) -> str:
    if not rows:
        return "<p>No multi-wallet position consensus detected from stored leader deltas.</p>"
    lines = [
        "<table><tr><th>Coin</th><th>Direction</th><th>Wallets</th><th>First Seen</th><th>Last Seen</th><th>Score</th><th>Crowding</th><th>Warnings</th></tr>"
    ]
    for row in rows:
        lines.append(
            "<tr>"
            f"<td>{escape(str(row.coin))}</td>"
            f"<td>{escape(str(row.direction))}</td>"
            f"<td>{escape(str(row.wallet_count))}: {escape(', '.join(row.wallets))}</td>"
            f"<td>{escape(row.first_seen.isoformat())}</td>"
            f"<td>{escape(row.last_seen.isoformat())}</td>"
            f"<td>{escape(str(row.consensus_score))}</td>"
            f"<td>{escape(str(row.crowding_risk))}</td>"
            f"<td>{escape(', '.join(row.warnings))}</td>"
            "</tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _risk_table(rows) -> str:
    if not rows:
        return "<p>No risk events stored.</p>"
    lines = ["<table><tr><th>Reason</th><th>Component</th><th>Message</th></tr>"]
    for row in rows:
        lines.append(f"<tr><td>{escape(str(row['reason_code']))}</td><td>{escape(str(row['component']))}</td><td>{escape(str(row['message']))}</td></tr>")
    lines.append("</table>")
    return "".join(lines)


def _shortlist_table(rows) -> str:
    if not rows:
        return "<p>No leaderboard shortlist stored. Run copy-run dry-run or import local candidates.</p>"
    lines = ["<table><tr><th>Wallet</th><th>Status</th><th>Score</th><th>Reasons</th></tr>"]
    for row in rows:
        lines.append(
            f"<tr><td>{escape(str(row['wallet_address']))}</td><td>{escape(str(row['status']))}</td>"
            f"<td>{row['score']}</td><td>{escape(str(row['refusal_reasons_json']))}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _signal_table(rows) -> str:
    if not rows:
        return "<p>No copy signal candidates stored.</p>"
    lines = ["<table><tr><th>Leader</th><th>Coin</th><th>Action</th><th>Decision</th><th>Edge bps</th></tr>"]
    for row in rows:
        lines.append(
            f"<tr><td>{escape(str(row['leader_wallet']))}</td><td>{escape(str(row['coin']))}</td>"
            f"<td>{escape(str(row['action_type']))}</td><td>{escape(str(row['decision']))}</td>"
            f"<td>{row['edge_remaining_bps']}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _delta_table(rows) -> str:
    if not rows:
        return "<p>No leader deltas stored.</p>"
    lines = ["<table><tr><th>Leader</th><th>Coin</th><th>Action</th><th>Previous</th><th>Current</th><th>Warnings</th></tr>"]
    for row in rows:
        lines.append(
            f"<tr><td>{escape(str(row['leader_wallet']))}</td><td>{escape(str(row['coin']))}</td>"
            f"<td>{escape(str(row['action_type']))}</td><td>{row['previous_size']}</td>"
            f"<td>{row['current_size']}</td><td>{escape(str(row['warnings_json']))}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _no_trade_table(rows) -> str:
    if not rows:
        return "<p>No no-trade decisions stored.</p>"
    lines = ["<table><tr><th>Reason</th><th>Observed</th><th>Why</th><th>Next</th></tr>"]
    for row in rows:
        lines.append(
            f"<tr><td>{escape(str(row['reason']))}</td><td>{escape(str(row['observed']))}</td>"
            f"<td>{escape(str(row['why_not_simulable']))}</td><td>{escape(str(row['next_action']))}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _edge_table(rows) -> str:
    if not rows:
        return "<p>No edge_remaining_bps values stored. Signals without measurable edge are refused.</p>"
    return _signal_table(rows)


def _degradation_table(rows) -> str:
    if not rows:
        return "<p>No copy degradation values stored.</p>"
    lines = ["<table><tr><th>Candidate</th><th>Spread</th><th>Slippage</th><th>Fee</th><th>Degradation</th></tr>"]
    for row in rows:
        lines.append(
            f"<tr><td>{escape(str(row['candidate_id']))}</td><td>{row['spread_bps']}</td>"
            f"<td>{row['slippage_bps']}</td><td>{row['fee_bps']}</td><td>{row['copy_degradation_bps']}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _source_health_table(rows) -> str:
    if not rows:
        return "<p>No source health rows stored.</p>"
    lines = ["<table><tr><th>Source</th><th>Status</th><th>Message</th><th>Failures</th></tr>"]
    for row in rows:
        lines.append(
            f"<tr><td>{escape(str(row['source']))}</td><td>{escape(str(row['status']))}</td>"
            f"<td>{escape(str(row['message']))}</td><td>{row['failures_count']}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _api_health_table(rows) -> str:
    if not rows:
        return "<p>No API health rows stored. Network reads are explicit and disabled by default.</p>"
    lines = ["<table><tr><th>Component</th><th>OK</th><th>Message</th></tr>"]
    for row in rows:
        lines.append(
            f"<tr><td>{escape(str(row['component']))}</td><td>{row['ok']}</td>"
            f"<td>{escape(str(row['message']))}</td></tr>"
        )
    lines.append("</table>")
    return "".join(lines)
