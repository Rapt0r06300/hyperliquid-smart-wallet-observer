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
import os
import threading
import time
from hl_observer.ops.echec_silencieux import noter as _noter_echec

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
_started_lock = threading.Lock()
_started = False


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEF[name]) or _DEF[name])
    except (TypeError, ValueError):
        return float(_DEF[name])


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
    try:
        if not levels_bid or not levels_ask:
            return None
        best_bid, best_ask = float(levels_bid[0][0]), float(levels_ask[0][0])
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            return None
        mid = (best_bid + best_ask) / 2.0
        spread_bps = (best_ask - best_bid) / mid * 10_000.0

        cible = float(notional_usd)
        if not (cible > 0.0):
            return None

        # walk-the-book : quantité acquise niveau par niveau pour le notionnel visé
        qty = 0.0
        remain_usd2 = cible
        for px, sz in levels_ask:
            px, sz = float(px), float(sz)
            if px <= 0.0 or sz <= 0.0:
                continue
            take_usd = min(remain_usd2, px * sz)
            qty += take_usd / px
            remain_usd2 -= take_usd
            if remain_usd2 <= 1e-12:
                break

        if remain_usd2 > 1e-9:
            # Le carnet VISIBLE ne peut pas absorber ce notionnel. On ne l'invente pas.
            return None
        if qty <= 0.0:
            return None

        avg_px = cible / qty
        slip_bps = max(0.0, (avg_px - best_ask) / best_ask * 10_000.0)
        return round(spread_bps, 4), round(slip_bps, 4)
    except Exception:
        return None


def push_costs(coin: str, spread_bps: float, slip_bps: float, ts: float | None = None) -> None:
    key = (coin or "").strip().upper()
    if not key:
        return
    with _lock:
        _cache[key] = (float(spread_bps), float(slip_bps), float(ts) if ts is not None else time.time())


def live_costs_for(coin: str, env: dict | None = None, now: float | None = None) -> tuple[float, float] | None:
    """(spread_bps, slip_bps) si flag consommation actif ET entrée fraîche, sinon None."""
    if not _on(CONSUME_FLAG, env):
        return None
    key = (coin or "").strip().upper()
    with _lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    spread, slip, ts = entry
    t = float(now) if now is not None else time.time()
    if t - ts > _f(FRESH_ENV, env):
        return None  # périmé -> constantes V25 (jamais de coût vieux)
    return spread, slip


def parse_l2book(payload: object) -> tuple[list[tuple[float, float]], list[tuple[float, float]]] | None:
    """Extrait ([(bid_px, sz)...], [(ask_px, sz)...]) du retour public l2Book."""
    try:
        levels = payload.get("levels")  # type: ignore[union-attr]
        bids = [(float(l["px"]), float(l["sz"])) for l in levels[0]]
        asks = [(float(l["px"]), float(l["sz"])) for l in levels[1]]
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
            parsed = parse_l2book(json.loads(raw.decode("utf-8")))
            if parsed is None:
                continue
            costs = compute_book_costs(parsed[0], parsed[1], notional)
            if costs is None:
                continue
            push_costs(coin, costs[0], costs[1])
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
            return sorted({str(c).upper() for c in (coins() or []) if c})
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


def _loop(interval_s: float) -> None:  # pragma: no cover — boucle démon runtime
    while True:
        try:
            # BUG CORRIGE 2026-07-11 -- CETTE LISTE ETAIT TOUJOURS VIDE.
            # Le poller demandait ses coins a DEFAULT_EDGE_TREND_RECORDER, dont la seule fonction
            # de remplissage (`record_edge_observation`) n'etait appelee NULLE PART. Resultat : il
            # sondait une liste vide, le carnet n'etait jamais recupere, et tous les couts
            # retombaient sur des constantes -- malgre le flag allume.
            from hl_observer.collection import coin_universe as _cu
            from hl_observer.signals.v26_entry_vetos import DEFAULT_EDGE_TREND_RECORDER

            _limite = int(_f(MAX_COINS_ENV))
            coins = coins_a_sonder(limit=_limite, universe=_cu, recorder=DEFAULT_EDGE_TREND_RECORDER)
            if coins:
                poll_once(coins)
        except Exception:
            _noter_echec("hl_observer/collection/l2_snapshot_cache.py:304")
        time.sleep(max(10.0, interval_s))


def ensure_started(env: dict | None = None) -> bool:
    """Démarre le poller carnet UNE fois si opt-in. Sinon no-op (aucun réseau)."""
    global _started
    if not _on(POLLER_FLAG, env):
        return False
    with _started_lock:
        if _started:
            return True
        t = threading.Thread(target=_loop, args=(_f(INTERVAL_ENV, env),), daemon=True, name="v26-book-poller")
        t.start()
        _started = True
        return True


def clear() -> None:
    with _lock:
        _cache.clear()


__all__ = [
    "CONSUME_FLAG", "POLLER_FLAG", "compute_book_costs", "push_costs",
    "live_costs_for", "parse_l2book", "poll_once", "ensure_started", "clear",
    "coins_a_sonder", "DEFAUT_COINS", "DEFAUT_COINS_ENV", "BALAYAGE_FLAG",
]
