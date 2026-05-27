PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    label TEXT,
    source TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    fee REAL NOT NULL,
    timestamp TEXT NOT NULL,
    raw_id TEXT,
    source TEXT NOT NULL,
    closed_pnl REAL,
    action_type TEXT,
    start_position REAL,
    fee_token TEXT,
    raw_json TEXT,
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);
CREATE INDEX IF NOT EXISTS idx_fills_wallet ON fills(wallet_address);
CREATE INDEX IF NOT EXISTS idx_fills_timestamp ON fills(timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fills_raw_id_unique ON fills(raw_id) WHERE raw_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS position_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    size REAL NOT NULL,
    entry_price REAL,
    mark_price REAL,
    unrealized_pnl REAL,
    leverage REAL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);
CREATE INDEX IF NOT EXISTS idx_positions_wallet ON position_snapshots(wallet_address);
CREATE INDEX IF NOT EXISTS idx_positions_timestamp ON position_snapshots(timestamp);

CREATE TABLE IF NOT EXISTS wallet_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    calculated_at TEXT NOT NULL,
    status TEXT,
    total_trades INTEGER NOT NULL,
    usable_fills INTEGER,
    skipped_fills INTEGER,
    first_fill_at TEXT,
    last_fill_at TEXT,
    history_days REAL,
    gross_pnl REAL,
    net_pnl REAL,
    total_fees REAL,
    winrate REAL,
    average_win REAL,
    average_loss REAL,
    pnl_net REAL,
    max_drawdown REAL,
    profit_factor REAL,
    sharpe REAL,
    sortino REAL,
    calmar REAL,
    sample_quality_score REAL,
    recency_score REAL,
    consistency_score REAL,
    risk_score REAL,
    confidence_score REAL,
    final_score REAL,
    refusal_reason TEXT,
    warnings_json TEXT,
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);
CREATE INDEX IF NOT EXISTS idx_wallet_scores_wallet ON wallet_scores(wallet_address);

CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    side TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL,
    reason TEXT NOT NULL,
    FOREIGN KEY (wallet_address) REFERENCES wallets(address)
);
CREATE INDEX IF NOT EXISTS idx_signals_wallet ON signals(wallet_address);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);

CREATE TABLE IF NOT EXISTS paper_intents (
    intent_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    side TEXT NOT NULL,
    reference_price REAL NOT NULL,
    requested_notional REAL NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT NOT NULL,
    score_snapshot_id TEXT,
    status TEXT NOT NULL,
    refusal_reason TEXT,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_intents_wallet ON paper_intents(wallet_address);
CREATE INDEX IF NOT EXISTS idx_paper_intents_status ON paper_intents(status);

CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id TEXT PRIMARY KEY,
    signal_id TEXT,
    intent_id TEXT,
    wallet_address TEXT,
    coin TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    size REAL NOT NULL,
    notional REAL,
    simulated_fee REAL NOT NULL,
    simulated_slippage REAL NOT NULL,
    fee_entry REAL,
    fee_exit REAL,
    slippage_entry REAL,
    slippage_exit REAL,
    spread_cost REAL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    pnl REAL,
    gross_pnl REAL,
    net_pnl REAL,
    state TEXT NOT NULL,
    status TEXT,
    close_reason TEXT,
    warnings_json TEXT
);
CREATE TABLE IF NOT EXISTS paper_portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    starting_equity REAL NOT NULL,
    current_equity REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    total_fees REAL NOT NULL,
    open_trades INTEGER NOT NULL,
    closed_trades INTEGER NOT NULL,
    max_drawdown REAL
);

