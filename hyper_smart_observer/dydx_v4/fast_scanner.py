"""
Scanner rapide multi-wallets dYdX v4 — READ-ONLY / PAPER-ONLY.

Objectif: supprimer la latence de 8–58 s qui rendait les signaux trop vieux
(et donc le PnL paper négatif). Au lieu d'interroger chaque wallet en REST,
séquentiellement, sur un intervalle (ancien `_poll_shortlist_live`), on
écoute le flux temps réel de l'Indexer dYdX (canal `v4_subaccounts`) pour les
wallets "chauds". Les fills arrivent alors en < 1 s, avec un `age_ms` calculé
sur l'horodatage réel du fill.

Principe "scanner des milliers de wallets" sans saturer le WebSocket:
- un `HotWalletSet` borné garde en abonnement live les N meilleurs/plus frais ;
- les autres wallets restent suivis par un balayage REST rapide (concurrent,
  borné), avec une `fetch_fn` injectable → testable hors réseau ;
- déduplication par `fill_id`, fenêtre de fraîcheur stricte, métriques de débit.

SÉCURITÉ ABSOLUE:
- aucune méthode d'ordre, de signature, de dépôt/retrait n'existe ici ;
- ce module lit, parse, déduplique et range des fills publics, rien d'autre.
- Un signal/fill n'est JAMAIS un ordre.

La logique "pure" (parsing, dedupe, fraîcheur, hot-set, débit) est isolée du
réseau pour être testable de façon déterministe.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

# Canal Indexer temps réel des fills d'un subaccount (READ-ONLY).
CHANNEL_SUBACCOUNTS = "v4_subaccounts"

# Fenêtre de fraîcheur par défaut: un fill plus vieux que ça n'est plus
# copiable (aligné sur DydxV4Config.max_signal_age_ms = 4000).
DEFAULT_MAX_AGE_MS = 4000


# --------------------------------------------------------------------------- #
# Parsing horodatage
# --------------------------------------------------------------------------- #
def parse_iso_to_ms(value: object) -> Optional[int]:
    """
    Convertir un horodatage dYdX (`createdAt`) en epoch millisecondes.

    Accepte:
      - ISO8601 "2026-06-12T03:04:05.123Z" ou avec offset "+00:00" ;
      - un nombre déjà en ms (>= 1e12) ou en secondes (< 1e12) ;
    Retourne None si non parsable (le fill sera alors ignoré, jamais inventé).
    """
    if value is None:
        return None
    # Déjà numérique
    if isinstance(value, (int, float)):
        n = float(value)
        if n <= 0:
            return None
        # Heuristique secondes vs millisecondes
        return int(n) if n >= 1_000_000_000_000 else int(n * 1000)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        # Dernier recours: chaîne purement numérique
        try:
            n = float(text)
            return int(n) if n >= 1_000_000_000_000 else int(n * 1000)
        except (ValueError, TypeError):
            return None


# --------------------------------------------------------------------------- #
# Fill normalisé issu du scan
# --------------------------------------------------------------------------- #
@dataclass
class ScannedFill:
    """Fill public normalisé, enrichi de l'âge mesuré au moment du scan."""

    address: str
    subaccount_number: int
    market_id: str
    side: str               # "BUY" | "SELL" (normalisé majuscule)
    size: float
    price: float
    created_at_ms: int
    fill_id: str
    age_ms: int
    source: str = "WS"      # "WS" (temps réel) | "REST" (balayage)

    @property
    def notional_usdc(self) -> float:
        return abs(self.size) * self.price

    def is_fresh(self, max_age_ms: int = DEFAULT_MAX_AGE_MS) -> bool:
        return 0 <= self.age_ms <= max_age_ms


