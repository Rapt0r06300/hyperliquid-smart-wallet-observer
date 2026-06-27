"""
Stockage SQLite dYdX v4 — WAL, busy_timeout, déduplication.

Relançable sans dupliquer les données.
Tables séparées par mode (LIVE vs BACKTEST vs REPLAY vs TEST_FIXTURE).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# Schéma SQL complet
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=60000;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;

-- Métadonnées réseau
CREATE TABLE IF NOT EXISTS dydx_networks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network TEXT NOT NULL UNIQUE,
    rest_url TEXT NOT NULL,
    ws_url TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL
);

-- Marchés
CREATE TABLE IF NOT EXISTS dydx_markets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    base_asset TEXT,
    quote_asset TEXT,
    tick_size REAL,
    step_size REAL,
    min_order_size REAL,
    oracle_price REAL,
    mid_price REAL,
    best_bid REAL,
    best_ask REAL,
    spread_bps REAL,
    volume_24h REAL,
    open_interest REAL,
    is_active INTEGER DEFAULT 1,
    updated_at_ms INTEGER NOT NULL,
    raw_json TEXT,
    UNIQUE(market_id, network)
);

-- Comptes
CREATE TABLE IF NOT EXISTS dydx_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL,
    network TEXT NOT NULL,
    subaccount_count INTEGER DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE(address, network)
);

-- Subaccounts
CREATE TABLE IF NOT EXISTS dydx_subaccounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    network TEXT NOT NULL,
    equity REAL DEFAULT 0,
    free_collateral REAL DEFAULT 0,
    margin_usage REAL DEFAULT 0,
    leverage REAL DEFAULT 0,
    updated_at_ms INTEGER NOT NULL,
    raw_json TEXT,
    UNIQUE(account_address, subaccount_number, network)
);

-- Réponses REST brutes (pour replay/audit)
CREATE TABLE IF NOT EXISTS dydx_raw_rest_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    params_json TEXT,
    response_json TEXT NOT NULL,
    status_code INTEGER,
    received_at_ms INTEGER NOT NULL,
    network TEXT NOT NULL
);

-- Messages WS bruts
CREATE TABLE IF NOT EXISTS dydx_raw_ws_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    msg_type TEXT NOT NULL,
    channel_id TEXT,
    data_json TEXT NOT NULL,
    received_at_ms INTEGER NOT NULL,
    network TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ws_channel ON dydx_raw_ws_messages(channel, received_at_ms);

-- Ordres
CREATE TABLE IF NOT EXISTS dydx_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    status TEXT NOT NULL,
    order_type TEXT,
    time_in_force TEXT,
    total_filled REAL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    raw_json TEXT,
    UNIQUE(order_id, network)
);

-- Fills
CREATE TABLE IF NOT EXISTS dydx_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id TEXT NOT NULL,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL,
    fee_bps REAL,
    liquidity TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    order_id TEXT,
    raw_json TEXT,
    UNIQUE(fill_id, network)
);
CREATE INDEX IF NOT EXISTS idx_fills_account ON dydx_fills(account_address, subaccount_number, market_id, created_at_ms);

-- Trades publics
CREATE TABLE IF NOT EXISTS dydx_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    trade_type TEXT,
    created_at_ms INTEGER NOT NULL,
    raw_json TEXT,
    UNIQUE(trade_id, network)
);

-- Positions
CREATE TABLE IF NOT EXISTS dydx_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_key TEXT NOT NULL,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    entry_price REAL NOT NULL,
    mark_price REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    net_funding REAL DEFAULT 0,
    leverage REAL DEFAULT 0,
    liquidation_price REAL,
    opened_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    raw_json TEXT,
    UNIQUE(position_key, network)
);

-- Snapshots de positions (pour reconstruction)
CREATE TABLE IF NOT EXISTS dydx_position_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_key TEXT NOT NULL,
    network TEXT NOT NULL,
    size REAL NOT NULL,
    mark_price REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    snapshot_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_key ON dydx_position_snapshots(position_key, snapshot_at_ms);

-- Deltas de positions
CREATE TABLE IF NOT EXISTS dydx_position_deltas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    size_delta REAL NOT NULL,
    price REAL NOT NULL,
    fill_id TEXT,
    timestamp_ms INTEGER NOT NULL,
    raw_json TEXT
);

-- Événements lifecycle
CREATE TABLE IF NOT EXISTS dydx_lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_key TEXT NOT NULL,
    network TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    size_before REAL,
    size_after REAL,
    price REAL,
    fill_id TEXT,
    simulation_mode TEXT NOT NULL DEFAULT 'live',
    timestamp_ms INTEGER NOT NULL
);

-- Scores accounts/subaccounts
CREATE TABLE IF NOT EXISTS dydx_wallet_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    network TEXT NOT NULL,
    pnl_net REAL DEFAULT 0,
    winrate REAL DEFAULT 0,
    profit_factor REAL DEFAULT 0,
    expectancy REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    regularity REAL DEFAULT 0,
    recency_score REAL DEFAULT 0,
    volume_score REAL DEFAULT 0,
    copyability REAL DEFAULT 0,
    data_confidence REAL DEFAULT 0,
    composite_score REAL DEFAULT 0,
    computed_at_ms INTEGER NOT NULL,
    UNIQUE(account_address, subaccount_number, network)
);

-- Shortlist
CREATE TABLE IF NOT EXISTS dydx_shortlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    network TEXT NOT NULL,
    score REAL NOT NULL,
    reason TEXT,
    added_at_ms INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE(account_address, subaccount_number, network)
);

-- Candidats signaux
CREATE TABLE IF NOT EXISTS dydx_signal_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL UNIQUE,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    signal_age_ms INTEGER NOT NULL,
    edge_remaining_bps REAL NOT NULL,
    total_cost_bps REAL NOT NULL,
    source TEXT NOT NULL,
    simulation_mode TEXT NOT NULL DEFAULT 'live',
    score REAL DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    notes_json TEXT
);

-- Décisions NO_TRADE
CREATE TABLE IF NOT EXISTS dydx_no_trade_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    signal_candidate_id TEXT,
    account_address TEXT,
    market_id TEXT,
    network TEXT,
    detail TEXT,
    simulation_mode TEXT NOT NULL DEFAULT 'live',
    timestamp_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_no_trade_reason ON dydx_no_trade_decisions(reason, timestamp_ms);

-- Paper trades
CREATE TABLE IF NOT EXISTS dydx_paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL UNIQUE,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    entry_price REAL NOT NULL,
    mark_price REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'OPEN',
    lifecycle TEXT NOT NULL,
    gross_pnl REAL DEFAULT 0,
    net_pnl REAL DEFAULT 0,
    fees REAL DEFAULT 0,
    spread_cost REAL DEFAULT 0,
    slippage_cost REAL DEFAULT 0,
    entry_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    closed_at_ms INTEGER,
    close_reason TEXT,
    simulation_mode TEXT NOT NULL DEFAULT 'live',
    signal_id TEXT,
    notes_json TEXT
);

-- Positions paper
CREATE TABLE IF NOT EXISTS dydx_paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_key TEXT NOT NULL UNIQUE,
    account_address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    network TEXT NOT NULL,
    side TEXT NOT NULL,
    size REAL NOT NULL,
    entry_price REAL NOT NULL,
    current_mark_price REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    total_fees REAL DEFAULT 0,
    opened_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    simulation_mode TEXT NOT NULL DEFAULT 'live',
    trade_ids_json TEXT
);

-- Runs backtest
CREATE TABLE IF NOT EXISTS dydx_backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    network TEXT NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    gross_pnl REAL DEFAULT 0,
    net_pnl REAL DEFAULT 0,
    total_fees REAL DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    winrate REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    config_json TEXT,
    created_at_ms INTEGER NOT NULL
);

-- Health
CREATE TABLE IF NOT EXISTS dydx_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT NOT NULL,
    network TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    checked_at_ms INTEGER NOT NULL
);

-- Audit sécurité
CREATE TABLE IF NOT EXISTS dydx_safety_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_name TEXT NOT NULL,
    passed INTEGER NOT NULL DEFAULT 1,
    detail TEXT,
    audited_at_ms INTEGER NOT NULL
);
"""


