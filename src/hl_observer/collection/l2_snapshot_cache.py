"""V26 reliquat — Cache de snapshots carnet (l2Book PUBLIC) + coûts live walk-the-book.

Deux morceaux :

* ``compute_book_costs(levels_bid, levels_ask, notional_usd)`` — pur : spread bps
  (best bid/ask) + slippage bps à la taille (walk-the-book, repo 30 rustjesty).
* Cache {coin → (spread_bps, slip_bps, ts)} alimenté par un poller PUBLIC opt-in
  (``HYPERSMART_V26_BOOK_POLLER=1``) qui interroge ``/info {"type":"l2Book"}`` pour
  les coins récemment vus par le moteur (EdgeTrendRecorder), à cadence prudente.

``live_costs_for(coin)`` ne retourne une valeur QUE si le flag consommation
(``HYPERSMART_V26_LIVE_BOOK_COSTS=1``) est actif ET l'entrée fraîche — sinon None
(le scorer garde ses constantes V25). Lecture publique seule, jamais un ordre.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time

from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.ops.echec_silencieux import noter as _noter_echec
from hl_observer.paper_trading.execution_truth import ExecutionTruth

CONSUME_FLAG = "HYPERSMART_V26_LIVE_BOOK_COSTS"
POLLER_FLAG = "HYPERSMART_V26_BOOK_POLLER"
INTERVAL_ENV = "HYPERSMART_V26_BOOK_POLL_INTERVAL_S"
MAX_COINS_ENV = "HYPERSMART_V26_BOOK_POLL_MAX_COINS"
FRESH_ENV = "HYPERSMART_V26_BOOK_FRESH_S"
NOTIONAL_ENV = "HYPERSMART_V26_BOOK_COST_NOTIONAL_USD"
URL_ENV = "HYPERSMART_V26_FUNDING_INFO_URL"   # même endpoint /info que le funding
DEFAULT_INFO_URL = "https://api.hyperliquid.xyz/info"

_DEF = {INTERVAL_ENV: 30.0, MAX_COINS_ENV: 12.0, FRESH_ENV: 90.0, NOTIONAL_ENV: 50.0}

_lock = threading.Lock()
_cache: dict[str, tuple[float, float, float]] = {}   # coin -> (spread_bps, slip_bps, ts)
_book_cache: dict[str, ExecutionTruth] = {}
_started_lock = threading.Lock()
_started = False
_logger = logging.getLogger(__name__)


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    if name not in e:
        return float(_DEF[name])
    try:
        return float(e[name])
    except (TypeError, ValueError, OverflowError):
        return math.nan


def _freshness_age_ms(env: dict | None = None) -> int | None:
    freshness_s = _f(FRESH_ENV, env)
    if not math.isfinite(freshness_s) or freshness_s < 0:
        return None
    freshness_ms = freshness_s * 1_000.0
    if not math.isfinite(freshness_ms) or freshness_ms > (2**63 - 1):
        return None
    return int(freshness_ms)


def _on(flag: str, env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(flag, "0")).strip().lower() in ("1", "true", "yes", "on")


def compute_book_costs(
    levels_bid: list[tuple[float, float]],
    levels_ask: list[tuple[float, float]],
    notional_usd: float,
) -> tuple[float, float] | None:
    """(spread_bps, slippage_bps au notionnel) depuis des niveaux [(px, sz), ...].

    Walk-the-book côté ask (achat) : avg_price vs best, en bps.
    Carnet vide/invalide ⇒ None (jamais de coût inventé).

    🔴 Q2 (2026-07-13) — LA LIGNE QUI INVENTAIT DE LA LIQUIDITÉ :

        if remain_usd2 > 0:
            qty += remain_usd2 / float(levels_ask[-1][0])   # <-- SUPPRIMÉE

    Quand le notionnel demandé dépassait ce que le carnet VISIBLE contient, cette ligne
    prolongeait le dernier niveau **à l'infini**, au même prix. Elle rendait donc un slippage
    faible pile dans le cas où le slippage explose : celui du carnet trop mince. Un coût
    sous-estimé exactement quand il compte n'est pas une approximation — c'est un mensonge
    orienté, et il penche toujours du côté qui fait trader.

    Désormais : profondeur insuffisante ⇒ ``None``. Le carnet ne peut pas absorber le trade,
    donc on ne sait pas ce qu'il coûterait. L'appelant (``fusion_paper_engine_adapter``) traite
    ce ``None`` comme un repli EXPLICITEMENT MARQUÉ (``book_costs_used=False``), jamais comme
    une validation silencieuse.

    Le walk-the-book complet (VWAP, refus, les deux sens) vit dans
    ``hl_observer/arbitrage/executable_legs.py``. Cette fonction-ci reste le raccourci
    « spread + slippage à l'achat » du chemin de coûts.
    """
    return compute_book_costs_with_reason(levels_bid, levels_ask, notional_usd)[0]


def compute_book_costs_with_reason(
    levels_bid: list[tuple[float, float]],
    levels_ask: list[tuple[float, float]],
    notional_usd: float,
) -> tuple[tuple[float, float] | None, str | None]:
    """Compute walk-the-book costs with a stable fail-closed refusal category."""

    try:
        if not levels_bid or not levels_ask:
            return None, "INVALID_BOOK"
        best_bid, best_ask = float(levels_bid[0][0]), float(levels_ask[0][0])
        cible = float(notional_usd)
    except (TypeError, ValueError, OverflowError, IndexError):
        return None, "INVALID_BOOK"
    if not math.isfinite(best_bid) or not math.isfinite(best_ask):
        return None, "INVALID_BOOK"
    if best_bid <= 0.0 or best_ask <= 0.0 or best_ask < best_bid:
        return None, "INVALID_BOOK"
    if not math.isfinite(cible) or cible <= 0.0:
        return None, "INVALID_NOTIONAL"

    mid = best_bid / 2.0 + best_ask / 2.0
    if not math.isfinite(mid) or mid <= 0.0:
        return None, "NUMERIC_OVERFLOW"
    spread_bps = (best_ask - best_bid) / mid * 10_000.0
    if not math.isfinite(spread_bps) or spread_bps < 0.0:
        return None, "NUMERIC_OVERFLOW"

    qty = 0.0
    remaining = cible
    try:
        for raw_px, raw_sz in levels_ask:
            px, sz = float(raw_px), float(raw_sz)
            if not math.isfinite(px) or not math.isfinite(sz) or px <= 0.0 or sz <= 0.0:
                return None, "INVALID_BOOK"
            available_notional = px * sz
            if not math.isfinite(available_notional) or available_notional <= 0.0:
                return None, "NUMERIC_OVERFLOW"
            take_notional = min(remaining, available_notional)
            taken_quantity = take_notional / px
            qty += taken_quantity
            remaining -= take_notional
            if not all(math.isfinite(value) for value in (take_notional, taken_quantity, qty, remaining)):
                return None, "NUMERIC_OVERFLOW"
            if remaining <= 1e-12:
                break
    except (TypeError, ValueError, OverflowError):
        return None, "INVALID_BOOK"

    if remaining > 1e-9:
        return None, "INSUFFICIENT_DEPTH"
    if qty <= 0.0:
        return None, "NUMERIC_OVERFLOW"
    average_price = cible / qty
    if not math.isfinite(average_price) or average_price <= 0.0:
        return None, "NUMERIC_OVERFLOW"
    slip_bps = max(0.0, (average_price - best_ask) / best_ask * 10_000.0)
    if not math.isfinite(slip_bps):
        return None, "NUMERIC_OVERFLOW"
    costs = (round(spread_bps, 4), round(slip_bps, 4))
    if not all(math.isfinite(value) for value in costs):
        return None, "NUMERIC_OVERFLOW"
    return costs, None


def push_costs(coin: str, spread_bps: float, slip_bps: float, ts: float | None = None) -> None:
    key = preserve_native_instrument_symbol(coin)
    if not key:
        return
    with _lock:
        _cache[key] = (float(spread_bps), float(slip_bps), float(ts) if ts is not None else time.time())


def push_book(
    coin: str,
    bids: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    asks: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    *,
    received_ts_ms: int,
    exchange_ts_ms: object = None,
    source: str = "hyperliquid:/info:l2Book",
) -> ExecutionTruth:
    """Store the full causal L2 snapshot used by strict paper execution."""

    truth = ExecutionTruth.from_levels(
        coin=coin,
        bids=bids,
        asks=asks,
        received_ts_ms=received_ts_ms,
        exchange_ts_ms=exchange_ts_ms,
        source=source,
    )
    with _lock:
        _book_cache[truth.coin] = truth
        # Scalar costs are only meaningful for the exact book they summarize.
        _cache.pop(truth.coin, None)
    return truth


def live_costs_for(coin: str, env: dict | None = None, now: float | None = None) -> tuple[float, float] | None:
    """(spread_bps, slip_bps) si flag consommation actif ET entrée fraîche, sinon None."""
    if not _on(CONSUME_FLAG, env):
        return None
    key = preserve_native_instrument_symbol(coin)
    with _lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    spread, slip, ts = entry
    max_age_ms = _freshness_age_ms(env)
    if max_age_ms is None:
        return None
    try:
        t = float(now) if now is not None else time.time()
    except (TypeError, ValueError, OverflowError):
        return None
    age_s = t - ts
    freshness_s = max_age_ms / 1_000.0
    if (
        not math.isfinite(t)
        or not math.isfinite(ts)
        or not math.isfinite(spread)
        or not math.isfinite(slip)
        or spread < 0.0
        or slip < 0.0
        or not math.isfinite(age_s)
        or age_s < 0.0
        or age_s > freshness_s
    ):
        return None  # périmé -> constantes V25 (jamais de coût vieux)
    return spread, slip


def live_execution_truth_for(
    coin: str,
    *,
    decision_ts_ms: int,
    env: dict | None = None,
    require_consume_flag: bool = True,
) -> ExecutionTruth | None:
    """Return a fresh full book, never a scalar-depth substitute."""

    if require_consume_flag and not _on(CONSUME_FLAG, env):
        return None
    key = preserve_native_instrument_symbol(coin)
    with _lock:
        truth = _book_cache.get(key)
    if truth is None:
        return None
    max_age_ms = _freshness_age_ms(env)
    if max_age_ms is None:
        return None
    if truth.timestamp_refusal_reason(
        decision_ts_ms=decision_ts_ms,
        max_age_ms=max_age_ms,
    ) is not None:
        return None
    return truth


def live_execution_truth_refusal_for(
    coin: str,
    *,
    decision_ts_ms: int,
    env: dict | None = None,
    require_consume_flag: bool = True,
) -> str | None:
    """Explain why a cached book cannot support a strict paper execution."""

    if require_consume_flag and not _on(CONSUME_FLAG, env):
        return "LIVE_BOOK_CONSUMPTION_DISABLED"
    key = preserve_native_instrument_symbol(coin)
    with _lock:
        truth = _book_cache.get(key)
    if truth is None:
        return "NO_LIVE_EXECUTABLE_BOOK"
    max_age_ms = _freshness_age_ms(env)
    if max_age_ms is None:
        return "INVALID_L2_FRESHNESS_CONFIG"
    return truth.timestamp_refusal_reason(
        decision_ts_ms=decision_ts_ms,
        max_age_ms=max_age_ms,
    )


def parse_l2book(payload: object) -> tuple[list[tuple[float, float]], list[tuple[float, float]]] | None:
    """Extrait ([(bid_px, sz)...], [(ask_px, sz)...]) du retour public l2Book."""
    try:
        levels = payload.get("levels")  # type: ignore[union-attr]
        bids = [(float(level["px"]), float(level["sz"])) for level in levels[0]]
        asks = [(float(level["px"]), float(level["sz"])) for level in levels[1]]
        if not bids or not asks:
            return None
        return bids, asks
    except Exception:
        return None


def poll_once(coins: list[str], *, opener=None, env: dict | None = None) -> int:
    """Un cycle : l2Book public pour chaque coin -> coûts -> cache. Retourne nb maj."""
    n = 0
    notional = _f(NOTIONAL_ENV, env)
    e = env if env is not None else os.environ
    target = str(e.get(URL_ENV, "") or DEFAULT_INFO_URL)
    for coin in coins:
        try:
            body = json.dumps({"type": "l2Book", "coin": coin}).encode("utf-8")
            if opener is not None:
                raw = opener(target, body, 10.0)
            else:  # pragma: no cover — réseau réel, opt-in runtime seulement
                import urllib.request

                req = urllib.request.Request(
                    target, data=body, headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    raw = resp.read()
            decoded = json.loads(raw.decode("utf-8"))
            parsed = parse_l2book(decoded)
            if parsed is None:
                continue
            received_ts_ms = int(time.time() * 1_000)
            raw_exchange_ts = decoded.get("time") if isinstance(decoded, dict) else None
            truth = push_book(
                coin,
                parsed[0],
                parsed[1],
                received_ts_ms=received_ts_ms,
                exchange_ts_ms=raw_exchange_ts,
                source=f"hyperliquid:/info:l2Book:{target}",
            )
            key = preserve_native_instrument_symbol(coin)
            if truth is not None and truth.timestamp_refusal_reason(
                decision_ts_ms=received_ts_ms,
            ) is None:
                costs = compute_book_costs(parsed[0], parsed[1], notional)
                with _lock:
                    # Do not publish costs if a newer concurrent poll replaced the book.
                    if _book_cache.get(key) is truth and costs is not None:
                        _cache[key] = (
                            costs[0], costs[1], received_ts_ms / 1_000.0
                        )
            else:
                # A cost derived from a temporally invalid book is not usable.
                with _lock:
                    if _book_cache.get(key) is truth:
                        _cache.pop(key, None)
            # ENREGISTREMENT (audit PnL 2026-07-11, opt-in HYPERSMART_RECORD_MICROSTRUCTURE=1).
            # Ce poller recuperait DEJA le carnet complet et le JETAIT apres en avoir tire deux
            # chiffres. Or le carnet est la seule donnee qui permette de tester les strategies
            # dont l'esperance ne depend PAS d'une prediction (market making : on ENCAISSE le
            # spread au lieu de le payer). Le copy-trading, lui, est mesure sans edge : meme a
            # cout zero son esperance est negative. On garde donc la donnee, sans un seul appel
            # reseau supplementaire. Best-effort : jamais bloquant pour la boucle.
            try:
                from hl_observer.collection import microstructure_recorder as _mr

                if _mr.enabled():
                    _base = str(e.get("HYPERSMART_V26_RECORD_PATH", "") or "runtime/replay")
                    _mr.record_l2(_base, coin, json.loads(raw.decode("utf-8")))
            except Exception:
                _noter_echec("hl_observer/collection/l2_snapshot_cache.py:199")
            n += 1
        except Exception:
            continue
    return n


DEFAUT_COINS_ENV = "HYPERSMART_V26_BOOK_DEFAULT_COINS"
DEFAUT_COINS = ("BTC", "ETH", "SOL")


BALAYAGE_FLAG = "HYPERSMART_V26_BOOK_SWEEP_ALL"      # balayer TOUS les marches, par rotation
_curseur = [0]                                        # position dans le balayage (mutable, borne)


def _tous_les_marches() -> list[str]:
    """Tous les marches connus, via le cache funding (deja alimente, zero requete en plus)."""
    try:
        from hl_observer.funding import funding_runtime_cache as _frc

        coins = getattr(_frc, "known_coins", None)
        if callable(coins):
            return sorted({preserve_native_instrument_symbol(c) for c in (coins() or []) if c})
    except Exception:
        _noter_echec("hl_observer/collection/l2_snapshot_cache.py:223")
    return []


def _tranche_rotative(univers: list[str], taille: int) -> list[str]:
    """La tranche suivante du balayage. Le curseur avance a chaque cycle et boucle."""
    if not univers or taille <= 0:
        return []
    n = len(univers)
    debut = _curseur[0] % n
    tranche = [univers[(debut + i) % n] for i in range(min(taille, n))]
    _curseur[0] = (debut + len(tranche)) % n
    return tranche


def coins_a_sonder(*, limit: int, universe=None, recorder=None, env: dict | None = None) -> list[str]:
    """Quels marches sonder ? PURE, testable, et surtout : **jamais vide sans raison**.

    LE BUG DE FOND (2026-07-11) : le poller prenait ses coins d'une seule source. Cette source
    etait vide -> il sondait RIEN -> aucun carnet n'etait recuperé -> tous les couts retombaient
    sur des constantes -> et aucune donnee de carnet n'existait pour tester le market making.
    Pendant ce temps le flag etait allume et personne ne s'en plaignait.

    Une liste vide ne doit JAMAIS pouvoir eteindre silencieusement la collecte. Collecter des
    donnees n'est pas ouvrir une position : le deny-by-default protege les ORDRES, pas les
    OCTETS. Ici, en cas de doute, on collecte.

    Ordre : coins reellement observes -> recorder d'edge -> socle par defaut (jamais vide).
    """
    e = env if env is not None else os.environ
    lim = max(1, int(limit))
    vus: list[str] = []
    try:
        if universe is not None:
            vus = list(universe.coins(limit=lim))
    except Exception:
        vus = []
    if not vus and recorder is not None:
        try:
            vus = list(recorder.coins())[:lim]
        except Exception:
            vus = []
    # BALAYAGE COMPLET (2026-07-12) -- pour repondre a "existe-t-il un marche assez large ?", il
    # faut voir TOUS les marches, pas les 8 majors. On tourne : `lim` coins par cycle, et on
    # avance dans la liste. En ~4 min a 30 coins / 10 s, les ~230 marches Hyperliquid sont
    # couverts, sans une seule requete de plus par cycle.
    if _on(BALAYAGE_FLAG, e):
        univers = _tous_les_marches()
        if univers:
            vus = list(vus) + _tranche_rotative(univers, lim)

    if not vus:
        brut = str(e.get(DEFAUT_COINS_ENV, "") or "").strip()
        socle = [c.strip().upper() for c in brut.split(",") if c.strip()] or list(DEFAUT_COINS)
        vus = socle[:lim]
    # dedoublonne en gardant l'ordre
    vu, sortie = set(), []
    for c in vus:
        cc = str(c or "").strip().upper()
        if cc and cc not in vu:
            vu.add(cc)
            sortie.append(cc)
    return sortie[:lim]


def _loop(interval_s: float, max_coins: int) -> None:  # pragma: no cover — boucle démon runtime
    while True:
        try:
            # BUG CORRIGE 2026-07-11 -- CETTE LISTE ETAIT TOUJOURS VIDE.
            # Le poller demandait ses coins a DEFAULT_EDGE_TREND_RECORDER, dont la seule fonction
            # de remplissage (`record_edge_observation`) n'etait appelee NULLE PART. Resultat : il
            # sondait une liste vide, le carnet n'etait jamais recupere, et tous les couts
            # retombaient sur des constantes -- malgre le flag allume.
            from hl_observer.collection import coin_universe as _cu
            from hl_observer.signals.v26_entry_vetos import DEFAULT_EDGE_TREND_RECORDER

            coins = coins_a_sonder(limit=max_coins, universe=_cu, recorder=DEFAULT_EDGE_TREND_RECORDER)
            if coins:
                poll_once(coins)
        except Exception:
            _noter_echec("hl_observer/collection/l2_snapshot_cache.py:304")
        time.sleep(max(10.0, interval_s))


def _poller_config_refusal(env: dict | None = None) -> str | None:
    interval_s = _f(INTERVAL_ENV, env)
    if (
        not math.isfinite(interval_s)
        or interval_s <= 0.0
        or interval_s > threading.TIMEOUT_MAX
    ):
        return "INVALID_L2_POLL_INTERVAL"
    max_coins_value = _f(MAX_COINS_ENV, env)
    if (
        not math.isfinite(max_coins_value)
        or max_coins_value < 1.0
        or not max_coins_value.is_integer()
        or max_coins_value > sys.maxsize
    ):
        return "INVALID_L2_POLL_MAX_COINS"
    return None


def ensure_started(env: dict | None = None) -> bool:
    """Démarre le poller carnet UNE fois si opt-in. Sinon no-op (aucun réseau)."""
    global _started
    if not _on(POLLER_FLAG, env):
        return False
    refusal = _poller_config_refusal(env)
    if refusal is not None:
        _logger.warning("L2 poller startup refused: %s", refusal)
        return False
    interval_s = _f(INTERVAL_ENV, env)
    max_coins_value = _f(MAX_COINS_ENV, env)
    with _started_lock:
        if _started:
            return True
        t = threading.Thread(
            target=_loop,
            args=(interval_s, int(max_coins_value)),
            daemon=True,
            name="v26-book-poller",
        )
        t.start()
        _started = True
        return True


def clear() -> None:
    with _lock:
        _cache.clear()
        _book_cache.clear()


__all__ = [
    "CONSUME_FLAG", "POLLER_FLAG", "compute_book_costs", "compute_book_costs_with_reason", "push_costs",
    "live_costs_for", "live_execution_truth_for", "live_execution_truth_refusal_for", "push_book",
    "parse_l2book", "poll_once", "ensure_started", "clear",
    "coins_a_sonder", "DEFAUT_COINS", "DEFAUT_COINS_ENV", "BALAYAGE_FLAG",
]