def parse_subaccount_fills(
    address: str,
    subaccount_number: int,
    contents: dict,
    now_ms: int,
    source: str = "WS",
) -> list[ScannedFill]:
    """
    Extraire et normaliser les fills d'un message `v4_subaccounts`.

    Le payload Indexer place les fills dans `contents["fills"]`. On reste
    défensif sur les noms de champs (market/ticker, createdAt/createdAtMs).
    Les fills sans id, marché, prix ou horodatage exploitable sont ignorés
    (NO_TRADE implicite — on n'invente jamais de donnée).
    """
    out: list[ScannedFill] = []
    if not isinstance(contents, dict):
        return out
    raw_fills = contents.get("fills") or contents.get("items") or []
    if not isinstance(raw_fills, list):
        return out
    for raw in raw_fills:
        if not isinstance(raw, dict):
            continue
        fill_id = str(raw.get("id") or raw.get("fillId") or "").strip()
        market = str(raw.get("market") or raw.get("ticker") or "").strip()
        if not fill_id or not market:
            continue
        created = (
            raw.get("createdAt")
            or raw.get("createdAtMs")
            or raw.get("created_at")
        )
        created_ms = parse_iso_to_ms(created)
        if created_ms is None:
            continue
        try:
            size = float(raw.get("size", 0) or 0)
            price = float(raw.get("price", 0) or 0)
        except (ValueError, TypeError):
            continue
        if price <= 0 or size == 0:
            continue
        side = str(raw.get("side", "") or "").upper()
        age_ms = int(now_ms - created_ms)
        out.append(
            ScannedFill(
                address=address,
                subaccount_number=int(subaccount_number or 0),
                market_id=market,
                side=side,
                size=size,
                price=price,
                created_at_ms=created_ms,
                fill_id=fill_id,
                age_ms=age_ms,
                source=source,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Déduplication bornée
# --------------------------------------------------------------------------- #
class FillDeduper:
    """
    Déduplication par `fill_id` avec mémoire bornée (FIFO).

    Évite de retraiter un fill vu en WS puis en REST (ou rediffusé après un
    reconnect / gap recovery). Mémoire bornée → pas de fuite sur longue durée.
    """

    def __init__(self, maxlen: int = 200_000) -> None:
        self.maxlen = max(1, maxlen)
        self._seen: set[str] = set()
        self._order: deque[str] = deque()

    def __contains__(self, fill_id: str) -> bool:
        return fill_id in self._seen

    def __len__(self) -> int:
        return len(self._seen)

    def add(self, fill_id: str) -> bool:
        """
        Marquer un fill comme vu. Retourne True si NOUVEAU, False si doublon.
        """
        if not fill_id or fill_id in self._seen:
            return False
        self._seen.add(fill_id)
        self._order.append(fill_id)
        if len(self._order) > self.maxlen:
            old = self._order.popleft()
            self._seen.discard(old)
        return True


# --------------------------------------------------------------------------- #
# Ensemble de wallets "chauds" borné
# --------------------------------------------------------------------------- #
@dataclass
class _HotEntry:
    score: float
    last_seen_ms: int


class HotWalletSet:
    """
    Garde en abonnement live au plus `capacity` wallets, classés par score.

    Permet de "scanner des milliers" de wallets candidats tout en gardant
    l'empreinte WebSocket bornée: seuls les meilleurs/plus actifs restent
    abonnés. `observe()` renvoie (added, removed) pour piloter les
    (dé)souscriptions du client WS.
    """

    def __init__(self, capacity: int = 500) -> None:
        self.capacity = max(1, capacity)
        self._entries: dict[str, _HotEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, address: str) -> bool:
        return address in self._entries

    def active(self) -> set[str]:
        return set(self._entries.keys())

    def observe(
        self, address: str, score: float, now_ms: Optional[int] = None
    ) -> tuple[set[str], set[str]]:
        """
        Insérer/mettre à jour un wallet. Évince le plus faible si dépassement.

        Retourne (added, removed): adresses à abonner / désabonner côté WS.
        """
        if not address:
            return set(), set()
        ts = int(now_ms if now_ms is not None else time.time() * 1000)
        added: set[str] = set()
        removed: set[str] = set()

        existing = self._entries.get(address)
        if existing is not None:
            # Mise à jour: on garde le meilleur score observé, on rafraîchit le ts
            existing.score = max(existing.score, score)
            existing.last_seen_ms = ts
            return added, removed

        self._entries[address] = _HotEntry(score=score, last_seen_ms=ts)
        added.add(address)

        # Éviction si capacité dépassée: plus faible score, puis plus ancien
        while len(self._entries) > self.capacity:
            worst_addr = min(
                self._entries.items(),
                key=lambda kv: (kv[1].score, kv[1].last_seen_ms),
            )[0]
            if worst_addr == address and len(self._entries) == 1:
                break
            del self._entries[worst_addr]
            if worst_addr in added:
                added.discard(worst_addr)
            else:
                removed.add(worst_addr)
        return added, removed

    def evict_stale(self, older_than_ms: int, now_ms: Optional[int] = None) -> set[str]:
        """Retirer les wallets inactifs depuis `older_than_ms`."""
        ts = int(now_ms if now_ms is not None else time.time() * 1000)
        removed = {
            addr
            for addr, e in self._entries.items()
            if ts - e.last_seen_ms > older_than_ms
        }
        for addr in removed:
            del self._entries[addr]
        return removed


# --------------------------------------------------------------------------- #
# Mesure de débit
# --------------------------------------------------------------------------- #
class ThroughputMeter:
    """Compteur glissant de fills frais traités + médiane d'âge."""

    def __init__(self, window_s: float = 10.0) -> None:
        self.window_s = window_s
        self._events: deque[tuple[float, int]] = deque()  # (monotonic_s, age_ms)
        self.total_fills = 0
        self.total_fresh = 0
        self.total_stale = 0
        self.total_duplicates = 0

    def record(self, age_ms: int, monotonic_s: Optional[float] = None) -> None:
        t = monotonic_s if monotonic_s is not None else time.monotonic()
        self._events.append((t, age_ms))
        self._trim(t)

    def _trim(self, now_s: float) -> None:
        cutoff = now_s - self.window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def fills_per_second(self, now_s: Optional[float] = None) -> float:
        t = now_s if now_s is not None else time.monotonic()
        self._trim(t)
        if not self._events:
            return 0.0
        return len(self._events) / self.window_s

    def median_age_ms(self) -> Optional[float]:
        if not self._events:
            return None
        ages = sorted(age for _, age in self._events)
        mid = len(ages) // 2
        if len(ages) % 2:
            return float(ages[mid])
        return (ages[mid - 1] + ages[mid]) / 2.0


# --------------------------------------------------------------------------- #
# Scanner rapide
# --------------------------------------------------------------------------- #
class FastScanner:
    """
    Orchestrateur READ-ONLY: WS temps réel pour les wallets chauds + balayage
    REST rapide pour le reste, déduplication, fenêtre de fraîcheur, métriques.

    Ne contient AUCUNE méthode d'ordre/signature. Produit uniquement des
    `ScannedFill` frais, mis en file et/ou transmis à un callback.
    """

    def __init__(
        self,
        ws_client=None,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
        hot_capacity: int = 500,
        dedupe_maxlen: int = 200_000,
        on_fresh_fill: Optional[Callable[[ScannedFill], None]] = None,
    ) -> None:
        self.ws = ws_client
        self.max_age_ms = max_age_ms
        self.hot = HotWalletSet(capacity=hot_capacity)
        self.deduper = FillDeduper(maxlen=dedupe_maxlen)
        self.meter = ThroughputMeter()
        self._on_fresh = on_fresh_fill
        self._fresh_queue: Queue[ScannedFill] = Queue(maxsize=50_000)
        self._lock = threading.Lock()

    # -- Gestion des wallets chauds (souscriptions WS) ----------------------- #
    def track_wallets(self, scored: Iterable[tuple[str, float]]) -> None:
        """
        Déclarer des wallets candidats (adresse, score). Abonne en WS ceux qui
        entrent dans le hot-set, désabonne ceux évincés. READ-ONLY.
        """
        for address, score in scored:
            # Calcul du hot-set sous verrou; (dé)souscription réseau hors verrou.
            with self._lock:
                added, removed = self.hot.observe(address, score)
            for addr in added:
                self._subscribe(addr)
            for addr in removed:
                self._unsubscribe(addr)

    def _subscribe(self, address: str, subaccount_number: int = 0) -> None:
        if self.ws is None:
            return
        try:
            self.ws.subscribe_subaccount(address, subaccount_number)
        except Exception as e:  # pragma: no cover - dépend du réseau
            logger.debug("subscribe %s échec: %s", address[:12], e)

    def _unsubscribe(self, address: str) -> None:
        # Le client WS actuel ne gère pas le unsubscribe explicite; on retire
        # juste du suivi local. (Hook prêt si l'API WS l'ajoute plus tard.)
        return

    # -- Traitement des messages WS ----------------------------------------- #
    def handle_ws_message(self, msg, now_ms: Optional[int] = None) -> list[ScannedFill]:
        """
        Traiter un `WsMessage` du canal subaccounts: parse → dedupe →
        fraîcheur → file + callback. Retourne les fills FRAIS retenus.
        """
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        channel = getattr(msg, "channel", "") or ""
        if channel != CHANNEL_SUBACCOUNTS:
            return []
        msg_id = getattr(msg, "id", "") or ""
        address, _, sub = msg_id.partition("/")
        subaccount_number = 0
        if sub:
            try:
                subaccount_number = int(sub)
            except ValueError:
                subaccount_number = 0
        data = getattr(msg, "data", {}) or {}
        fills = parse_subaccount_fills(address, subaccount_number, data, now, "WS")
        return self._ingest(fills)

    def ingest_rest_fills(
        self, address: str, subaccount_number: int, raw_contents: dict, now_ms: Optional[int] = None
    ) -> list[ScannedFill]:
        """Variante pour les fills obtenus par balayage REST (fallback)."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        fills = parse_subaccount_fills(address, subaccount_number, raw_contents, now, "REST")
        return self._ingest(fills)

    def _ingest(self, fills: list[ScannedFill]) -> list[ScannedFill]:
        # _ingest peut être appelé depuis le thread WS (callback on_message) ET
        # depuis le thread principal (rest_fast_sweep). On protège l'état mutable
        # partagé (deduper, meter) par un verrou, et on déclenche file + callback
        # HORS verrou pour ne pas bloquer sur un consommateur lent.
        fresh: list[ScannedFill] = []
        with self._lock:
            for f in fills:
                self.meter.total_fills += 1
                if not self.deduper.add(f.fill_id):
                    self.meter.total_duplicates += 1
                    continue
                if not f.is_fresh(self.max_age_ms):
                    self.meter.total_stale += 1
                    continue
                self.meter.total_fresh += 1
                self.meter.record(f.age_ms)
                fresh.append(f)
        for f in fresh:
            try:
                self._fresh_queue.put_nowait(f)
            except Exception:
                pass  # file pleine — perte acceptable, jamais bloquant
            if self._on_fresh is not None:
                try:
                    self._on_fresh(f)
                except Exception as e:  # pragma: no cover
                    logger.debug("callback fresh fill échec: %s", e)
        return fresh

    # -- Balayage REST rapide (fallback, testable via fetch_fn) -------------- #
    def rest_fast_sweep(
        self,
        addresses: Iterable[str],
        fetch_fn: Callable[[str], dict],
        max_workers: int = 16,
        now_ms: Optional[int] = None,
    ) -> list[ScannedFill]:
        """
        Balayer un lot d'adresses en parallèle (borné) via `fetch_fn(address)`
        qui DOIT retourner un dict de contents type Indexer (READ-ONLY).

        `fetch_fn` est injectable → testable sans réseau. Aucune écriture.
        """
        from concurrent.futures import ThreadPoolExecutor

        now = int(now_ms if now_ms is not None else time.time() * 1000)
        results: list[ScannedFill] = []
        addresses = list(addresses)
        if not addresses:
            return results

        def _one(addr: str) -> list[ScannedFill]:
            try:
                contents = fetch_fn(addr)
            except Exception as e:  # pragma: no cover - dépend du réseau
                logger.debug("rest sweep %s échec: %s", addr[:12], e)
                return []
            return parse_subaccount_fills(addr, 0, contents or {}, now, "REST")

        workers = max(1, min(max_workers, len(addresses)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fills in pool.map(_one, addresses):
                results.extend(self._ingest(fills))
        return results

    # -- Sorties ------------------------------------------------------------- #
    def get_fresh(self, timeout_s: float = 0.5) -> Optional[ScannedFill]:
        try:
            return self._fresh_queue.get(timeout=timeout_s)
        except Empty:
            return None

    def drain_fresh(self, limit: int = 1000) -> list[ScannedFill]:
        out: list[ScannedFill] = []
        while len(out) < limit:
            try:
                out.append(self._fresh_queue.get_nowait())
            except Empty:
                break
        return out

    def stats(self) -> dict:
        """État READ-ONLY du scanner pour le dashboard."""
        return {
            "hot_wallets": len(self.hot),
            "hot_capacity": self.hot.capacity,
            "max_age_ms": self.max_age_ms,
            "fills_seen": self.meter.total_fills,
            "fills_fresh": self.meter.total_fresh,
            "fills_stale": self.meter.total_stale,
            "duplicates": self.meter.total_duplicates,
            "dedupe_memory": len(self.deduper),
            "fills_per_second": round(self.meter.fills_per_second(), 3),
            "median_age_ms": self.meter.median_age_ms(),
            "queue_pending": self._fresh_queue.qsize(),
            "read_only": True,
            "paper_only": True,
        }


__all__ = [
    "ScannedFill",
    "FastScanner",
    "HotWalletSet",
    "FillDeduper",
    "ThroughputMeter",
    "parse_subaccount_fills",
    "parse_iso_to_ms",
    "CHANNEL_SUBACCOUNTS",
    "DEFAULT_MAX_AGE_MS",
]
