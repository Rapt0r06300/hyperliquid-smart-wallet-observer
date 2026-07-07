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
    copy_period_reports = _load_copy_period_reports(config.reports_dir)
    scan_features_report = _load_latest_scan_features(config.reports_dir)
    decision_ledger_report = _load_latest_decision_ledger(config.reports_dir)
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
        copy_period_reports=copy_period_reports,
        scan_features_report=scan_features_report,
        decision_ledger_report=decision_ledger_report,
        starting_equity=config.paper_starting_equity,
        active_config=_safe_config_snapshot(config),
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
    copy_period_reports,
    scan_features_report,
    decision_ledger_report,
    starting_equity=0.0,
    active_config=None,
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
    <a href="#ledger">Decision Ledger</a>
    <a href="#paper">Paper Local</a>
    <a href="#safety">Safety</a>
  </nav>
  <section id="runtime" class="panel"><h2>Runtime / Archive Readiness</h2><pre>{escape(runtime_report)}</pre></section>
  <section id="active-config" class="panel"><h2>Configuration active / seuils</h2><p>Seuils reellement lus par le runtime copy/paper. Cette section n'affiche jamais de cle privee, signature, wallet connect ou secret.</p>{_config_table(active_config or [])}</section>
  <section id="collection" class="panel"><h2>Data Collection Status</h2><p>REST /info: configured read-only. Explorer observer: disabled by default. WebSocket monitor: disabled by default.</p></section>
  <section id="simulation" class="panel"><h2>Simulation</h2><p>Local historical follow replay. No mock USDC wallet, no faucet, no order, no execution. Results are notional estimates after costs.</p>{_simulation_table(simulation_reports)}</section>
  <section class="panel"><h2>Runtime Paper vs Replay Paper</h2><p>Compares the latest local runtime paper ledger against stored paper replay reports. Same warning: paper result is not future profit.</p>{_runtime_replay_comparison_table(open_trades, closed_trades, starting_equity, simulation_reports, copy_period_reports)}</section>
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
  <section class="panel"><h2>Market Signal Features</h2>{_scan_features_table(scan_features_report)}</section>
  <section id="ledger" class="panel"><h2>Decision Ledger</h2>{_decision_ledger_table(decision_ledger_report)}</section>
  <section class="panel"><h2>Source Failures</h2>{_source_health_table(source_health)}</section>
  <section class="panel"><h2>Wallet Discovery</h2><p>Discovery candidates appear after imports, explorer fixtures, WS observations or local fills. No wallet is invented.</p></section>
  <section class="panel"><h2>Smart Wallet Rankings</h2>{_scores_table(scores)}</section>
  <section class="panel"><h2>Position Lifecycle</h2><p>Openings, closings, reductions, increases and UNKNOWN actions are reconstructed from local data only.</p></section>
  <section class="panel"><h2>Pattern Detector</h2><p>Patterns require enough evidence. Historical patterns are research-only.</p></section>
  <section class="panel"><h2>Backtests / Replays</h2><p>Backtests are local simulations with fees, spread, slippage and latency assumptions.</p></section>
  <section id="paper" class="panel"><h2>Paper Trading</h2>{_paper_table(open_trades, closed_trades, starting_equity)}</section>
  <section class="panel"><h2>Risk Events</h2>{_risk_table(risk_events)}</section>
  <section id="safety" class="panel"><h2>Safety Audit</h2><p>Read-only dashboard. No wallet connection, no secret form, no execution controls, no mainnet controls.</p></section>
  <section class="panel"><h2>Archive Audit</h2><p>Desktop clean archive only. Root ZIP/7Z/RAR files are warnings and excluded from clean archives.</p></section>
  <section class="panel"><h2>API Limits Status</h2>{_api_health_table(api_health)}</section>
  <section class="panel"><h2>Limitations</h2><p>No guaranteed profit. Historical PnL is not future PnL. Paper trading is approximate. No order execution exists.</p></section>
