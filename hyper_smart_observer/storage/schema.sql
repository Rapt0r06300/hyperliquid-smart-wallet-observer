-- HyperSmart Official Database Schema (Batches 1-5)
-- Observation-only, Local Paper Simulation, No Execution.

CREATE TABLE IF NOT EXISTS app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    label TEXT,
    source TEXT,
    discovered_at TEXT,
    status TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    coin TEXT,
    px REAL,
    sz REAL,
    side TEXT,
    time INTEGER,
    price REAL,
    size REAL,
    fee REAL,
    closed_pnl REAL,
    action_type TEXT,
    start_position REAL,
    fee_token TEXT,
    timestamp TEXT,
    raw_id TEXT,
    source TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS fill_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    coin TEXT,
    fill_time TEXT,
    raw_id TEXT,
    direction TEXT,
    side TEXT,
    price REAL,
    size REAL,
    closed_pnl REAL,
    start_position REAL,
    source TEXT,
    collection_run_id TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS wallet_scores (
    wallet_address TEXT PRIMARY KEY,
    calculated_at TEXT,
    final_score REAL,
    status TEXT,
    usable_fills INTEGER,
    skipped_fills INTEGER,
    first_fill_at TEXT,
    last_fill_at TEXT,
    history_days REAL,
    gross_pnl REAL,
    net_pnl REAL,
    total_fees REAL,
    average_win REAL,
    average_loss REAL,
    sample_quality_score REAL,
    recency_score REAL,
    consistency_score REAL,
    risk_score REAL,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS leaderboard_shortlist (
    wallet_address TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    score REAL,
    source TEXT,
    rank INTEGER,
    history_days REAL,
    closed_pnl_points INTEGER,
    pnl_concentration REAL,
    consistency_score REAL,
    max_drawdown_pct REAL,
    refusal_reasons_json TEXT,
    warnings_json TEXT,
    last_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS leader_deltas (
    delta_id TEXT PRIMARY KEY,
    leader_wallet TEXT NOT NULL,
    coin TEXT NOT NULL,
    action_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    previous_size REAL,
    current_size REAL,
    leader_reference_price REAL,
    leader_fill_time TEXT,
    raw_event_hash TEXT UNIQUE,
    source_snapshot_id TEXT,
    collection_run_id TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS leader_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    captured_at TEXT,
    source TEXT,
    positions_json TEXT,
    fills_cursor TEXT,
    open_orders_json TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS copy_signal_candidates (
    candidate_id TEXT PRIMARY KEY,
    leader_wallet TEXT NOT NULL,
    coin TEXT NOT NULL,
    action_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    leader_fill_time TEXT,
    leader_reference_price REAL,
    current_mid REAL,
    spread_bps REAL,
    slippage_bps REAL,
    fee_bps REAL,
    latency_ms INTEGER,
    liquidity_score REAL,
    leader_score REAL,
    signal_freshness_score REAL,
    copy_degradation_bps REAL,
    edge_remaining_bps REAL,
    paper_mode TEXT,
    decision TEXT NOT NULL,
    refusal_reasons_json TEXT,
    raw_event_hash TEXT NOT NULL,
    payload_json TEXT,
    source_snapshot_id TEXT,
    collection_run_id TEXT
);

CREATE TABLE IF NOT EXISTS no_trade_decisions (
    decision_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    leader_wallet TEXT,
    coin TEXT,
    candidate_id TEXT,
    observed TEXT,
    why_not_simulable TEXT,
    missing_data TEXT,
    next_action TEXT,
    context_json TEXT,
    risk_level TEXT NOT NULL DEFAULT 'INFO',
    component TEXT NOT NULL DEFAULT 'copy_mode'
);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id TEXT PRIMARY KEY,
    intent_id TEXT,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size REAL NOT NULL,
    notional REAL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    fee_entry REAL,
    fee_exit REAL,
    slippage_entry REAL,
    slippage_exit REAL,
    spread_cost REAL,
    gross_pnl REAL,
    net_pnl REAL,
    status TEXT NOT NULL,
    state TEXT,
    close_reason TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS paper_intents (
    intent_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    coin TEXT,
    side TEXT,
    reference_price REAL,
    requested_notional REAL,
    created_at TEXT,
    status TEXT,
    refusal_reason TEXT
);

CREATE TABLE IF NOT EXISTS risk_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    severity TEXT,
    component TEXT,
    reason_code TEXT,
    message TEXT,
    blocked_action TEXT,
    context_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id TEXT PRIMARY KEY,
    source TEXT,
    started_at TEXT,
    finished_at TEXT,
    status TEXT,
    stopped_reason TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS fill_dedupe (
    dedupe_key TEXT PRIMARY KEY,
    wallet_address TEXT,
    coin TEXT,
    fill_time TEXT,
    raw_id TEXT,
    seen_at TEXT
);

CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    checked_at TEXT,
    status TEXT,
    message TEXT,
    failures_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT,
    checked_at TEXT,
    ok INTEGER,
    message TEXT
);

CREATE TABLE IF NOT EXISTS position_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    coin TEXT,
    size REAL,
    entry_price REAL,
    mark_price REAL,
    unrealized_pnl REAL,
    liquidation_price REAL,
    leverage TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS open_order_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    coin TEXT,
    captured_at TEXT,
    raw_json TEXT
);
