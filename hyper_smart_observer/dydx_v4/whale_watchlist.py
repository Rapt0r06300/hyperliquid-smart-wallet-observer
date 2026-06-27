"""
whale_watchlist.py — Surveillance prioritaire des top performers dYdX v4.

Objectif: maintenir un classement live des top-N wallets dYdX par performance
historique composite (PnL réalisé + win rate + profit factor + récence).

Ces wallets sont suivis en PRIORITÉ ABSOLUE:
- Pollés à CHAQUE tick (pas de rotation) pour signal age < 5s
- Abonnés en WebSocket via fast_scanner (0-lag sur les fills)
- Mises à jour scoring toutes les 30 min (refresh background)

Architecture:
- SQLite cache: whale_cache.db (survit aux redémarrages)
- Refresh périodique: découverte Cosmos LCD → scoring Indexer REST → cache
- Sources: seeds connus + Cosmos LCD scan + enrichissement historique

RÈGLE ABSOLUE: READ-ONLY. Aucun ordre réel, aucune clé privée.
PAPER SIMULATION ONLY. Toutes les positions sont fictives.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Paramètres ───────────────────────────────────────────────────────────────

REFRESH_INTERVAL_S: float = 1800.0      # Refresh du scoring toutes les 30 min
DEFAULT_TOP_N: int = 100                # Top-N wallets à suivre en priorité
MIN_CLOSED_POSITIONS: int = 5           # Historique minimum pour scorer
MIN_WIN_RATE: float = 0.45             # Au moins 45% de trades gagnants
MIN_PNL_USDC: float = 500.0            # Au moins 500 USDC de PnL total réalisé
MIN_TRADE_COUNT: int = 5               # Ignorer les wallets avec trop peu de trades
MAX_SCORE_CANDIDATES: int = 500        # Scorer au plus N candidats par refresh
PRIORITY_HOT_N: int = 20              # Les top-20 sont pollés à chaque tick

# Poids du score composite
SCORE_WEIGHTS = {
    "win_rate":      0.40,  # Le plus important: peut-il gagner régulièrement?
    "profit_factor": 0.30,  # Rapport gains/pertes: est-il efficient?
    "total_pnl":     0.20,  # Montant absolu: est-il significatif?
    "recency":       0.10,  # A-t-il tradé récemment?
}


# ─── Structures de données ────────────────────────────────────────────────────

@dataclass
class WhaleScore:
    """Score de performance d'un wallet dYdX pour le classement whale."""
    address: str
    subaccount_number: int = 0
    total_pnl_usdc: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 1.0
    trade_count: int = 0
    composite_score: float = 0.0
    last_trade_ms: int = 0          # Timestamp du dernier trade connu
    last_updated_ms: int = 0        # Timestamp du dernier scoring
    source: str = "whale_watchlist"

    def to_wallet_score(self):
        """Convertir en WalletScore pour compatibilité avec la shortlist."""
        from hyper_smart_observer.dydx_v4.wallet_discovery import WalletScore
        return WalletScore(
            address=self.address,
            subaccount_number=self.subaccount_number,
            total_score=self.composite_score,
            winrate=self.win_rate,
            profit_factor=self.profit_factor,
            trade_count=self.trade_count,
            net_pnl_usdc=self.total_pnl_usdc,
            source="whale_watchlist",
        )


# ─── WhaleWatchlist ───────────────────────────────────────────────────────────

