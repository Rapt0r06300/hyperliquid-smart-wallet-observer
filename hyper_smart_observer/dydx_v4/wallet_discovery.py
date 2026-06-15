"""
Découverte et scoring de wallets dYdX v4.

Basé sur l'analyse de 1,482,013 events Hyperliquid:
- ETH-USD = seul coin prouvé rentable (+$9.07 net), signal age moyen 3s
- Signal frais (<4s) = critique pour éviter NO_MATCHING refusals (47%% des refus)
- 1-2 wallets de qualité > 7 wallets stale (winrate: 41%% vs 10%%)

READ-ONLY. Aucun ordre. Aucune clé privée.
"""

from __future__ import annotations

import logging
import time
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from hyper_smart_observer.dydx_v4.cosmos_client import (
    DydxCosmosLcdClient,
    OnChainSubaccount,
    LIQUID_MARKETS,
)
from hyper_smart_observer.dydx_v4.rest_client import DydxIndexerRestClient, RestError
from hyper_smart_observer.dydx_v4.leader_quality import score_trades_by_market
from hyper_smart_observer.dydx_v4.scoring import compute_account_score, TradeRecord

logger = logging.getLogger(__name__)

PRIORITY_MARKETS = ["ETH-USD", "BTC-USD", "SOL-USD", "TIA-USD"]

BLOCKED_MARKETS = frozenset([
    "CASH:WTI", "CASH:TSLA", "CASH:SILVER", "CASH:GOLD",
    "XYZ:CL", "XYZ:AMD", "XYZ:ORCL", "HYPE", "ZEC",
])

MARKET_PRIORITY_SCORE = {
    "ETH-USD": 1.0, "BTC-USD": 0.8, "SOL-USD": 0.6, "TIA-USD": 0.5,
    "AVAX-USD": 0.4, "BNB-USD": 0.4, "ARB-USD": 0.3, "OP-USD": 0.3,
}


@dataclass
class WalletScore:
    address: str
    subaccount_number: int = 0
    usdc_balance: float = 0.0
    open_positions: list[dict] = field(default_factory=list)
    total_score: float = 0.0
    net_pnl_usdc: float = 0.0
    winrate: float = 0.0
    profit_factor: float = 1.0
    trade_count: int = 0
    recent_score: float = 0.0
    market_stats: dict[str, dict] = field(default_factory=dict)
    market_priority_score: float = 0.0
    balance_score: float = 0.0
    position_count_score: float = 0.0
    freshness_score: float = 1.0
    discovered_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    last_updated_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    source: str = "cosmos_lcd"
    note: str = ""


@dataclass
class DiscoveryResult:
    run_id: str
    started_at_ms: int
    finished_at_ms: int
    candidates_scanned: int
    shortlisted: list[WalletScore]
    discovery_method: str = "cosmos_lcd"
    disclaimer: str = (
        "PAPER SIMULATION ONLY. Wallet discovery is READ-ONLY. "
        "No real orders, no real money, no private keys."
    )


# ---------------------------------------------------------------------------
# Wallets synthétiques pour le mode démo (aucun réseau requis)
# ---------------------------------------------------------------------------
_DEMO_WALLET_SPECS = [
    # ALPHA, BETA, GAMMA partagent tous ETH-USD LONG + BTC-USD LONG
    # → detect_clusters(min_wallets=2) détecte 2 clusters dès le tick 1
    {
        "address": "dydx1qjfsuqfpjqfsuqfpjqfsuqfpjqfsuqfpjfaa",
        "label": "DEMO-ALPHA",
        "markets": [
            {"market": "ETH-USD", "side": "LONG", "notional": 15000},
            {"market": "BTC-USD", "side": "LONG", "notional": 8000},
        ],
        "balance": 50000,
        "winrate": 0.61,
        "profit_factor": 1.85,
        "score": 0.82,
    },
    {
        "address": "dydx1rjfsuqfpjqfsuqfpjqfsuqfpjqfsuqfpjfbb",
        "label": "DEMO-BETA",
        # BUG FIX: était ETH SHORT + SOL LONG → aucun overlap possible
        "markets": [
            {"market": "ETH-USD", "side": "LONG", "notional": 12000},
            {"market": "BTC-USD", "side": "LONG", "notional": 10000},
        ],
        "balance": 40000,
        "winrate": 0.58,
        "profit_factor": 1.65,
        "score": 0.75,
    },
    {
        "address": "dydx1sjfsuqfpjqfsuqfpjqfsuqfpjqfsuqfpjfcc",
        "label": "DEMO-GAMMA",
        # BUG FIX: était BTC SHORT → aucun overlap avec ALPHA
        "markets": [
            {"market": "BTC-USD", "side": "LONG", "notional": 20000},
            {"market": "ETH-USD", "side": "LONG", "notional": 10000},
            {"market": "SOL-USD", "side": "LONG", "notional": 5000},
        ],
        "balance": 80000,
        "winrate": 0.63,
        "profit_factor": 1.95,
        "score": 0.85,
    },
    {
        "address": "dydx1tjfsuqfpjqfsuqfpjqfsuqfpjqfsuqfpjfdd",
        "label": "DEMO-DELTA",
        # Wallet 4: SOL + AVAX → clusters SOL (w/ GAMMA) et AVAX diversifiés
        "markets": [
            {"market": "SOL-USD", "side": "LONG", "notional": 8000},
            {"market": "AVAX-USD", "side": "LONG", "notional": 6000},
            {"market": "BNB-USD", "side": "LONG", "notional": 5000},
        ],
        "balance": 60000,
        "winrate": 0.59,
        "profit_factor": 1.70,
        "score": 0.78,
    },
]


