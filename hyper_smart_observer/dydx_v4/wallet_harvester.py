"""
Moteur de découverte multi-sources de wallets — READ-ONLY / PAPER-ONLY.

But: avoir le MAXIMUM de wallets candidats, vite, en imitant — et en dépassant —
la méthode du bot viral (cf. docs/research/MAGIC_BOT_VIRAL_METHOD_CONFIRMED.md).

Le bot viral copie seulement le top ~5 du leaderboard, sondé toutes les 5 min.
Les outils pros (Hyperbot ~600k adresses, HyperTracker ~1,5M wallets) vont plus
loin en **ingérant les données on-chain et les flux de trades** : chaque fill
révèle une adresse. C'est public, gratuit, sans clé API. Ce n'est PAS du scraping
HTML (qui serait plus lent — le site lit la même donnée — et fragile).

Ce module agrège plusieurs SOURCES d'adresses, les déduplique dans un index,
les score (qualité d'exécution + récence + confirmation multi-source +
copiabilité) et renvoie le top sous forme `(address, score)` directement
consommable par `FastScanner.track_wallets()`.

Architecture (chaque source est injectable → testable hors réseau) :

    [Leaderboard] [Trade-tape] [On-chain blocks] [Import dataset]
              \        |            |             /
               ▼       ▼            ▼            ▼
                    WalletIndex (dedupe, first/last seen, activité)
                              │
                              ▼  rank()  (filtre style bot viral + score)
                    top (address, score)  ──►  FastScanner.track_wallets()

SÉCURITÉ : aucune méthode d'ordre/signature/dépôt. Lecture, dédup, score. Point.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

# Adresses acceptées : dydx1… (bech32) ou 0x… (hex 40). Les tronquées (« 0xab…cd »)
# sont rejetées — règle projet : jamais d'adresse non exploitable.
_RE_DYDX_OK = re.compile(r"^dydx1[0-9a-z]{38,}$")  # dydx1 + 38+ chars bech32
_RE_HEX = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_valid_address(address: object) -> bool:
    """Valider une adresse complète (jamais tronquée). dydx1… ou 0x…40hex."""
    if not isinstance(address, str):
        return False
    a = address.strip()
    if not a or "..." in a or "…" in a:
        return False
    return bool(_RE_DYDX_OK.match(a) or _RE_HEX.match(a))


# --------------------------------------------------------------------------- #
# Candidat & index
# --------------------------------------------------------------------------- #
@dataclass
class WalletCandidate:
    """Une adresse découverte + ce qu'on sait d'elle (fusionné multi-sources)."""

    address: str
    sources: set[str] = field(default_factory=set)
    first_seen_ms: int = 0
    last_seen_ms: int = 0
    activity_count: int = 0  # nb d'observations (fills/lignes leaderboard…)

    # Métriques optionnelles (issues du leaderboard ou d'un enrichissement)
    net_pnl_usdc: Optional[float] = None
    roi_pct: Optional[float] = None
    winrate: Optional[float] = None
    profit_factor: Optional[float] = None
    trade_count: Optional[int] = None
    usdc_balance: Optional[float] = None  # depuis la source on-chain Cosmos

    score: float = 0.0

    @property
    def has_metrics(self) -> bool:
        return self.winrate is not None and self.profit_factor is not None


def _merge_metric(current: Optional[float], incoming: object) -> Optional[float]:
    """Garder la métrique connue ; remplacer None par une valeur numérique."""
    if incoming is None:
        return current
    try:
        val = float(incoming)
    except (TypeError, ValueError):
        return current
    return val


class WalletIndex:
    """Index dédupliqué d'adresses. Cœur pur, sans réseau, testable."""

    def __init__(self) -> None:
        self._by_addr: dict[str, WalletCandidate] = {}

    def __len__(self) -> int:
        return len(self._by_addr)

    def __contains__(self, address: str) -> bool:
        return address in self._by_addr

    def get(self, address: str) -> Optional[WalletCandidate]:
        return self._by_addr.get(address)

    def all(self) -> list[WalletCandidate]:
        return list(self._by_addr.values())

    def observe(
        self,
        address: str,
        source: str,
        now_ms: int,
        metrics: Optional[dict] = None,
    ) -> Optional[WalletCandidate]:
        """
        Enregistrer/fusionner une observation d'adresse.

        Retourne le candidat (créé ou mis à jour), ou None si l'adresse est
        invalide/tronquée (jamais indexée).
        """
        if not is_valid_address(address):
            return None
        c = self._by_addr.get(address)
        created = c is None
        if c is None:
            c = WalletCandidate(address=address, first_seen_ms=now_ms, last_seen_ms=now_ms)
            self._by_addr[address] = c
        c.sources.add(source)
        c.first_seen_ms = min(c.first_seen_ms or now_ms, now_ms)
        c.last_seen_ms = max(c.last_seen_ms, now_ms)
        c.activity_count += 1
        if metrics:
            c.net_pnl_usdc = _merge_metric(c.net_pnl_usdc, metrics.get("net_pnl_usdc"))
            c.roi_pct = _merge_metric(c.roi_pct, metrics.get("roi_pct"))
            c.winrate = _merge_metric(c.winrate, metrics.get("winrate"))
            c.profit_factor = _merge_metric(c.profit_factor, metrics.get("profit_factor"))
            tc = metrics.get("trade_count")
            if tc is not None:
                try:
                    c.trade_count = int(tc)
                except (TypeError, ValueError):
                    pass
            c.usdc_balance = _merge_metric(c.usdc_balance, metrics.get("usdc_balance"))
        _ = created
        return c