CREATE TABLE IF NOT EXISTS risk_events (
    event_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    message TEXT NOT NULL,
    blocked_action TEXT NOT NULL,
    context_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_risk_events_created ON risk_events(created_at);

CREATE TABLE IF NOT EXISTS wallet_candidates (
    wallet_address TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    observed_trades INTEGER NOT NULL DEFAULT 0,
    observed_notional REAL,
    observed_closed_pnl REAL,
    candidate_reason TEXT NOT NULL,
    candidate_score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wallet_candidates_status ON wallet_candidates(status);

CREATE TABLE IF NOT EXISTS leaderboard_shortlist (
    wallet_address TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    score REAL NOT NULL,
    source TEXT NOT NULL,
    rank INTEGER,
    history_days REAL,
    closed_pnl_points INTEGER NOT NULL DEFAULT 0,
    pnl_concentration REAL,
    consistency_score REAL,
    max_drawdown_pct REAL,
    refusal_reasons_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leaderboard_shortlist_status ON leaderboard_shortlist(status);
CREATE INDEX IF NOT EXISTS idx_leaderboard_shortlist_score ON leaderboard_shortlist(score);

CREATE TABLE IF NOT EXISTS leader_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL,
    positions_json TEXT NOT NULL,
    fills_cursor TEXT,
    open_orders_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leader_snapshots_wallet ON leader_snapshots(wallet_address);

CREATE TABLE IF NOT EXISTS fill_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    fill_time TEXT,
    raw_id TEXT,
    direction TEXT,
    side TEXT,
    price REAL,
    size REAL,
    closed_pnl REAL,
    start_position REAL,
    source TEXT NOT NULL,
    collection_run_id TEXT,
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fill_snapshots_wallet ON fill_snapshots(wallet_address);
CREATE INDEX IF NOT EXISTS idx_fill_snapshots_time ON fill_snapshots(fill_time);

CREATE TABLE IF NOT EXISTS open_order_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    coin TEXT,
    captured_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fill_dedupe (
    dedupe_key TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    coin TEXT,
    fill_time TEXT,
    raw_id TEXT,
    seen_at TEXT NOT NULL
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
    spread_bps REAL NOT NULL,
    slippage_bps REAL NOT NULL,
    fee_bps REAL NOT NULL,
    latency_ms INTEGER NOT NULL,
    liquidity_score REAL NOT NULL,
    leader_score REAL NOT NULL,
    signal_freshness_score REAL NOT NULL,
    copy_degradation_bps REAL NOT NULL,
    edge_remaining_bps REAL,
    paper_mode TEXT NOT NULL,
    decision TEXT NOT NULL,
    refusal_reasons_json TEXT NOT NULL,
    raw_event_hash TEXT NOT NULL,
    source_snapshot_id TEXT,
    collection_run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_copy_signal_candidates_leader ON copy_signal_candidates(leader_wallet);
CREATE INDEX IF NOT EXISTS idx_copy_signal_candidates_decision ON copy_signal_candidates(decision);

CREATE TABLE IF NOT EXISTS no_trade_decisions (
    decision_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    observed TEXT NOT NULL,
    why_not_simulable TEXT NOT NULL,
    missing_data TEXT NOT NULL,
    next_action TEXT NOT NULL,
    leader_wallet TEXT,
    coin TEXT,
    candidate_id TEXT,
    risk_level TEXT NOT NULL DEFAULT 'INFO',
    component TEXT NOT NULL DEFAULT 'copy_mode',
    context_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_no_trade_decisions_reason ON no_trade_decisions(reason);
CREATE INDEX IF NOT EXISTS idx_no_trade_decisions_created ON no_trade_decisions(created_at);

CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    failures_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wallet_labels (
    wallet_address TEXT NOT NULL,
    label TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS explorer_events (
    event_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    block_time TEXT,
    tx_hash TEXT,
    user TEXT,
    action_type TEXT NOT NULL,
    coin TEXT,
    side TEXT,
    size REAL,
    price REAL,
    notional REAL,
    closed_pnl REAL,
    fee REAL,
    raw_json TEXT,
    confidence REAL,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_explorer_events_user ON explorer_events(user);
CREATE INDEX IF NOT EXISTS idx_explorer_events_coin ON explorer_events(coin);

CREATE TABLE IF NOT EXISTS ws_events (
    event_id TEXT PRIMARY KEY,
    stream_type TEXT NOT NULL,
    received_at TEXT NOT NULL,
    coin TEXT,
    user TEXT,
    payload_json TEXT,
    is_snapshot INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS market_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    side TEXT,
    price REAL,
    size REAL,
    timestamp TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS position_actions (
    action_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    action_type TEXT NOT NULL,
    size REAL,
    price REAL,
    closed_pnl REAL,
    fee REAL,
    timestamp TEXT NOT NULL,
    confidence REAL NOT NULL,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_position_actions_wallet ON position_actions(wallet_address);

CREATE TABLE IF NOT EXISTS position_lifecycles (
    lifecycle_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    opened_at TEXT,
    closed_at TEXT,
    realized_pnl REAL,
    fees REAL,
    actions_count INTEGER NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS smart_wallet_rankings (
    wallet_address TEXT PRIMARY KEY,
    computed_at TEXT NOT NULL,
    rank_score REAL NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    warnings_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pattern_results (
    pattern_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    pnl_association REAL,
    risk_flags_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    research_only_message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    wallet_address TEXT,
    scenario TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    net_pnl REAL,
    max_drawdown REAL,
    warnings_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    trade_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    wallet_address TEXT,
    coin TEXT,
    side TEXT,
    entry_price REAL,
    exit_price REAL,
    net_pnl REAL,
    skipped_reason TEXT
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    stopped_reason TEXT,
    warnings_json TEXT NOT NULL
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
    raw_event_hash TEXT,
    source_snapshot_id TEXT,
    collection_run_id TEXT,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leader_deltas_wallet ON leader_deltas(leader_wallet);
CREATE INDEX IF NOT EXISTS idx_leader_deltas_observed ON leader_deltas(observed_at);

CREATE TABLE IF NOT EXISTS paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    coin TEXT NOT NULL,
    size REAL NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_no_trades (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    observed TEXT NOT NULL,
    created_at TEXT NOT NULL,
    context_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    warning TEXT
);

CREATE TABLE IF NOT EXISTS audit_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_name TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    message TEXT NOT NULL
);