class WhaleWatchlist:
    """
    Classement live des top-N wallets dYdX par performance historique.

    Usage:
        ww = WhaleWatchlist(rest_client=rest, cosmos_client=cosmos)
        ww.start_background_refresh()
        top = ww.get_top()       # list[WhaleScore]
        hot = ww.get_hot_set()   # set[str] des adresses prioritaires

    PAPER SIMULATION ONLY — READ-ONLY, aucun ordre réel.
    """

    def __init__(
        self,
        rest_client,
        cosmos_client=None,
        db_path: Optional[str] = None,
        top_n: int = DEFAULT_TOP_N,
        refresh_interval_s: float = REFRESH_INTERVAL_S,
        priority_hot_n: int = PRIORITY_HOT_N,
    ):
        self.rest = rest_client
        self.cosmos = cosmos_client
        self.top_n = top_n
        self.refresh_interval_s = refresh_interval_s
        self.priority_hot_n = priority_hot_n
        self._db_path = Path(db_path) if db_path else Path("whale_cache.db")
        self._lock = threading.RLock()
        self._top_wallets: list[WhaleScore] = []
        self._hot_set: set[str] = set()     # Adresses des top-N prioritaires (lookup O(1))
        self._candidates: dict[str, int] = {}  # {address: discovered_at_ms}
        self._last_refresh_ms: int = 0
        self._refresh_count: int = 0
        self._init_db()
        self._load_from_db()
        logger.info(
            "WhaleWatchlist initialisé: %d wallets en cache, %d candidats | PAPER-ONLY",
            len(self._top_wallets), len(self._candidates),
        )

    # ── DB ────────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS whale_scores (
                        address TEXT PRIMARY KEY,
                        subaccount_number INTEGER DEFAULT 0,
                        total_pnl_usdc REAL DEFAULT 0,
                        win_rate REAL DEFAULT 0,
                        profit_factor REAL DEFAULT 1,
                        trade_count INTEGER DEFAULT 0,
                        composite_score REAL DEFAULT 0,
                        last_trade_ms INTEGER DEFAULT 0,
                        last_updated_ms INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'whale_watchlist'
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS whale_candidates (
                        address TEXT PRIMARY KEY,
                        discovered_at_ms INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'unknown'
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_whale_score ON whale_scores(composite_score DESC)"
                )
                conn.commit()
        except Exception as e:
            logger.warning("WhaleWatchlist DB init error: %s", e)

    def _load_from_db(self) -> None:
        """Charger depuis SQLite au démarrage (wallets scorés + candidats connus)."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                rows = conn.execute(
                    "SELECT address, subaccount_number, total_pnl_usdc, win_rate, "
                    "profit_factor, trade_count, composite_score, last_trade_ms, "
                    "last_updated_ms, source "
                    "FROM whale_scores ORDER BY composite_score DESC LIMIT ?",
                    (self.top_n,)
                ).fetchall()
                top = [
                    WhaleScore(
                        address=r[0], subaccount_number=r[1], total_pnl_usdc=r[2],
                        win_rate=r[3], profit_factor=r[4], trade_count=r[5],
                        composite_score=r[6], last_trade_ms=r[7],
                        last_updated_ms=r[8], source=r[9],
                    )
                    for r in rows
                ]
                cand_rows = conn.execute(
                    "SELECT address, discovered_at_ms FROM whale_candidates"
                ).fetchall()
                with self._lock:
                    self._top_wallets = top
                    self._hot_set = {w.address for w in top[:self.priority_hot_n]}
                    self._candidates = {r[0]: r[1] for r in cand_rows}
            logger.debug(
                "WhaleWatchlist DB chargé: %d scorés, %d candidats",
                len(self._top_wallets), len(self._candidates),
            )
        except Exception as e:
            logger.debug("WhaleWatchlist DB load error: %s", e)

    def _save_scores(self, scores: list[WhaleScore]) -> None:
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO whale_scores
                    (address, subaccount_number, total_pnl_usdc, win_rate, profit_factor,
                     trade_count, composite_score, last_trade_ms, last_updated_ms, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    (w.address, w.subaccount_number, w.total_pnl_usdc, w.win_rate,
                     w.profit_factor, w.trade_count, w.composite_score,
                     w.last_trade_ms, w.last_updated_ms, w.source)
                    for w in scores
                ])
                conn.commit()
        except Exception as e:
            logger.warning("WhaleWatchlist save scores error: %s", e)

    def _save_candidates(self, addresses: list[str], source: str) -> None:
        try:
            now_ms = int(time.time() * 1000)
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.executemany("""
                    INSERT OR IGNORE INTO whale_candidates (address, discovered_at_ms, source)
                    VALUES (?, ?, ?)
                """, [(addr, now_ms, source) for addr in addresses])
                conn.commit()
        except Exception as e:
            logger.debug("WhaleWatchlist save candidates error: %s", e)

    # ── Accès public ─────────────────────────────────────────────────────────

    def get_top(self, n: Optional[int] = None) -> list[WhaleScore]:
        """Retourner les top-N wallets scorés (thread-safe)."""
        with self._lock:
            return list(self._top_wallets[:n or self.top_n])

    def get_hot_set(self) -> set[str]:
        """Set des adresses prioritaires (lookup O(1) pour fast_scanner)."""
        with self._lock:
            return set(self._hot_set)

    def is_whale(self, address: str) -> bool:
        """True si ce wallet est dans le hot set prioritaire."""
        with self._lock:
            return address in self._hot_set

    def as_wallet_scores(self, n: Optional[int] = None) -> list:
        """Convertir les top-N en WalletScore pour la shortlist."""
        return [w.to_wallet_score() for w in self.get_top(n)]

    def get_stats(self) -> dict:
        """Stats pour le dashboard."""
        with self._lock:
            top = self._top_wallets
            return {
                "total_tracked": len(top),
                "hot_set_size": len(self._hot_set),
                "candidates_known": len(self._candidates),
                "last_refresh_ms": self._last_refresh_ms,
                "refresh_count": self._refresh_count,
                "avg_win_rate": (
                    sum(w.win_rate for w in top) / len(top) if top else 0.0
                ),
                "avg_pnl_usdc": (
                    sum(w.total_pnl_usdc for w in top) / len(top) if top else 0.0
                ),
                "top1": top[0].address[:16] + "..." if top else None,
            }

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_if_needed(self) -> None:
        """Déclencher un refresh si l'intervalle est écoulé."""
        now_ms = int(time.time() * 1000)
        with self._lock:
            elapsed_ms = now_ms - self._last_refresh_ms
        if elapsed_ms >= self.refresh_interval_s * 1000:
            self.refresh()

    def refresh(self) -> list[WhaleScore]:
        """
        Refresh complet: découverte → scoring → cache → mise à jour hot set.
        Appelable depuis n'importe quel thread.
        PAPER SIMULATION ONLY.
        """
        logger.info(
            "WhaleWatchlist refresh #%d démarré (%d candidats connus) | PAPER-ONLY",
            self._refresh_count + 1, len(self._candidates),
        )
        t0 = time.time()

        # 1. Découverte de nouveaux candidats
        n_new = self._discover_candidates()

        # 2. Scorer les candidats (par batch, limité à MAX_SCORE_CANDIDATES)
        all_scored = self._score_all_candidates()

        # 3. Trier et garder le top-N
        all_scored.sort(key=lambda w: w.composite_score, reverse=True)
        top = all_scored[:self.top_n]

        # 4. Mise à jour thread-safe
        with self._lock:
            self._top_wallets = top
            self._hot_set = {w.address for w in top[:self.priority_hot_n]}
            self._last_refresh_ms = int(time.time() * 1000)
            self._refresh_count += 1

        # 5. Persistance SQLite
        if all_scored:
            self._save_scores(all_scored)

        elapsed = time.time() - t0
        logger.info(
            "WhaleWatchlist refresh terminé en %.1fs: %d scorés → top-%d "
            "| wr_avg=%.2f pnl_avg=%.0f USDC | PAPER-ONLY",
            elapsed, len(all_scored), len(top),
            sum(w.win_rate for w in top) / max(1, len(top)),
            sum(w.total_pnl_usdc for w in top) / max(1, len(top)),
        )
        return top

    def _discover_candidates(self) -> int:
        """
        Découvrir de nouveaux candidats depuis:
        1. Cosmos LCD scan (wallets avec positions actives et gros soldes)
        2. Fills récents des wallets connus (pour tracker leurs contacts)
        Retourne le nombre de NOUVEAUX candidats.
        """
        n_before = len(self._candidates)
        new_addrs: list[str] = []

        # Source 1: Cosmos LCD (déjà utilisé par wallet_discovery)
        if self.cosmos is not None:
            try:
                subs = self.cosmos.scan_subaccounts(
                    max_pages=20,       # ~2000 wallets max
                    page_size=100,
                    min_usdc=1_000.0,   # Wallets avec > 1000 USDC
                    only_with_positions=False,  # Inclure wallets sans positions ouvertes
                )
                for sub in subs:
                    addr = sub.address if hasattr(sub, 'address') else str(sub)
                    if addr and addr not in self._candidates:
                        new_addrs.append(addr)
                logger.debug(
                    "WhaleWatchlist discovery Cosmos: %d sous-comptes scannés",
                    len(subs),
                )
            except Exception as e:
                logger.debug("WhaleWatchlist Cosmos scan error: %s", e)

        if new_addrs:
            now_ms = int(time.time() * 1000)
            with self._lock:
                for addr in new_addrs:
                    self._candidates[addr] = now_ms
            self._save_candidates(new_addrs, source="cosmos_lcd")

        n_new = len(self._candidates) - n_before
        if n_new > 0:
            logger.info("WhaleWatchlist: +%d nouveaux candidats découverts", n_new)
        return n_new

    def _score_all_candidates(self) -> list[WhaleScore]:
        """Scorer tous les candidats connus (limité à MAX_SCORE_CANDIDATES)."""
        with self._lock:
            # Prioriser les candidats les plus récents + ceux pas encore scorés
            known_scored = {w.address for w in self._top_wallets}
            # Candidats non encore scorés en premier, puis anciens scorés
            unscored = [a for a in self._candidates if a not in known_scored]
            already_scored = [a for a in self._candidates if a in known_scored]
            ordered = unscored[:MAX_SCORE_CANDIDATES // 2] + already_scored[:MAX_SCORE_CANDIDATES // 2]

        results: list[WhaleScore] = []
        # Garder les wallets déjà scorés (avec leur score existant)
        with self._lock:
            existing_by_addr = {w.address: w for w in self._top_wallets}

        for addr in ordered[:MAX_SCORE_CANDIDATES]:
            try:
                score = self._score_candidate(addr, existing=existing_by_addr.get(addr))
                if score is not None:
                    results.append(score)
            except Exception as e:
                logger.debug("WhaleWatchlist score error %s: %s", addr[:12], e)

        # Inclure les wallets déjà scorés qui n'ont pas été ré-scorés cette fois
        already_in_results = {w.address for w in results}
        for w in existing_by_addr.values():
            if w.address not in already_in_results:
                results.append(w)

        return results

    def _score_candidate(
        self, address: str, existing: Optional[WhaleScore] = None
    ) -> Optional[WhaleScore]:
        """
        Calculer le score de performance d'un wallet depuis ses positions fermées.

        Utilise GET /v4/perpetualPositions?status=CLOSED pour obtenir l'historique
        des positions fermées avec leur PnL réalisé. READ-ONLY.
        """
        now_ms = int(time.time() * 1000)

        # Si le score existant est récent (< 1h), ne pas re-scorer
        if existing and (now_ms - existing.last_updated_ms) < 3600 * 1000:
            return existing

        try:
            resp = self.rest.get_positions(
                address=address,
                subaccount_number=0,
                status="CLOSED",
                limit=100,
            )
            positions = resp.get("positions", [])
        except Exception as e:
            logger.debug("WhaleWatchlist REST error %s: %s", address[:12], e)
            return existing  # Garder le score précédent si REST échoue

        if len(positions) < MIN_CLOSED_POSITIONS:
            return None

        # Extraire PnL réalisé de chaque position fermée
        pnls: list[float] = []
        last_trade_ms = 0
        for pos in positions:
            try:
                pnl = float(pos.get("realizedPnl") or pos.get("realized_pnl") or 0)
                pnls.append(pnl)
                # Récupérer le timestamp de fermeture pour le score de récence
                closed_at = pos.get("closedAt") or pos.get("createdAt") or ""
                if closed_at:
                    try:
                        import datetime as _dt
                        ts = int(
                            _dt.datetime.fromisoformat(
                                closed_at.replace("Z", "+00:00")
                            ).timestamp() * 1000
                        )
                        last_trade_ms = max(last_trade_ms, ts)
                    except Exception:
                        pass
            except (ValueError, TypeError):
                continue

        if len(pnls) < MIN_CLOSED_POSITIONS:
            return None

        # Métriques de performance
        total_pnl = sum(pnls)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_rate = len(wins) / len(pnls)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses)) if losses else 0.01
        profit_factor = gross_profit / max(0.01, gross_loss)
        trade_count = len(pnls)

        # Filtres de qualité minimum (ne pas polluer le classement avec des marginaux)
        if win_rate < MIN_WIN_RATE or total_pnl < MIN_PNL_USDC or trade_count < MIN_TRADE_COUNT:
            return None

        # Score composite normalisé [0, 1]
        wr_score = min(1.0, max(0.0, (win_rate - 0.45) / 0.35))  # 45%=0 → 80%=1
        pf_score = min(1.0, max(0.0, (profit_factor - 1.0) / 4.0))  # PF 1=0 → PF 5=1
        pnl_score = min(1.0, max(0.0, total_pnl / 50_000.0))   # 50k USDC = score 1.0

        # Récence: plein score si tradé dans les 7 jours, décroît sur 30 jours
        if last_trade_ms > 0:
            age_days = (now_ms - last_trade_ms) / (86400 * 1000)
            recency_score = max(0.0, 1.0 - (age_days / 30.0))
        else:
            recency_score = 0.3  # Inconnu → score neutre réduit

        composite = (
            SCORE_WEIGHTS["win_rate"] * wr_score
            + SCORE_WEIGHTS["profit_factor"] * pf_score
            + SCORE_WEIGHTS["total_pnl"] * pnl_score
            + SCORE_WEIGHTS["recency"] * recency_score
        )

        return WhaleScore(
            address=address,
            subaccount_number=0,
            total_pnl_usdc=total_pnl,
            win_rate=win_rate,
            profit_factor=profit_factor,
            trade_count=trade_count,
            composite_score=composite,
            last_trade_ms=last_trade_ms,
            last_updated_ms=now_ms,
            source="whale_watchlist",
        )

    # ── Background thread ─────────────────────────────────────────────────────

    def start_background_refresh(self, initial_delay_s: float = 90.0) -> threading.Thread:
        """
        Démarrer le refresh périodique en background thread (daemon).
        Premier refresh après initial_delay_s (laisse le temps au REST de s'initialiser).
        PAPER SIMULATION ONLY.
        """
        def _loop():
            logger.info(
                "WhaleWatchlist: background refresh démarré (premier refresh dans %.0fs)",
                initial_delay_s,
            )
            time.sleep(initial_delay_s)
            while True:
                try:
                    self.refresh()
                except Exception as e:
                    logger.warning("WhaleWatchlist background refresh error: %s", e)
                time.sleep(self.refresh_interval_s)

        t = threading.Thread(target=_loop, daemon=True, name="whale-watchlist-refresh")
        t.start()
        return t

    def inject_address(self, address: str, source: str = "manual") -> None:
        """Ajouter manuellement une adresse candidate (ex: depuis WebSocket fills)."""
        with self._lock:
            if address not in self._candidates:
                self._candidates[address] = int(time.time() * 1000)
        self._save_candidates([address], source=source)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def build_whale_watchlist_from_config(
    rest_client,
    cosmos_client=None,
    config=None,
    db_dir: Optional[str] = None,
) -> WhaleWatchlist:
    """
    Factory: construire un WhaleWatchlist depuis la config de l'engine.
    PAPER SIMULATION ONLY.
    """
    top_n = int(getattr(config, "whale_watchlist_top_n", DEFAULT_TOP_N))
    refresh_s = float(getattr(config, "whale_watchlist_refresh_s", REFRESH_INTERVAL_S))
    hot_n = int(getattr(config, "whale_watchlist_hot_n", PRIORITY_HOT_N))
    db_path = None
    if db_dir:
        db_path = str(Path(db_dir) / "whale_cache.db")
    return WhaleWatchlist(
        rest_client=rest_client,
        cosmos_client=cosmos_client,
        db_path=db_path,
        top_n=top_n,
        refresh_interval_s=refresh_s,
        priority_hot_n=hot_n,
    )