# --------------------------------------------------------------------------- #
# Parsers de payloads publics (purs, défensifs)
# --------------------------------------------------------------------------- #
def extract_leaderboard_addresses(payload: object) -> list[tuple[str, dict]]:
    """
    Extraire (adresse, métriques) d'un payload leaderboard générique.

    Défensif sur les noms de champs (address/user/wallet ; pnl/roi/winrate…).
    """
    rows = payload
    if isinstance(payload, dict):
        rows = (
            payload.get("leaderboard")
            or payload.get("rows")
            or payload.get("data")
            or payload.get("traders")
            or []
        )
    if not isinstance(rows, list):
        return []
    out: list[tuple[str, dict]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        addr = row.get("address") or row.get("user") or row.get("wallet") or row.get("ethAddress")
        if not isinstance(addr, str):
            continue
        metrics = {
            "net_pnl_usdc": row.get("pnl") if row.get("pnl") is not None else row.get("net_pnl_usdc"),
            "roi_pct": row.get("roi") if row.get("roi") is not None else row.get("roi_pct"),
            "winrate": row.get("winRate") if row.get("winRate") is not None else row.get("winrate"),
            "profit_factor": row.get("profitFactor") if row.get("profitFactor") is not None else row.get("profit_factor"),
            "trade_count": row.get("trades") if row.get("trades") is not None else row.get("trade_count"),
        }
        out.append((addr, metrics))
    return out


def extract_tape_addresses(trades: object) -> list[str]:
    """
    Extraire les adresses d'un flux de trades/fills (chaque fill → 1-2 adresses).

    Sur dYdX v4 l'Indexer `v4_trades` n'expose pas l'adresse ; il faut alors la
    couche on-chain. Sur Hyperliquid les fills exposent l'adresse. Ce parser
    reste générique : il prend toute clé d'adresse présente.
    """
    if not isinstance(trades, list):
        return []
    found: list[str] = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        for key in ("address", "user", "wallet", "maker", "taker", "subaccount", "sender"):
            v = t.get(key)
            if isinstance(v, str) and is_valid_address(v):
                found.append(v)
    return found


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
@dataclass
class WalletSource:
    """
    Source d'adresses générique et injectable.

    `harvest_fn()` renvoie un itérable de `(address, metrics|None)`. On l'enveloppe
    pour pouvoir brancher leaderboard, trade-tape, on-chain ou import dataset,
    tout en restant testable sans réseau.
    """

    name: str
    harvest_fn: Callable[[], Iterable[tuple[str, Optional[dict]]]]

    def harvest(self) -> list[tuple[str, Optional[dict]]]:
        try:
            return list(self.harvest_fn())
        except Exception as e:  # pragma: no cover - dépend du réseau
            logger.debug("source %s a échoué: %s", self.name, e)
            return []


def leaderboard_source(name: str, fetch_payload: Callable[[], object]) -> WalletSource:
    """Source leaderboard: `fetch_payload()` → payload → (addr, métriques)."""

    def _gen() -> Iterable[tuple[str, Optional[dict]]]:
        for addr, metrics in extract_leaderboard_addresses(fetch_payload()):
            yield addr, metrics

    return WalletSource(name=name, harvest_fn=_gen)


def tape_source(name: str, fetch_trades: Callable[[], object]) -> WalletSource:
    """Source flux de trades: `fetch_trades()` → liste de fills → adresses."""

    def _gen() -> Iterable[tuple[str, Optional[dict]]]:
        for addr in extract_tape_addresses(fetch_trades()):
            yield addr, None

    return WalletSource(name=name, harvest_fn=_gen)


def static_source(name: str, addresses: Iterable[str]) -> WalletSource:
    """Source d'amorçage: une liste d'adresses (dataset importé)."""
    snapshot = list(addresses)

    def _gen() -> Iterable[tuple[str, Optional[dict]]]:
        for addr in snapshot:
            yield addr, None

    return WalletSource(name=name, harvest_fn=_gen)


def cosmos_source(
    name: str,
    cosmos_client,
    max_pages: int = 50,
    page_size: int = 100,
    min_usdc: float = 5_000.0,
    only_with_positions: bool = True,
) -> WalletSource:
    """
    Source ON-CHAIN haute couverture — la vraie voie « maximum d'adresses ».

    Pagine TOUS les subaccounts dYdX v4 via le Cosmos LCD
    (`cosmos_client.scan_subaccounts(...)`). Chaque subaccount actif = une adresse,
    avec sa balance USDC. READ-ONLY, aucune clé, aucun ordre.

    `cosmos_client` est injectable (duck-typing sur `.scan_subaccounts`) → testable
    sans réseau. Si le scan échoue, `WalletSource.harvest()` renvoie [] (NO_TRADE).
    """

    def _gen() -> Iterable[tuple[str, Optional[dict]]]:
        subs = cosmos_client.scan_subaccounts(
            max_pages=max_pages,
            page_size=page_size,
            min_usdc=min_usdc,
            only_with_positions=only_with_positions,
        )
        for s in subs or []:
            addr = getattr(s, "address", None)
            if not isinstance(addr, str) or not addr:
                continue
            bal = getattr(s, "usdc_balance", None)
            yield addr, ({"usdc_balance": bal} if bal is not None else None)

    return WalletSource(name=name, harvest_fn=_gen)


# --------------------------------------------------------------------------- #
# Scoring (sélection « intelligente » façon bot viral, étendue)
# --------------------------------------------------------------------------- #
# Seuils façon bot viral (cf. audit) : filtrer le bruit avant de copier.
GATE_MIN_TRADES = 10
GATE_MIN_WINRATE = 0.40
GATE_MIN_PROFIT_FACTOR = 1.2


def score_candidate(c: WalletCandidate, now_ms: int, recency_window_ms: int = 3_600_000) -> float:
    """
    Score 0–100 transparent et déterministe.

    Composantes :
      - qualité d'exécution (winrate, profit_factor, ROI) si connue ;
      - récence (vu récemment = plus utile pour copier) ;
      - confirmation multi-source (leaderboard ET tape = plus fiable) ;
      - activité (plus de fills = plus de signaux copiables, rendements décroissants).
    Un candidat sans métriques reste découvrable (tier bas) via récence + activité.
    """
    # Qualité (0–50)
    quality = 0.0
    if c.winrate is not None:
        quality += max(0.0, min(1.0, c.winrate)) * 25.0
    if c.profit_factor is not None:
        quality += max(0.0, min(3.0, c.profit_factor)) / 3.0 * 15.0
    if c.roi_pct is not None:
        quality += max(0.0, min(100.0, c.roi_pct)) / 100.0 * 10.0

    # Récence (0–25) : 25 si vu à l'instant, 0 au-delà de la fenêtre
    age = max(0, now_ms - c.last_seen_ms)
    recency = max(0.0, 1.0 - age / max(1, recency_window_ms)) * 25.0

    # Multi-source (0–15) : +7,5 par source distincte, plafonné
    multi = min(2, len(c.sources)) * 7.5

    # Activité (0–10) : log-ish via paliers
    act = c.activity_count
    if act >= 50:
        activity = 10.0
    elif act >= 20:
        activity = 8.0
    elif act >= 10:
        activity = 6.0
    elif act >= 3:
        activity = 3.0
    elif act >= 1:
        activity = 1.0
    else:
        activity = 0.0

    # Taille du compte (0–10) : un compte plus capitalisé est plus pertinent à
    # copier. Fournie par la source on-chain Cosmos (balance USDC), saturée à 100k.
    if c.usdc_balance is not None:
        balance = min(1.0, max(0.0, c.usdc_balance) / 100_000.0) * 10.0
    else:
        balance = 0.0

    return round(quality + recency + multi + activity + balance, 4)


def passes_viral_gates(c: WalletCandidate) -> bool:
    """Filtre « qualité d'exécution » du bot viral (quand les métriques existent)."""
    if c.trade_count is not None and c.trade_count < GATE_MIN_TRADES:
        return False
    if c.winrate is not None and c.winrate < GATE_MIN_WINRATE:
        return False
    if c.profit_factor is not None and c.profit_factor < GATE_MIN_PROFIT_FACTOR:
        return False
    return True


# --------------------------------------------------------------------------- #
# Harvester
# --------------------------------------------------------------------------- #
class WalletHarvester:
    """
    Agrège des sources, déduplique, score, et fournit le top pour le scanner.

    READ-ONLY. Ne place aucun ordre. `harvest_once()` ne lève jamais (chaque
    source est isolée) → robuste si une source réseau tombe (NO_TRADE silencieux).
    """

    def __init__(self, index: Optional[WalletIndex] = None, max_track: int = 500) -> None:
        self.index = index or WalletIndex()
        self.max_track = max_track
        self._sources: list[WalletSource] = []
        self.last_harvest_new = 0
        self.total_harvested = 0

    def add_source(self, source: WalletSource) -> None:
        self._sources.append(source)

    def add_cosmos_source(
        self, cosmos_client, name: str = "cosmos_onchain", **scan_kwargs
    ) -> None:
        """Brancher la source on-chain Cosmos (énumère tous les subaccounts)."""
        self.add_source(cosmos_source(name, cosmos_client, **scan_kwargs))

    def harvest_once(self, now_ms: Optional[int] = None) -> int:
        """Faire un passage sur toutes les sources. Retourne le nb de NOUVELLES adresses."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        before = len(self.index)
        for src in self._sources:
            for address, metrics in src.harvest():
                self.index.observe(address, src.name, now, metrics)
        new = len(self.index) - before
        self.last_harvest_new = new
        self.total_harvested += new
        return new

    def rank(
        self,
        now_ms: Optional[int] = None,
        enforce_gates: bool = True,
    ) -> list[WalletCandidate]:
        """
        Scorer tout l'index et retourner les candidats triés (meilleur d'abord).

        `enforce_gates=True` écarte ceux qui échouent aux gates qualité du bot
        viral (quand leurs métriques sont connues). Les candidats sans métriques
        passent (découverte), mais scorent plus bas (pas de composante qualité).
        """
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        ranked: list[WalletCandidate] = []
        for c in self.index.all():
            if enforce_gates and c.has_metrics and not passes_viral_gates(c):
                continue
            c.score = score_candidate(c, now)
            ranked.append(c)
        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked

    def top_for_scanner(
        self, n: Optional[int] = None, now_ms: Optional[int] = None
    ) -> list[tuple[str, float]]:
        """Top `(address, score)` prêt pour `FastScanner.track_wallets()`."""
        limit = n if n is not None else self.max_track
        return [(c.address, c.score) for c in self.rank(now_ms=now_ms)[:limit]]

    def stats(self) -> dict:
        """État READ-ONLY pour le dashboard."""
        with_metrics = sum(1 for c in self.index.all() if c.has_metrics)
        multi_source = sum(1 for c in self.index.all() if len(c.sources) >= 2)
        return {
            "total_addresses": len(self.index),
            "with_metrics": with_metrics,
            "multi_source": multi_source,
            "sources": [s.name for s in self._sources],
            "last_harvest_new": self.last_harvest_new,
            "max_track": self.max_track,
            "read_only": True,
            "paper_only": True,
        }


__all__ = [
    "WalletCandidate",
    "WalletIndex",
    "WalletSource",
    "WalletHarvester",
    "is_valid_address",
    "extract_leaderboard_addresses",
    "extract_tape_addresses",
    "leaderboard_source",
    "tape_source",
    "static_source",
    "cosmos_source",
    "score_candidate",
    "passes_viral_gates",
    "GATE_MIN_TRADES",
    "GATE_MIN_WINRATE",
    "GATE_MIN_PROFIT_FACTOR",
]