</body></html>"""


def _safe_config_snapshot(config: AppConfig) -> list[dict[str, Any]]:
    """Return only operator-safe thresholds used by the paper/runtime path.

    The dashboard is a read-only diagnostic surface, so this intentionally
    excludes `sensitive_key_material`, raw environment values and anything that
    could look like wallet credentials.
    """

    return [
        {
            "setting": "mode",
            "value": config.mode,
            "env": "HYPERSMART_MODE",
            "why": "doit rester simulation/research-only",
        },
        {
            "setting": "network_reads",
            "value": str(bool(config.enable_network_reads)),
            "env": "HYPERSMART_ENABLE_NETWORK_READS",
            "why": "les lectures reseau restent explicites",
        },
        {
            "setting": "copy_min_edge_required_bps",
            "value": config.copy_min_edge_required_bps,
            "env": "HYPERSMART_COPY_MIN_EDGE_REQUIRED_BPS ou HYPERSMART_SIMULATION_MIN_EDGE_BPS",
            "why": "edge_remaining_bps minimum avant paper",
        },
        {
            "setting": "copy_max_signal_age_ms",
            "value": config.copy_max_signal_age_ms,
            "env": "HYPERSMART_COPY_MAX_SIGNAL_AGE_MS ou HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS",
            "why": "refuse les signaux vieux",
        },
        {
            "setting": "copy_min_liquidity_score",
            "value": config.copy_min_liquidity_score,
            "env": "HYPERSMART_COPY_MIN_LIQUIDITY_SCORE ou HYPERSMART_SIMULATION_MIN_LIQUIDITY_SCORE",
            "why": "refuse les carnets trop minces",
        },
        {
            "setting": "copy_max_degradation_bps",
            "value": config.copy_max_degradation_bps,
            "env": "HYPERSMART_COPY_MAX_DEGRADATION_BPS ou HYPERSMART_SIMULATION_MAX_COPY_DEGRADATION_BPS",
            "why": "borne retard + spread + slippage + fees",
        },
        {
            "setting": "paper_starting_equity",
            "value": config.paper_starting_equity,
            "env": "HYPERSMART_PAPER_STARTING_EQUITY",
            "why": "capital paper local seulement",
        },
        {
            "setting": "paper_max_position_notional",
            "value": config.paper_max_position_notional,
            "env": "HYPERSMART_PAPER_MAX_POSITION_NOTIONAL ou HYPERSMART_SIMULATION_MAX_POSITION_NOTIONAL",
            "why": "taille maximale par position simulee",
        },
        {
            "setting": "paper_max_open_trades",
            "value": config.paper_max_open_trades,
            "env": "HYPERSMART_PAPER_MAX_OPEN_TRADES ou HYPERSMART_SIMULATION_MAX_OPEN_POSITIONS",
            "why": "limite les positions paper simultanees",
        },
        {
            "setting": "ws_unique_users",
            "value": config.ws_max_user_subscriptions,
            "env": "HYPERSMART_WS_MAX_USER_SUBSCRIPTIONS ou HYPERSMART_WS_MAX_UNIQUE_USERS",
            "why": "respecte le plafond user-specific WS",
        },
    ]


def _config_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>No safe configuration snapshot available.</p>"
    lines = ["<table><tr><th>Seuil</th><th>Valeur active</th><th>Variable</th><th>Impact</th></tr>"]
    for row in rows:
        lines.append(
            "<tr>"
            f"<td>{escape(str(row.get('setting', '')))}</td>"
            f"<td>{escape(str(row.get('value', '')))}</td>"
            f"<td>{escape(str(row.get('env', '')))}</td>"
            f"<td>{escape(str(row.get('why', '')))}</td>"
            "</tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _load_simulation_reports(reports_dir: Path) -> list[dict[str, Any]]:
    if not reports_dir.exists():
        return []
    reports: list[dict[str, Any]] = []
    paths = [
        *reports_dir.glob("multi_wallet_follow_simulation_*.json"),
        *reports_dir.glob("paper_replay_*.json"),
    ]
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["_path"] = str(path)
        reports.append(payload)
    return reports


def _load_copy_period_reports(reports_dir: Path) -> list[dict[str, Any]]:
    if not reports_dir.exists():
        return []
    reports: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("copy_period_report_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload["_path"] = str(path)
            reports.append(payload)
    return reports


def _load_latest_scan_features(reports_dir: Path) -> dict[str, Any]:
    scan_dir = reports_dir / "scan_features"
    if not scan_dir.exists():
        return {"path": None, "rows": [], "total_rows": 0}
    for path in sorted(scan_dir.glob("scan_features_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        rows = [row for row in payload if isinstance(row, dict)]
        return {"path": str(path), "rows": rows[:25], "total_rows": len(rows)}
    return {"path": None, "rows": [], "total_rows": 0}


def _load_latest_decision_ledger(reports_dir: Path) -> dict[str, Any]:
    ledger_dir = reports_dir / "decision_ledger"
    if not ledger_dir.exists():
        return {"path": None, "rows": [], "total_rows": 0}
    for path in sorted(ledger_dir.glob("decision_ledger_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        rows = [row for row in payload if isinstance(row, dict)]
        return {"path": str(path), "rows": rows[:25], "total_rows": len(rows)}
    return {"path": None, "rows": [], "total_rows": 0}


def _scores_table(rows) -> str:
    if not rows:
        return "<p>No scores stored.</p>"
    lines = ["<table><tr><th>Wallet</th><th>Status</th><th>Confidence</th><th>Final</th><th>Reason</th></tr>"]
    for row in rows:
        lines.append(f"<tr><td>{escape(str(row['wallet_address']))}</td><td>{escape(str(row['status']))}</td><td>{row['confidence_score']}</td><td>{row['final_score']}</td><td>{escape(str(row['refusal_reason']))}</td></tr>")
    lines.append("</table>")
    return "".join(lines)


def _paper_table(open_rows, closed_rows, starting_equity: float = 0.0) -> str:
    realized = sum(float(r["net_pnl"] or r["pnl"] or 0.0) for r in closed_rows)
    start = float(starting_equity)
    equity = start + realized
    eq = start
    peak = start
    max_dd = 0.0
    for r in sorted(closed_rows, key=lambda x: (x["closed_at"] or "")):
        eq += float(r["net_pnl"] or r["pnl"] or 0.0)
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    return (
        f"<p>Open paper simulations: {len(open_rows)}. Closed paper simulations: {len(closed_rows)}.</p>"
        f"<table><tr><th>Starting equity</th><th>Realized PnL</th><th>Current equity</th>"
        f"<th>Max drawdown</th></tr>"
        f"<tr><td>{start:.2f}</td><td>{realized:.2f}</td><td>{equity:.2f}</td><td>{max_dd:.2f}</td></tr></table>"
        "<p>Latent PnL is shown only when live read-only mids are available. Paper/mock USDC only; no real order.</p>"
    )


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


def _runtime_replay_comparison_table(open_rows, closed_rows, starting_equity: float, simulation_reports: list[dict[str, Any]], copy_period_reports: list[dict[str, Any]]) -> str:
    realized = sum(float(r["net_pnl"] or r["pnl"] or 0.0) for r in closed_rows)
    runtime_drawdown = _realized_drawdown(closed_rows, float(starting_equity))
    latest_period = copy_period_reports[0] if copy_period_reports else {}
    latest_replay = next((r for r in simulation_reports if str(r.get("scenario", "")).startswith("paper_replay")), None)
    rows = [
        "<table><tr><th>Source</th><th>Equity</th><th>Net/Realized PnL</th><th>Max drawdown</th><th>Open</th><th>Closed</th><th>Report</th></tr>",
        "<tr>"
        "<td>Runtime paper DB</td>"
        f"<td>{float(starting_equity) + realized:.2f}</td>"
        f"<td>{realized:.2f}</td>"
        f"<td>{runtime_drawdown:.2f}</td>"
        f"<td>{len(open_rows)}</td>"
        f"<td>{len(closed_rows)}</td>"
        "<td>paper_trades SQLite</td>"
        "</tr>",
    ]
    if latest_period:
        rows.append(
            "<tr>"
            "<td>Latest copy-report</td>"
            f"<td>{escape(str(latest_period.get('current_equity', '')))}</td>"
            f"<td>{escape(str(latest_period.get('realized_pnl', '')))}</td>"
            f"<td>{escape(str(latest_period.get('max_drawdown', '')))}</td>"
            f"<td>{escape(str(latest_period.get('open_trades', '')))}</td>"
            f"<td>{escape(str(latest_period.get('closed_trades', '')))}</td>"
            f"<td>{escape(str(latest_period.get('_path', '')))}</td>"
            "</tr>"
        )
    if latest_replay:
        rows.append(
            "<tr>"
            "<td>Latest paper replay</td>"
            "<td></td>"
            f"<td>{escape(str(latest_replay.get('net_pnl', latest_replay.get('realized_pnl', ''))))}</td>"
            f"<td>{escape(str(latest_replay.get('max_drawdown', '')))}</td>"
            f"<td>{escape(str(latest_replay.get('open_trades', '')))}</td>"
            f"<td>{escape(str(latest_replay.get('closed', '')))}</td>"
            f"<td>{escape(str(latest_replay.get('_path', '')))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "".join(rows)


def _realized_drawdown(closed_rows, starting_equity: float) -> float:
    equity = float(starting_equity)
    peak = equity
    max_dd = 0.0
    for row in sorted(closed_rows, key=lambda item: (item["closed_at"] or "")):
        equity += float(row["net_pnl"] or row["pnl"] or 0.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


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


def _scan_features_table(report: dict[str, Any]) -> str:
    rows = report.get("rows") if isinstance(report, dict) else []
    path = report.get("path") if isinstance(report, dict) else None
    total_rows = report.get("total_rows", 0) if isinstance(report, dict) else 0
    if not rows:
        if path:
            return (
                f"<p>Latest scan_features export has 0 rows: {escape(str(path))}. "
                "No market movement is drawn without real rows.</p>"
            )
        return "<p>No scan_features export stored yet. No market movement is drawn without real rows.</p>"
    lines = [
        f"<p>Latest export: {escape(str(path))}. Rows: {escape(str(total_rows))}.</p>",
        "<table><tr><th>Time</th><th>Wallet</th><th>Symbol</th><th>Mid</th><th>Spread bps</th><th>Liquidity</th><th>Edge bps</th><th>Quality</th><th>Source</th></tr>",
    ]
    for row in rows:
        lines.append(
            "<tr>"
            f"<td>{escape(str(row.get('timestamp_ms', '')))}</td>"
            f"<td>{escape(str(row.get('wallet', '')))}</td>"
            f"<td>{escape(str(row.get('symbol', '')))}</td>"
            f"<td>{escape(str(row.get('current_mid', '')))}</td>"
            f"<td>{escape(str(row.get('spread_bps', '')))}</td>"
            f"<td>{escape(str(row.get('liquidity_score', '')))}</td>"
            f"<td>{escape(str(row.get('edge_remaining_bps', '')))}</td>"
            f"<td>{escape(str(row.get('data_quality', '')))}</td>"
            f"<td>{escape(str(row.get('source_health', '')))}</td>"
            "</tr>"
        )
    lines.append("</table>")
    return "".join(lines)


def _decision_ledger_table(report: dict[str, Any]) -> str:
    rows = report.get("rows") if isinstance(report, dict) else []
    path = report.get("path") if isinstance(report, dict) else None
    total_rows = report.get("total_rows", 0) if isinstance(report, dict) else 0
    if not rows:
        if path:
            return f"<p>Latest decision ledger has 0 rows: {escape(str(path))}.</p>"
        return "<p>No decision ledger stored yet. Run copy-run dry-run to create evidence.</p>"
    lines = [
        f"<p>Latest ledger: {escape(str(path))}. Rows: {escape(str(total_rows))}. Read-only evidence chain.</p>",
        "<table><tr><th>Decision</th><th>Coin</th><th>Wallet</th><th>Reasons</th><th>Feature hash</th><th>Paper intent</th><th>Paper trade</th><th>Exit trigger</th><th>Exit price</th><th>Realized PnL</th><th>Refs</th></tr>",
    ]
    for row in rows:
        lines.append(
            "<tr>"
            f"<td>{escape(str(row.get('decision_type', '')))}</td>"
            f"<td>{escape(str(row.get('coin', '')))}</td>"
            f"<td>{escape(str(row.get('wallet', '')))}</td>"
            f"<td>{escape(str(row.get('reason_codes', '')))}</td>"
            f"<td>{escape(str(row.get('feature_hash', '')))}</td>"
            f"<td>{escape(str(row.get('paper_intent_id', '')))}</td>"
            f"<td>{escape(str(row.get('paper_trade_id', '')))}</td>"
            f"<td>{escape(str(row.get('exit_trigger', '')))}</td>"
            f"<td>{escape(str(row.get('exit_reference_price', '')))}</td>"
            f"<td>{escape(str(row.get('realized_net_pnl', '')))}</td>"
            f"<td>{escape(str(row.get('raw_refs', '')))}</td>"
            "</tr>"
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