class DydxStorage:
    """Stockage SQLite dYdX v4 — thread-safe, relançable, dédupliqué."""

    def __init__(self, db_path: str = "data/dydx_v4.sqlite3", network: str = "testnet") -> None:
        self.db_path = db_path
        self.network = network
        self._setup_db()

    def _setup_db(self) -> None:
        """Créer le répertoire et initialiser le schéma."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("dYdX storage initialisé: %s", self.db_path)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            self.db_path,
            timeout=60,
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    # ----------------------------------------------------------------------- #
    # Marchés
    # ----------------------------------------------------------------------- #

    def upsert_market(self, market: "NormalizedMarket") -> None:  # noqa: F821
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO dydx_markets
                    (market_id, network, base_asset, quote_asset, tick_size, step_size,
                     min_order_size, oracle_price, mid_price, best_bid, best_ask,
                     spread_bps, volume_24h, open_interest, is_active, updated_at_ms, raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(market_id, network) DO UPDATE SET
                    oracle_price=excluded.oracle_price,
                    mid_price=excluded.mid_price,
                    best_bid=excluded.best_bid,
                    best_ask=excluded.best_ask,
                    spread_bps=excluded.spread_bps,
                    volume_24h=excluded.volume_24h,
                    open_interest=excluded.open_interest,
                    is_active=excluded.is_active,
                    updated_at_ms=excluded.updated_at_ms,
                    raw_json=excluded.raw_json
                """,
                (
                    market.market_id, self.network,
                    market.base_asset, market.quote_asset,
                    market.tick_size, market.step_size,
                    market.min_order_size, market.oracle_price,
                    market.mid_price, market.best_bid, market.best_ask,
                    market.spread_bps, market.volume_24h, market.open_interest,
                    1 if market.is_active else 0,
                    market.updated_at_ms,
                    json.dumps(market.raw),
                ),
            )

    # ----------------------------------------------------------------------- #
    # Fills (avec déduplication par fill_id)
    # ----------------------------------------------------------------------- #

    def insert_fill(self, fill: "NormalizedFill") -> bool:  # noqa: F821
        """Insérer un fill. Retourne True si nouveau, False si dupliqué."""
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO dydx_fills
                        (fill_id, account_address, subaccount_number, market_id, network,
                         side, size, price, fee, fee_bps, liquidity, created_at_ms, order_id, raw_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fill.fill_id, fill.account_address, fill.subaccount_number,
                        fill.market_id, self.network, fill.side.value,
                        fill.size, fill.price, fill.fee, fill.fee_bps,
                        fill.liquidity, fill.created_at_ms, fill.order_id,
                        json.dumps(fill.raw),
                    ),
                )
                return True
        except sqlite3.IntegrityError:
            return False  # Dupliqué — ignorer

    def get_latest_fill_ms(self, address: str, subaccount_number: int) -> Optional[int]:
        """Récupérer le timestamp du dernier fill connu (pour cursor de pagination)."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT MAX(created_at_ms) FROM dydx_fills
                WHERE account_address=? AND subaccount_number=? AND network=?
                """,
                (address, subaccount_number, self.network),
            ).fetchone()
            return row[0] if row and row[0] else None

    # ----------------------------------------------------------------------- #
    # Paper trades
    # ----------------------------------------------------------------------- #

    def insert_paper_trade(self, trade: "PaperTrade") -> None:  # noqa: F821
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dydx_paper_trades
                    (trade_id, account_address, subaccount_number, market_id, network,
                     side, size, entry_price, mark_price, status, lifecycle,
                     gross_pnl, net_pnl, fees, spread_cost, slippage_cost,
                     entry_at_ms, updated_at_ms, closed_at_ms, close_reason,
                     simulation_mode, signal_id, notes_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trade.trade_id, trade.account_address, trade.subaccount_number,
                    trade.market_id, self.network, trade.side.value,
                    trade.size, trade.entry_price, trade.mark_price,
                    trade.status.value, trade.lifecycle.value,
                    trade.gross_pnl, trade.net_pnl, trade.fees,
                    trade.spread_cost, trade.slippage_cost,
                    trade.entry_at_ms, trade.updated_at_ms, trade.closed_at_ms,
                    trade.close_reason, trade.simulation_mode.value,
                    trade.signal_id, json.dumps(trade.notes),
                ),
            )

    def get_open_paper_trades(self, simulation_mode: str = "live") -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM dydx_paper_trades
                WHERE status='OPEN' AND simulation_mode=? AND network=?
                ORDER BY entry_at_ms DESC
                """,
                (simulation_mode, self.network),
            ).fetchall()
            return [dict(r) for r in rows]

    # ----------------------------------------------------------------------- #
    # No-trade decisions
    # ----------------------------------------------------------------------- #

    def insert_no_trade(self, decision: "NoTradeDecision") -> None:  # noqa: F821
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO dydx_no_trade_decisions
                    (decision_id, reason, signal_candidate_id, account_address,
                     market_id, network, detail, simulation_mode, timestamp_ms)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision.decision_id, decision.reason.value,
                    decision.signal_candidate_id, decision.account_address,
                    decision.market_id, self.network, decision.detail,
                    decision.simulation_mode.value, decision.timestamp_ms,
                ),
            )

    # ----------------------------------------------------------------------- #
    # Signaux candidats
    # ----------------------------------------------------------------------- #

    def insert_signal_candidate(self, signal: "SignalCandidate") -> None:  # noqa: F821
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO dydx_signal_candidates
                    (signal_id, account_address, subaccount_number, market_id, network,
                     side, lifecycle, size, price, signal_age_ms, edge_remaining_bps,
                     total_cost_bps, source, simulation_mode, score, created_at_ms, notes_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    signal.signal_id, signal.account_address, signal.subaccount_number,
                    signal.market_id, self.network, signal.side.value,
                    signal.lifecycle.value, signal.size, signal.price,
                    signal.signal_age_ms, signal.edge_remaining_bps,
                    signal.total_cost_bps, signal.source,
                    signal.simulation_mode.value, signal.score,
                    signal.created_at_ms, json.dumps(signal.notes),
                ),
            )

    # ----------------------------------------------------------------------- #
    # Health
    # ----------------------------------------------------------------------- #

    def record_health(self, component: str, status: str, detail: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO dydx_health (component, network, status, detail, checked_at_ms)
                VALUES (?,?,?,?,?)
                """,
                (component, self.network, status, detail, int(time.time() * 1000)),
            )

    def get_stats(self) -> dict:
        """Statistiques des tables principales."""
        tables = [
            "dydx_markets", "dydx_fills", "dydx_positions",
            "dydx_signal_candidates", "dydx_no_trade_decisions",
            "dydx_paper_trades", "dydx_wallet_scores", "dydx_shortlist",
        ]
        stats: dict[str, int] = {}
        with self._conn() as conn:
            for t in tables:
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {t} WHERE network=?", (self.network,)).fetchone()
                    stats[t] = row[0] if row else 0
                except Exception:
                    stats[t] = -1
        return stats