def _build_demo_wallets() -> list[WalletScore]:
    """Construit des WalletScore synthétiques pour la simulation démo."""
    result = []
    for spec in _DEMO_WALLET_SPECS:
        ws = WalletScore(
            address=spec["address"],
            subaccount_number=0,
            usdc_balance=float(spec["balance"]),
            open_positions=[
                {"market": m["market"], "side": m["side"], "notional": m["notional"]}
                for m in spec["markets"]
            ],
            balance_score=min(1.0, spec["balance"] / 100_000),
            market_priority_score=0.8,
            position_count_score=min(1.0, len(spec["markets"]) / 3),
            total_score=spec["score"],
            winrate=spec["winrate"],
            profit_factor=spec["profit_factor"],
            net_pnl_usdc=spec["balance"] * 0.12,  # ~12% PnL démo
            trade_count=30,
            note=f"[{spec['label']}] demo_synthetic",
            source="demo_synthetic",
        )
        result.append(ws)
    return result


class DydxWalletDiscovery:
    """
    Découverte et scoring de wallets dYdX v4.
    READ-ONLY. Pas d'ordre. Pas de clé privée.
    """

    DISCLAIMER = (
        "WALLET DISCOVERY: READ-ONLY. No orders. No real money. Paper simulation."
    )

    def __init__(
        self,
        cosmos_client: DydxCosmosLcdClient,
        rest_client: DydxIndexerRestClient,
        min_usdc_balance: float = 1_000.0,
        max_scan_pages: int = 10,
        demo_mode: bool = False,
    ) -> None:
        self.cosmos = cosmos_client
        self.rest = rest_client
        self.min_usdc = min_usdc_balance
        self.max_scan_pages = max_scan_pages
        self._demo_mode = demo_mode

    def fast_discover(self, n: int = 20) -> DiscoveryResult:
        """Découverte rapide < 10s. Paper-only. Aucun ordre.

        Si demo_mode=True ou si Cosmos LCD renvoie 0 candidats,
        injecte des wallets synthétiques pour que la simulation reste active.
        """
        import hashlib
        started = int(time.time() * 1000)
        run_id = hashlib.sha256(f"fast:{started}".encode()).hexdigest()[:16]
        logger.info("fast_discover START run_id=%s n=%d demo=%s", run_id, n, self._demo_mode)

        if self._demo_mode:
            # Mode démo: retourner des wallets synthétiques immédiatement
            shortlist = _build_demo_wallets()
            finished = int(time.time() * 1000)
            logger.info("fast_discover DEMO: %d wallets synthétiques", len(shortlist))
            return DiscoveryResult(
                run_id=run_id, started_at_ms=started, finished_at_ms=finished,
                candidates_scanned=0, shortlisted=shortlist,
                discovery_method="demo_synthetic",
            )

        candidates = []
        try:
            candidates = self.cosmos.scan_subaccounts(
                max_pages=60, page_size=100, min_usdc=250.0, only_with_positions=True,
            )
        except Exception as e:
            logger.warning("Cosmos LCD unavailable: %s — activating demo mode", e)
            self._demo_mode = True
            shortlist = _build_demo_wallets()
            finished = int(time.time() * 1000)
            logger.info("fast_discover DEMO (fallback): %d wallets synthétiques", len(shortlist))
            return DiscoveryResult(
                run_id=run_id, started_at_ms=started, finished_at_ms=finished,
                candidates_scanned=0, shortlisted=shortlist,
                discovery_method="demo_synthetic_fallback",
            )

        logger.info("fast_discover scan: %d candidats", len(candidates))

        scored = []
        for sub in candidates:
            ws = self._score_wallet(sub)
            if ws.total_score > 0:
                scored.append(ws)

        scored.sort(key=lambda x: x.total_score, reverse=True)
        for ws in scored[:20]:
            self._enrich_with_indexer(ws)
        scored.sort(key=lambda x: x.total_score, reverse=True)
        shortlist = scored[:n]

        # Fallback démo si aucun wallet réel trouvé
        if not shortlist:
            logger.warning("fast_discover: 0 wallets réels — injection démo synthétique")
            shortlist = _build_demo_wallets()
            self._demo_mode = True
            discovery_method = "demo_synthetic_fallback"
        else:
            discovery_method = "fast_cosmos_lcd"

        finished = int(time.time() * 1000)
        logger.info(
            "fast_discover DONE: %d wallets en %.1fs | %s",
            len(shortlist), (finished - started) / 1000, self.DISCLAIMER,
        )
        return DiscoveryResult(
            run_id=run_id, started_at_ms=started, finished_at_ms=finished,
            candidates_scanned=len(candidates), shortlisted=shortlist,
            discovery_method=discovery_method,
        )

    async def fast_discover_async(
        self,
        n: int = 20,
        *,
        max_candidates: int = 500,
        concurrency: int = 10,
    ) -> DiscoveryResult:
        """
        Variante async bornée du scan rapide.

        READ-ONLY/PAPER-ONLY. Le scan Cosmos reste appelé via thread pour garder
        la compatibilité avec le client existant; le scoring/enrichment est
        parallélisé avec un sémaphore strict afin d'éviter les rafales réseau.
        """
        import hashlib

        started = int(time.time() * 1000)
        run_id = hashlib.sha256(f"fast-async:{started}".encode()).hexdigest()[:16]
        if self._demo_mode:
            shortlist = _build_demo_wallets()[:n]
            finished = int(time.time() * 1000)
            return DiscoveryResult(
                run_id=run_id,
                started_at_ms=started,
                finished_at_ms=finished,
                candidates_scanned=0,
                shortlisted=shortlist,
                discovery_method="demo_synthetic_async",
            )

        try:
            candidates = await asyncio.to_thread(
                self.cosmos.scan_subaccounts,
                max_pages=60,
                page_size=100,
                min_usdc=250.0,
                only_with_positions=True,
            )
        except Exception as e:
            logger.warning("Cosmos LCD unavailable async: %s — activating demo mode", e)
            self._demo_mode = True
            shortlist = _build_demo_wallets()[:n]
            finished = int(time.time() * 1000)
            return DiscoveryResult(
                run_id=run_id,
                started_at_ms=started,
                finished_at_ms=finished,
                candidates_scanned=0,
                shortlisted=shortlist,
                discovery_method="demo_synthetic_async_fallback",
            )

        candidates = list(candidates or [])[:max(1, max_candidates)]
        shortlist = await self._score_candidates_async(candidates, n=n, concurrency=concurrency)
        finished = int(time.time() * 1000)
        return DiscoveryResult(
            run_id=run_id,
            started_at_ms=started,
            finished_at_ms=finished,
            candidates_scanned=len(candidates),
            shortlisted=shortlist,
            discovery_method="fast_cosmos_lcd_async",
        )

    async def _score_candidates_async(
        self,
        candidates: list[OnChainSubaccount],
        *,
        n: int,
        concurrency: int = 10,
    ) -> list[WalletScore]:
        """Scorer jusqu'à N candidats avec concurrence bornée."""
        sem = asyncio.Semaphore(max(1, int(concurrency)))

        async def _score_one(sub: OnChainSubaccount) -> Optional[WalletScore]:
            async with sem:
                try:
                    ws = await asyncio.to_thread(self._score_wallet, sub)
                    return ws if ws.total_score > 0 else None
                except Exception as e:
                    logger.debug("async score wallet skipped: %s", e)
                    return None

        scored_raw = await asyncio.gather(*(_score_one(sub) for sub in candidates))
        scored = [w for w in scored_raw if w is not None]
        scored.sort(key=lambda x: x.total_score, reverse=True)

        enrich_sem = asyncio.Semaphore(max(1, min(int(concurrency), 10)))

        async def _enrich(ws: WalletScore) -> WalletScore:
            async with enrich_sem:
                try:
                    await asyncio.to_thread(self._enrich_with_indexer, ws)
                except Exception as e:
                    logger.debug("async enrich wallet skipped: %s", e)
                return ws

        top_for_enrich = scored[: min(50, len(scored))]
        if top_for_enrich:
            await asyncio.gather(*(_enrich(ws) for ws in top_for_enrich))
        scored.sort(key=lambda x: x.total_score, reverse=True)
        return scored[:n]

    def discover_top_wallets(self, n: int = 20) -> DiscoveryResult:
        """Découverte complète (lente). Paper-only. Aucun ordre."""
        import hashlib
        started = int(time.time() * 1000)
        run_id = hashlib.sha256(f"discovery:{started}".encode()).hexdigest()[:16]
        logger.info("Wallet discovery START run_id=%s n=%d", run_id, n)

        candidates = self.cosmos.scan_subaccounts(
            max_pages=self.max_scan_pages, min_usdc=self.min_usdc, only_with_positions=True,
        )
        logger.info("Cosmos scan: %d candidats avec positions", len(candidates))

        scored = []
        for sub in candidates:
            ws = self._score_wallet(sub)
            if ws.total_score > 0:
                scored.append(ws)

        scored.sort(key=lambda x: x.total_score, reverse=True)
        for ws in scored[:50]:
            self._enrich_with_indexer(ws)
        scored.sort(key=lambda x: x.total_score, reverse=True)
        shortlist = scored[:n]

        finished = int(time.time() * 1000)
        result = DiscoveryResult(
            run_id=run_id, started_at_ms=started, finished_at_ms=finished,
            candidates_scanned=len(candidates), shortlisted=shortlist,
        )
        logger.info(
            "Discovery DONE run_id=%s candidates=%d shortlisted=%d elapsed_s=%.1f | %s",
            run_id, len(candidates), len(shortlist),
            (finished - started) / 1000, self.DISCLAIMER,
        )
        return result

    def _score_wallet(self, sub: OnChainSubaccount) -> WalletScore:
        ws = WalletScore(
            address=sub.address,
            subaccount_number=sub.subaccount_number,
            usdc_balance=sub.usdc_balance,
            open_positions=[
                {"market": p.market_id, "side": p.side, "size": p.size}
                for p in sub.positions
            ],
        )
        import math
        ws.balance_score = min(1.0, math.log10(max(1, sub.usdc_balance)) / 6.0)

        market_scores = []
        for pos in sub.positions:
            market = pos.market_id
            if market in BLOCKED_MARKETS:
                return ws
            ms = MARKET_PRIORITY_SCORE.get(market, 0.1)
            market_scores.append(ms)

        if not market_scores:
            return ws

        ws.market_priority_score = sum(market_scores) / len(market_scores)

        n_pos = sub.total_position_count
        if n_pos == 0:
            ws.position_count_score = 0.0
        elif n_pos <= 3:
            ws.position_count_score = 1.0
        elif n_pos <= 6:
            ws.position_count_score = 0.7
        else:
            ws.position_count_score = 0.4

        ws.total_score = (
            0.35 * ws.balance_score +
            0.40 * ws.market_priority_score +
            0.25 * ws.position_count_score
        )
        ws.note = f"on-chain only, balance=${sub.usdc_balance:.0f}, positions={n_pos}"
        return ws

    def _enrich_with_indexer(self, ws: WalletScore) -> None:
        try:
            fills_raw = self.rest.paginate_fills(
                address=ws.address,
                subaccount_number=ws.subaccount_number,
                max_pages=5,
                page_size=100,
            )
            if len(fills_raw) < 5:
                ws.note += " | indexer_fills_insufficient"
                return

            pnl_total, fees_total, wins, total = 0.0, 0.0, 0, 0
            open_pos: dict = {}
            _closed_records: list[TradeRecord] = []  # pour compute_account_score

            for raw in sorted(fills_raw, key=lambda x: x.get("createdAt", "")):
                side = raw.get("side", "")
                market = raw.get("market", "")
                try:
                    price = float(raw.get("price", 0))
                    size = float(raw.get("size", 0))
                    fee = float(raw.get("fee", 0))
                except (ValueError, TypeError):
                    continue

                key = market
                if key not in open_pos:
                    if market in BLOCKED_MARKETS:
                        continue
                    entry_ts_raw = raw.get("createdAt", "")
                    try:
                        import datetime as _dt
                        _ets = int(_dt.datetime.fromisoformat(
                            entry_ts_raw.replace("Z", "+00:00")
                        ).timestamp() * 1000) if entry_ts_raw else 0
                    except Exception:
                        _ets = 0
                    open_pos[key] = {
                        "side": "LONG" if side == "BUY" else "SHORT",
                        "entry_price": price, "size": size, "entry_fee": fee,
                        "entry_ts": _ets,
                    }
                else:
                    pos = open_pos[key]
                    is_close = (
                        (pos["side"] == "LONG" and side == "SELL") or
                        (pos["side"] == "SHORT" and side == "BUY")
                    )
                    if not is_close:
                        total_notional = pos["size"] * pos["entry_price"] + size * price
                        total_size = pos["size"] + size
                        pos["entry_price"] = total_notional / total_size if total_size > 0 else pos["entry_price"]
                        pos["size"] = total_size
                        pos["entry_fee"] += fee
                    else:
                        gross = (
                            (price - pos["entry_price"]) * pos["size"]
                            if pos["side"] == "LONG"
                            else (pos["entry_price"] - price) * pos["size"]
                        )
                        net = gross - pos["entry_fee"] - fee
                        pnl_total += net
                        fees_total += pos["entry_fee"] + fee
                        total += 1
                        if net > 0:
                            wins += 1
                        # Construire TradeRecord pour scoring
                        try:
                            entry_ts_ms = int(pos.get("entry_ts", 0))
                            close_ts_raw = raw.get("createdAt", "")
                            import datetime as _dt
                            if close_ts_raw:
                                close_ts_ms = int(_dt.datetime.fromisoformat(
                                    close_ts_raw.replace("Z", "+00:00")
                                ).timestamp() * 1000)
                            else:
                                close_ts_ms = entry_ts_ms + 60_000
                            hold_ms = max(1000.0, float(close_ts_ms - entry_ts_ms))
                            _closed_records.append(TradeRecord(
                                pnl_gross=abs(gross),
                                pnl_net=net,
                                fees=pos["entry_fee"] + fee,
                                size=pos["size"] * price,
                                entry_price=pos["entry_price"],
                                closed_at_ms=close_ts_ms,
                                holding_time_ms=hold_ms,
                                market_id=market,
                            ))
                        except Exception:
                            pass
                        del open_pos[key]

            if total >= 3:
                # -- Viral bot: compute_account_score avec one-big-win filter --
                account_score = compute_account_score(
                    account_address=ws.address,
                    subaccount_number=ws.subaccount_number,
                    network="mainnet",
                    trades=_closed_records,
                    current_ts_ms=int(time.time() * 1000),
                )

                if account_score.is_rejected:
                    reasons = "; ".join(account_score.rejection_reasons[:2])
                    ws.note += f" | REJECTED: {reasons}"
                    ws.total_score = 0.0
                    return

                ws.net_pnl_usdc = account_score.total_pnl_net
                ws.trade_count = account_score.total_trades
                ws.winrate = account_score.winrate
                ws.profit_factor = account_score.profit_factor
                ws.recent_score = account_score.recency_score
                market_scores = score_trades_by_market(
                    _closed_records,
                    current_ts_ms=int(time.time() * 1000),
                )
                ws.market_stats = {
                    market: {
                        "trade_count": ms.trade_count,
                        "winrate": ms.winrate,
                        "profit_factor": ms.profit_factor,
                        "expectancy_usdc": ms.expectancy_usdc,
                        "net_pnl_usdc": ms.net_pnl_usdc,
                        "recent_score": ms.recent_score,
                        "confidence": ms.confidence,
                    }
                    for market, ms in market_scores.items()
                }
                data_conf = account_score.data_confidence
                pnl_bonus = min(0.3, max(-0.1,
                    account_score.expectancy / max(abs(account_score.expectancy) + 1, 1.0)
                ))
                ws.total_score = max(0.0, min(1.0,
                    0.25 * ws.balance_score +
                    0.30 * ws.market_priority_score +
                    0.20 * ws.position_count_score +
                    0.15 * (ws.winrate - 0.3) / 0.4 +
                    0.10 * data_conf +
       