"""
Leaderboard builder dYdX v4 — le "Job A" du bot viral, adapté à dYdX.

Polymarket expose un leaderboard public; dYdX v4 NON. Ce module le construit:
1. ÉNUMÉRATION  : candidats via scan Cosmos LCD + adresses déjà connues en base
2. ÉVALUATION   : pour CHAQUE candidat (pas seulement le top-5):
   - /v4/historicalPnl  → equity curve → Sharpe, max drawdown, ancienneté
   - /v4/fills          → trades clos reconstruits → winrate, profit factor
3. CLASSIFICATION: tiers stricts (selection.py) + score composite Sharpe-pondéré
4. PERSISTANCE  : snapshot SQLite par run → stabilité du rang entre runs
5. DÉMOTION     : promotion 1 tier max par run, rétrogradation immédiate

READ-ONLY / PAPER-ONLY. Endpoints publics uniquement, aucune clé privée.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Optional

from hyper_smart_observer.dydx_v4.selection import (
    AccountMetrics,
    SelectionCriteria,
    SelectionTier,
    TIER_SIZE_MULTIPLIER,
    apply_tier_transition,
    classify_account,
    composite_score,
    compute_equity_metrics,
)

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "PAPER SIMULATION ONLY. Leaderboard READ-ONLY. "
    "No real orders, no real money, no private keys."
)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS dydx_leaderboard (
    run_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    address TEXT NOT NULL,
    subaccount_number INTEGER NOT NULL DEFAULT 0,
    tier TEXT NOT NULL,
    score REAL NOT NULL,
    rank INTEGER NOT NULL,
    data_source TEXT NOT NULL DEFAULT 'REAL_INDEXER',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, address, subaccount_number)
)
"""


@dataclass
class LeaderboardEntry:
    address: str
    subaccount_number: int
    metrics: AccountMetrics
    tier: SelectionTier
    score: float
    rank: int = 0
    prev_tier: Optional[SelectionTier] = None
    prev_rank: Optional[int] = None
    size_multiplier: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def account_key(self) -> str:
        return f"{self.address}/{self.subaccount_number}"

    @property
    def copyable(self) -> bool:
        return self.tier in (SelectionTier.ELITE, SelectionTier.STANDARD)


@dataclass
class LeaderboardResult:
    run_id: str
    started_at_ms: int
    finished_at_ms: int
    candidates_evaluated: int
    entries: list[LeaderboardEntry]
    demotions: list[str] = field(default_factory=list)
    promotions: list[str] = field(default_factory=list)
    data_source: str = "REAL_INDEXER"
    disclaimer: str = DISCLAIMER

    @property
    def shortlist(self) -> list[LeaderboardEntry]:
        """Seuls les tiers copiables (ELITE + STANDARD)."""
        return [e for e in self.entries if e.copyable]


def build_trades_from_fills(fills: list[dict]) -> list[dict]:
    """
    Reconstruire les trades clos depuis les fills Indexer (FIFO par marché).
    Retourne des dicts: market, side, pnl_net, pnl_gross, fees, size,
    opened_at_ms, closed_at_ms, holding_time_ms.
    """
    def _ts(raw: str) -> int:
        try:
            import datetime as _dt
            return int(_dt.datetime.fromisoformat(
                str(raw).replace("Z", "+00:00")
            ).timestamp() * 1000)
        except Exception:
            return 0

    open_pos: dict[str, dict] = {}
    closed: list[dict] = []

    for raw in sorted(fills or [], key=lambda x: str(x.get("createdAt", ""))):
        try:
            market = str(raw.get("market", ""))
            side = str(raw.get("side", "")).upper()
            price = float(raw.get("price", 0))
            size = float(raw.get("size", 0))
            fee = float(raw.get("fee", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not market or price <= 0 or size <= 0 or side not in ("BUY", "SELL"):
            continue

        ts = _ts(raw.get("createdAt", ""))
        pos = open_pos.get(market)

        if pos is None:
            open_pos[market] = {
                "side": "LONG" if side == "BUY" else "SHORT",
                "entry_price": price, "size": size,
                "fees": fee, "opened_at_ms": ts,
            }
            continue

        same_dir = (pos["side"] == "LONG") == (side == "BUY")
        if same_dir:  # ADD → moyenne pondérée
            tot_n = pos["size"] * pos["entry_price"] + size * price
            pos["size"] += size
            pos["entry_price"] = tot_n / pos["size"] if pos["size"] > 0 else price
            pos["fees"] += fee
            continue

        # REDUCE/CLOSE
        closed_size = min(size, pos["size"])
        gross = (
            (price - pos["entry_price"]) * closed_size
            if pos["side"] == "LONG"
            else (pos["entry_price"] - price) * closed_size
        )
        part = closed_size / pos["size"] if pos["size"] > 0 else 1.0
        entry_fees_part = pos["fees"] * part
        net = gross - entry_fees_part - fee
        closed.append({
            "market": market, "side": pos["side"],
            "pnl_gross": gross, "pnl_net": net,
            "fees": entry_fees_part + fee, "size": closed_size,
            "opened_at_ms": pos["opened_at_ms"], "closed_at_ms": ts,
            "holding_time_ms": max(0, ts - pos["opened_at_ms"]),
        })
        pos["size"] -= closed_size
        pos["fees"] -= entry_fees_part
        if pos["size"] <= 1e-12:
            del open_pos[market]
        if size > closed_size:  # flip → nouvelle position dans l'autre sens
            open_pos[market] = {
                "side": "LONG" if side == "BUY" else "SHORT",
                "entry_price": price, "size": size - closed_size,
                "fees": 0.0, "opened_at_ms": ts,
            }

    return closed


def metrics_from_data(
    address: str,
    subaccount_number: int,
    fills: list[dict],
    equity_points: list[tuple[int, float]],
    data_source: str = "REAL_INDEXER",
) -> AccountMetrics:
    """Consolider fills + equity curve en AccountMetrics pour la sélection."""
    trades = build_trades_from_fills(fills)
    eq = compute_equity_metrics(equity_points)

    n = len(trades)
    wins = [t for t in trades if t["pnl_net"] > 0]
    losses = [t for t in trades if t["pnl_net"] <= 0]
    gross_win = sum(t["pnl_net"] for t in wins)
    gross_loss = abs(sum(t["pnl_net"] for t in losses))
    total_net = sum(t["pnl_net"] for t in trades)
    biggest = max((abs(t["pnl_net"]) for t in trades), default=0.0)
    denom = abs(total_net) if abs(total_net) > 1e-9 else max(biggest, 1e-9)

    # confiance données: assez de fills, courbe assez dense, historique
    conf = 0.0
    if n >= 10:
        conf += 0.4
    elif n >= 5:
        conf += 0.2
    if eq.n_points >= 30:
        conf += 0.3
    elif eq.n_points >= 7:
        conf += 0.15
    if eq.history_days >= 30:
        conf += 0.3
    elif eq.history_days >= 7:
        conf += 0.15

    return AccountMetrics(
        address=address,
        subaccount_number=subaccount_number,
        closed_trades=n,
        winrate=len(wins) / n if n else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 1e-9 else (2.0 if gross_win > 0 else 0.0),
        total_net_pnl=total_net,
        single_trade_pnl_share=min(1.0, biggest / denom) if n else 1.0,
        sharpe=eq.sharpe,
        max_drawdown_pct=eq.max_drawdown_pct,
        history_days=eq.history_days,
        data_confidence=min(1.0, conf),
        data_source=data_source,
    )


def parse_historical_pnl(raw: dict) -> list[tuple[int, float]]:
    """Parse /v4/historicalPnl → [(ts_ms, equity)]."""
    points: list[tuple[int, float]] = []
    for tick in (raw or {}).get("historicalPnl", []) or []:
        try:
            import datetime as _dt
            ts = int(_dt.datetime.fromisoformat(
                str(tick.get("createdAt", "")).replace("Z", "+00:00")
            ).timestamp() * 1000)
            eq = float(tick.get("equity", 0))
            if eq != 0 or points:
                points.append((ts, eq))
        except (TypeError, ValueError):
            continue
    return points


class DydxLeaderboardBuilder:
    """
    Construit le leaderboard. `rest` doit exposer get_historical_pnl() et
    paginate_fills(); `cosmos` (optionnel) scan_subaccounts().
    """

    def __init__(
        self,
        rest: Any,
        cosmos: Any = None,
        db_path: Optional[str] = None,
        criteria: Optional[SelectionCriteria] = None,
        rate_limit_sleep_s: float = 0.25,
        data_source: str = "REAL_INDEXER",
    ) -> None:
        self.rest = rest
        self.cosmos = cosmos
        self.db_path = db_path
        self.criteria = criteria or SelectionCriteria()
        self.rate_limit_sleep_s = rate_limit_sleep_s
        self.data_source = data_source

    # ------------------------------------------------------------------ #
    # Énumération
    # ------------------------------------------------------------------ #
    def enumerate_candidates(
        self,
        max_scan_pages: int = 5,
        min_usdc: float = 500.0,
        extra_addresses: Optional[list[tuple[str, int]]] = None,
    ) -> list[tuple[str, int]]:
        """Candidats = scan on-chain + adresses connues en base + seeds."""
        seen: dict[tuple[str, int], None] = {}

        for addr, sub in extra_addresses or []:
            seen[(addr, int(sub))] = None

        for addr, sub in self._known_addresses():
            seen[(addr, sub)] = None

        if self.cosmos is not None:
            try:
                subs = self.cosmos.scan_subaccounts(
                    max_pages=max_scan_pages, page_size=100,
                    min_usdc=min_usdc, only_with_positions=True,
                )
                for s in subs:
                    addr = getattr(s, "address", None) or (s.get("address") if isinstance(s, dict) else None)
                    num = getattr(s, "subaccount_number", 0) if not isinstance(s, dict) else s.get("subaccount_number", 0)
                    if addr:
                        seen[(str(addr), int(num or 0))] = None
            except Exception as e:
                logger.warning("Leaderboard: scan Cosmos indisponible: %s", e)

        return list(seen)

    def _known_addresses(self) -> list[tuple[str, int]]:
        if not self.db_path:
            return []
        try:
            with closing(sqlite3.connect(self.db_path)) as db:
                db.execute(_TABLE_SQL)
                rows = db.execute(
                    "SELECT DISTINCT address, subaccount_number FROM dydx_leaderboard"
                ).fetchall()
            return [(r[0], int(r[1])) for r in rows]
        except sqlite3.Error as e:
            logger.warning("Leaderboard: lecture adresses connues: %s", e)
            return []

    # ------------------------------------------------------------------ #
    # Évaluation
    # ------------------------------------------------------------------ #
    def evaluate_candidate(self, address: str, sub: int) -> Optional[AccountMetrics]:
        """historicalPnl + fills → AccountMetrics. None si données inaccessibles."""
        try:
            pnl_raw = self.rest.get_historical_pnl(
                address=address, subaccount_number=sub
            )
            equity_points = parse_historical_pnl(pnl_raw)
        except Exception as e:
            logger.debug("historicalPnl KO %s/%d: %s", address, sub, e)
            equity_points = []

        try:
            fills = self.rest.paginate_fills(
                address=address, subaccount_number=sub,
                max_pages=5, page_size=100,
            )
        except Exception as e:
            logger.debug("fills KO %s/%d: %s", address, sub, e)
            fills = []

        if not fills and not equity_points:
            return None
        return metrics_from_data(address, sub, fills, equity_points, self.data_source)

    # ------------------------------------------------------------------ #
    # Build complet
    # ------------------------------------------------------------------ #
    def build(
        self,
        max_candidates: int = 100,
        max_scan_pages: int = 5,
        extra_addresses: Optional[list[tuple[str, int]]] = None,
    ) -> LeaderboardResult:
        started = int(time.time() * 1000)
        run_id = hashlib.sha256(f"lb:{started}".encode()).hexdigest()[:16]
        prev = self._load_previous()

        candidates = self.enumerate_candidates(
            max_scan_pages=max_scan_pages, extra_addresses=extra_addresses
        )[:max_candidates]
        logger.info("Leaderboard %s: %d candidats | %s", run_id, len(candidates), DISCLAIMER)

        entries: list[LeaderboardEntry] = []
        promotions: list[str] = []
        demotions: list[str] = []

        for i, (addr, sub) in enumerate(candidates):
            metrics = self.evaluate_candidate(addr, sub)
            if metrics is None:
                continue

            decision = classify_account(metrics, self.criteria)
            prev_tier, prev_rank = prev.get((addr, sub), (None, None))
            final_tier = apply_tier_transition(prev_tier, decision.tier)

            key = f"{addr}/{sub}"
            if prev_tier is not None and final_tier != prev_tier:
                from hyper_smart_observer.dydx_v4.selection import _TIER_ORDER
                if _TIER_ORDER[final_tier] > _TIER_ORDER[prev_tier]:
                    promotions.append(f"{key}: {prev_tier}→{final_tier}")
                else:
                    demotions.append(f"{key}: {prev_tier}→{final_tier}")

            entries.append(LeaderboardEntry(
                address=addr,
                subaccount_number=sub,
                metrics=metrics,
                tier=final_tier,
                score=composite_score(metrics),
                prev_tier=prev_tier,
                prev_rank=prev_rank,
                size_multiplier=TIER_SIZE_MULTIPLIER[final_tier],
                reasons=decision.reasons,
            ))

            if self.rate_limit_sleep_s > 0 and i < len(candidates) - 1:
                time.sleep(self.rate_limit_sleep_s)

        entries.sort(key=lambda e: e.score, reverse=True)
        for rank, e in enumerate(entries, start=1):
            e.rank = rank

        result = LeaderboardResult(
            run_id=run_id,
            started_at_ms=started,
            finished_at_ms=int(time.time() * 1000),
            candidates_evaluated=len(candidates),
            entries=entries,
            demotions=demotions,
            promotions=promotions,
            data_source=self.data_source,
        )
        self.persist(result)
        logger.info(
            "Leaderboard %s DONE: %d évalués, %d copiables (ELITE+STANDARD), "
            "%d promotions, %d démotions",
            run_id, len(entries), len(result.shortlist),
            len(promotions), len(demotions),
        )
        return result

    # ------------------------------------------------------------------ #
    # Persistance
    # ------------------------------------------------------------------ #
    def persist(self, result: LeaderboardResult) -> None:
        if not self.db_path:
            return
        try:
            with closing(sqlite3.connect(self.db_path)) as db:
                db.execute(_TABLE_SQL)
                for e in result.entries:
                    db.execute(
                        "INSERT OR REPLACE INTO dydx_leaderboard "
                        "(run_id, ts_ms, address, subaccount_number, tier, score, "
                        " rank, data_source, metrics_json) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            result.run_id, result.finished_at_ms, e.address,
                            e.subaccount_number, e.tier.value, e.score, e.rank,
                            e.metrics.data_source,
                            json.dumps({
                                "closed_trades": e.metrics.closed_trades,
                                "winrate": round(e.metrics.winrate, 4),
                                "profit_factor": round(e.metrics.profit_factor, 4),
                                "sharpe": round(e.metrics.sharpe, 4),
                                "max_drawdown_pct": round(e.metrics.max_drawdown_pct, 2),
                                "history_days": round(e.metrics.history_days, 1),
                                "total_net_pnl": round(e.metrics.total_net_pnl, 4),
                            }),
                        ),
                    )
                db.commit()
        except sqlite3.Error as e:
            logger.error("Leaderboard persist KO: %s", e)

    def _load_previous(self) -> dict[tuple[str, int], tuple[SelectionTier, int]]:
        """Tier + rang du dernier run (pour transition et stabilité)."""
        if not self.db_path:
            return {}
        try:
            with closing(sqlite3.connect(self.db_path)) as db:
                db.execute(_TABLE_SQL)
                row = db.execute(
                    "SELECT run_id FROM dydx_leaderboard ORDER BY ts_ms DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return {}
                rows = db.execute(
                    "SELECT address, subaccount_number, tier, rank "
                    "FROM dydx_leaderboard WHERE run_id = ?", (row[0],)
                ).fetchall()
            out: dict[tuple[str, int], tuple[SelectionTier, int]] = {}
            for addr, sub, tier, rank in rows:
                try:
                    out[(addr, int(sub))] = (SelectionTier(tier), int(rank))
                except ValueError:
                    continue
            return out
        except sqlite3.Error as e:
            logger.warning("Leaderboard load_previous KO: %s", e)
            return {}

    def export_shortlist_json(self, result: LeaderboardResult, path: str) -> None:
        """Exporter la shortlist copiable (consommée par l'observer)."""
        payload = {
            "run_id": result.run_id,
            "generated_at_ms": result.finished_at_ms,
            "data_source": result.data_source,
            "disclaimer": result.disclaimer,
            "shortlist": [
                {
                    "address": e.address,
                    "subaccount_number": e.subaccount_number,
                    "tier": e.tier.value,
                    "score": e.score,
                    "rank": e.rank,
                    "size_multiplier": e.size_multiplier,
                }
                for e in result.shortlist
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
