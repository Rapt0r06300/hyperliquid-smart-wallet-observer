"""COLLECTEUR BBO RAPIDE HL↔Binance — PERSISTANT, horloge MONOTONE (23/07, chantier ARB).

POURQUOI CETTE VERSION (correction critique de Flo). Pour mesurer un lead-lag de ~100-700 ms :
  * le processus doit être VRAIMENT PERSISTANT — pas relancé toutes les 300 s (ça briserait la
    continuité). Il reconnecte SEULEMENT sur panne, garde son état (`MagasinBBO`), et est supervisé
    par HEARTBEAT + garde anti-orphelin interne (il sort si la session du lanceur a changé) ;
  * chaque message HL et Binance est horodaté DÈS SA RÉCEPTION avec **la même horloge MONOTONE locale**
    (`time.monotonic_ns()`). L'âge et la synchro se calculent sur CETTE horloge, jamais sur les
    timestamps exchange (skew entre venues). *Sans ça, un décalage d'horloge ressemble à un edge.*
  * on conserve AUSSI les timestamps EXCHANGE quand ils existent, les UPDATE IDs (Binance `u`), le
    compte de RECONNEXIONS et les TROUS de données — pour que la qualité soit auditable, pas supposée.

Le lead-lag se mesure ENSUITE sur ces snapshots (`lead_lag_shadow.py`), en shadow, jamais un ordre.
READ-ONLY / PAPER-ONLY : deux flux PUBLICS en lecture. Aucune clé, aucun ordre, aucune signature.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
import heartbeat_collecteur as HB  # noqa: E402

WS_HL = "wss://api.hyperliquid.xyz/ws"
INFO_HL = "https://api.hyperliquid.xyz/info"
WS_BINANCE = "wss://fstream.binance.com/stream"
SORTIE = Path("runtime") / "data" / "bbo_synchro.jsonl"
TAPE = Path("runtime") / "data" / "bbo_tape.jsonl"     # chaque message BBO (monotone) -> lead-lag fin
HEARTBEAT = Path("runtime") / "data" / "bbo_heartbeat.json"
FEED_QUALITY = Path("runtime") / "data" / "feed_quality.json"
TICK_DATASET_DIR = Path("runtime") / "data" / "market_ticks"
MARQUEUR = Path("runtime") / "data" / "lanceur_session_marqueur.txt"
AGE_MAX_MS = 750.0                 # au-delà (horloge MONOTONE), quote périmée -> rejet
FENETRE_SYNCHRO_MS = 250.0         # HL et Binance frais à moins de ça l'un de l'autre (monotone)
GAP_MS = 5000.0                    # aucun message d'une venue pendant ça = TROU de données noté
#: 🔴 garde-fou DISQUE + PREUVES. La tape brute grossit ~1 Go/h. Plutot que RENOMMER (qui DETRUIT
#: l'historique au-dela de 2×), on SCELLE la tape vivante en SHARD COMPRESSE IMMUABLE (.jsonl.gz,
#: ~10× plus petit) quand elle depasse SHARD_OCTETS, puis retention BORNEE (purge du plus vieux au-dela
#: de MAX_SHARDS). Ainsi on garde des JOURS d'historique pour le forward/OOS sans jamais remplir le disque.
SHARDS_DIR = Path("runtime") / "data" / "bbo_shards"
ARCHIVE_DIR = Path("runtime") / "data" / "bbo_shards_archive"   # historique PRÉSERVÉ (jamais supprimé, Flo 25/07)
SHARD_OCTETS = 80 * 1024 * 1024
MAX_SHARDS = 60                    # ~60 shards gz (~0,6-1 Go compresses, plusieurs jours) puis purge FIFO
TICK_QUEUE_MAX = 100_000           # protege la socket; toute eviction est comptee et degrade la qualite

_EXCEPTIONS = {"PEPE": "1000PEPEUSDT", "SHIB": "1000SHIBUSDT", "BONK": "1000BONKUSDT",
               "FLOKI": "1000FLOKIUSDT", "LUNC": "1000LUNCUSDT", "SATS": "1000SATSUSDT",
               "RATS": "1000RATSUSDT", "XEC": "1000XECUSDT", "WHYPE": None, "HYPE": None}

#: LIQUIDATION_LIVE_COVERAGE_V1 (25/07). Le HL WS bbo couvre N'IMPORTE QUEL coin (memes inclus) ; la
#: jointure Binance est ignorée si le coin n'y est pas. On garde donc un BBO/L2 synchronisé sur les coins
#: où les liquidations ARRIVENT — sinon 0 couverture (les 71 épisodes étaient sur ONDO/AAVE/HYPE/memes,
#: hors des 8 majors). La tape bbo_tape.jsonl EST le ring-buffer (continu, avant + après l'événement).
MAJORS_BBO = ("BTC", "ETH", "SOL", "INJ", "DASH", "NEO", "AVAX", "LINK")
LIQ_CONFIRMEES_REL = Path("runtime") / "data" / "liquidations_confirmees.jsonl"
LEAD_LAG_CONFIG_REL = Path("runtime") / "data" / "lead_lag_config_gele.json"


def extraire_symboles_hyperliquid(meta: Any) -> list[str]:
    """Return case-sensitive perpetual symbols exposed by ``/info meta``."""

    if not isinstance(meta, dict) or not isinstance(meta.get("universe"), list):
        raise ValueError("reponse /info meta invalide")
    symbols: list[str] = []
    seen: set[str] = set()
    for item in meta["universe"]:
        name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
        key = name.upper()
        if name and key not in seen:
            symbols.append(name)
            seen.add(key)
    if not symbols:
        raise ValueError("univers Hyperliquid vide")
    return symbols


def charger_symboles_hyperliquid(*, timeout: float = 8.0) -> list[str]:
    """Read the live universe through Hyperliquid's read-only ``/info`` API."""

    import urllib.request

    request = urllib.request.Request(
        INFO_HL,
        data=json.dumps({"type": "meta"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL
        payload = json.loads(response.read().decode("utf-8-sig"))
    return extraire_symboles_hyperliquid(payload)


def resoudre_symboles_hyperliquid(
    coins: list[str],
    universe: list[str],
) -> tuple[list[str], list[str]]:
    """Resolve normalized local names to exact WS names; omit unknown coins."""

    by_normalized = {
        str(symbol).upper(): str(symbol)
        for symbol in universe
        if str(symbol).strip()
    }
    selected: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw_coin in coins:
        normalized = str(raw_coin or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        exact = by_normalized.get(normalized)
        if exact is None:
            rejected.append(normalized)
        else:
            selected.append(exact)
    return selected, rejected


def coins_lead_lag_promus(root: Path | str = ".") -> list[str]:
    """Return coins from the validated frozen Lead-Lag evidence, or none.

    Invalid/unfrozen evidence never expands live subscriptions. This is coverage
    only: it cannot create a paper decision and has no execution surface.
    """
    path = Path(root) / LEAD_LAG_CONFIG_REL
    if not path.is_file():
        return []
    try:
        from hl_observer.backtesting.lead_lag_evidence import load_frozen_evidence
        config = load_frozen_evidence(path)
    except Exception as exc:  # evidence invalid => fail closed, but observable
        import logging
        logging.getLogger(__name__).warning(
            "lead-lag frozen coverage ignored: %s", exc.__class__.__name__
        )
        return []
    selected: list[str] = []
    for raw in config.get("coins") or []:
        coin = str(raw or "").strip().upper()
        if coin and coin not in selected:
            selected.append(coin)
    return selected


def coins_couverture(root: Path | str = ".", *, k: int = 16) -> list[str]:
    """Majors + les K coins les PLUS FRÉQUENTS des liquidations confirmées (journal). Relu à CHAQUE
    démarrage -> tout NOUVEAU coin de liquidation entre dans la couverture. Borné (majors + K). Pur."""
    import collections
    coins = list(MAJORS_BBO)
    try:
        recs = [json.loads(l) for l in (Path(root) / LIQ_CONFIRMEES_REL).open(encoding="utf-8") if l.strip()]
        for coin, _ in collections.Counter(r.get("coin") for r in recs if r.get("coin")).most_common(k):
            cu = str(coin).upper()
            if cu and cu not in coins:
                coins.append(cu)
    except (OSError, ValueError):
        import logging
        logging.getLogger(__name__).debug("liquidation coverage journal unavailable", exc_info=True)
    # A frozen/promoted Lead-Lag coin must never be absent merely because it is
    # neither a hard-coded major nor a frequent liquidation coin.
    for coin in coins_lead_lag_promus(root):
        if coin not in coins:
            coins.append(coin)
    return coins


def symbole_binance(coin_hl: str) -> str | None:
    """Symbole perp Binance correspondant EXACTEMENT au coin HL, ou None si non mappable (refus)."""
    c = str(coin_hl or "").upper().strip()
    if not c:
        return None
    if c in _EXCEPTIONS:
        return _EXCEPTIONS[c]
    if c.startswith("K") and len(c) > 1 and c[1:].isalpha():
        return "1000" + c[1:] + "USDT"
    if not c.isalnum():
        return None
    return c + "USDT"


def _f(x: Any) -> float | None:
    try:
        v = float(x)
        return v if v == v and v > 0 else None
    except (TypeError, ValueError):
        return None


def parser_bbo_hl(msg: Any) -> dict | None:
    """WS HL `bbo` -> {coin, bid, ask, bid_sz, ask_sz, ts_ex}. Autre message -> None."""
    if not isinstance(msg, dict) or msg.get("channel") != "bbo":
        return None
    d = msg.get("data") or {}
    bbo = d.get("bbo") or []
    try:
        bid, ask = bbo[0], bbo[1]
        b, a = _f(bid.get("px")), _f(ask.get("px"))
    except (IndexError, AttributeError, TypeError):
        return None
    if b is None or a is None or a < b:
        return None
    return {"coin": str(d.get("coin") or "").upper(), "bid": b, "ask": a,
            "bid_sz": _f(bid.get("sz")) or 0.0, "ask_sz": _f(ask.get("sz")) or 0.0,
            "ts_ex": float(d.get("time") or 0.0)}


def parser_l2_hl(msg: Any) -> dict | None:
    """WS HL ``l2Book`` -> full snapshot, never an invented incremental update."""
    if not isinstance(msg, dict) or msg.get("channel") != "l2Book":
        return None
    data = msg.get("data") or {}
    levels = data.get("levels") or []
    if not isinstance(levels, list) or len(levels) < 2:
        return None
    bids = levels[0] if isinstance(levels[0], list) else []
    asks = levels[1] if isinstance(levels[1], list) else []
    if not bids or not asks:
        return None
    return {
        "coin": str(data.get("coin") or "").upper(),
        "bids": bids,
        "asks": asks,
        "ts_ex": int(float(data.get("time") or 0.0)),
    }


def parser_trades_hl(msg: Any) -> list[dict]:
    """WS HL public ``trades`` -> independent exchange events.

    The channel is not labelled as an initial snapshot by Hyperliquid, so this
    parser never guesses ``isSnapshot`` from "first message on a connection".
    """
    if not isinstance(msg, dict) or msg.get("channel") != "trades":
        return []
    data = msg.get("data") or []
    if not isinstance(data, list):
        return []
    return [trade for trade in data if isinstance(trade, dict)]


def parser_bookticker_binance(msg: Any) -> dict | None:
    """WS Binance `<sym>@bookTicker` -> {symbol, bid, ask, bid_sz, ask_sz, ts_ex, update_id}."""
    d = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
    if not isinstance(d, dict) or "s" not in d:
        return None
    b, a = _f(d.get("b")), _f(d.get("a"))
    if b is None or a is None or a < b:
        return None
    return {"symbol": str(d.get("s")).upper(), "bid": b, "ask": a,
            "bid_sz": _f(d.get("B")) or 0.0, "ask_sz": _f(d.get("A")) or 0.0,
            "ts_ex": float(d.get("T") or d.get("E") or 0.0), "update_id": d.get("u")}


def parser_aggtrade_binance(msg: Any) -> dict | None:
    """WS Binance `<sym>@trade` (ou `@aggTrade`) -> {symbol, px, sz, side, ts_ex}. Le CHOC exécutable
    (Flo : détecter le choc sur les TRADES, pas le mid). `m`=True -> l'agressif est le VENDEUR.
    🔴 23/07 PROUVÉ AU NAVIGATEUR (même réseau que le bot) : `fstream …@aggTrade` ouvre mais ne pousse
    ZÉRO frame (0 vs 9827 bookTicker en 6 s), alors que `@trade` en pousse 548/6 s. On accepte donc les
    DEUX `e` : `trade` (utilisé, trades individuels, plus granulaires) et `aggTrade` (si jamais rétabli)."""
    d = msg.get("data") if isinstance(msg, dict) and "data" in msg else msg
    if not isinstance(d, dict) or d.get("e") not in ("trade", "aggTrade") or "p" not in d:
        return None
    px = _f(d.get("p"))
    if px is None:
        return None
    return {"symbol": str(d.get("s")).upper(), "px": px, "sz": _f(d.get("q")) or 0.0,
            "side": "SELL" if d.get("m") else "BUY", "ts_ex": float(d.get("T") or 0.0)}


def dispatch_lead_lag_trade(
    runtime: Any,
    trade_event: dict[str, Any],
    hl_quote: dict[str, Any] | None,
    *,
    now_ms: int,
) -> Any:
    """Dispatch inline; a diagnostic failure must never stop market capture."""

    try:
        return runtime.on_trade(trade_event, hl_quote, now_ms=now_ms)
    except Exception:
        return None


class MagasinBBO:
    """Dernier BBO de chaque venue par coin, horodaté sur l'horloge MONOTONE de réception. Ne produit
    un snapshot SYNCHRONISÉ que si les DEUX venues sont FRAÎCHES (âge monotone < AGE_MAX) et proches."""

    def __init__(self, *, age_max_ms: float = AGE_MAX_MS, fenetre_ms: float = FENETRE_SYNCHRO_MS):
        self.hl: dict[str, dict] = {}
        self.bin: dict[str, dict] = {}
        self.age_max_ms = age_max_ms
        self.fenetre_ms = fenetre_ms

    def maj_hl(
        self,
        q: dict,
        *,
        recu_mono_ns: int,
        recu_wall_ms: int,
        connection_id: str | None = None,
        sequence: int | None = None,
    ) -> None:
        self.hl[q["coin"]] = {
            **q,
            "recu_ns": recu_mono_ns,
            "recv_wall_ts_ms": int(recu_wall_ms),
            "connection_id": connection_id,
            "sequence": sequence,
        }

    def maj_binance(
        self,
        q: dict,
        coin_hl: str,
        *,
        recu_mono_ns: int,
        recu_wall_ms: int,
        connection_id: str | None = None,
        sequence: int | None = None,
    ) -> None:
        self.bin[coin_hl] = {
            **q,
            "recu_ns": recu_mono_ns,
            "recv_wall_ts_ms": int(recu_wall_ms),
            "connection_id": connection_id,
            "sequence": sequence,
        }

    def snapshot(self, coin: str, *, now_mono_ns: int, ts_wall_ms: float) -> dict | None:
        """Snapshot synchronisé FRAIS, âges/synchro sur l'horloge MONOTONE. None si rejeté."""
        h, b = self.hl.get(coin), self.bin.get(coin)
        if not h or not b:
            return None
        age_h = (now_mono_ns - h["recu_ns"]) / 1e6
        age_b = (now_mono_ns - b["recu_ns"]) / 1e6
        if age_h > self.age_max_ms or age_b > self.age_max_ms:
            return None                                        # quote périmée -> rejet
        desync = abs(h["recu_ns"] - b["recu_ns"]) / 1e6
        if desync > self.fenetre_ms:
            return None                                        # pas assez synchrones -> rejet
        hmid, bmid = (h["bid"] + h["ask"]) / 2, (b["bid"] + b["ask"]) / 2
        snapshot_wall_ts_ms = int(ts_wall_ms)
        event_id = "bbo_pair:%s:%s:%s" % (
            coin,
            h["recv_wall_ts_ms"],
            b["recv_wall_ts_ms"],
        )
        return {"coin": coin, "ts_ms": snapshot_wall_ts_ms,
                "snapshot_wall_ts_ms": snapshot_wall_ts_ms,
                "write_wall_ts_ms": snapshot_wall_ts_ms,
                "event_id": event_id,
                "hl_bid": h["bid"], "hl_ask": h["ask"], "bin_bid": b["bid"], "bin_ask": b["ask"],
                "hl_mid": hmid, "bin_mid": bmid, "ecart_mid_bps": round(1e4 * (hmid - bmid) / bmid, 3),
                "taille_top_usd": round(min(h["bid_sz"] * hmid, b["bid_sz"] * bmid), 2),
                "ts_ex_hl": h.get("ts_ex"), "ts_ex_bin": b.get("ts_ex"),
                "exchange_ts_hl_ms": h.get("ts_ex"), "exchange_ts_bin_ms": b.get("ts_ex"),
                "recv_wall_hl_ms": h["recv_wall_ts_ms"],
                "recv_wall_bin_ms": b["recv_wall_ts_ms"],
                "connection_id_hl": h.get("connection_id"),
                "connection_id_bin": b.get("connection_id"),
                "sequence_hl": h.get("sequence"), "sequence_bin": b.get("sequence"),
                "update_id_bin": b.get("update_id"),
                "recu_mono_hl_ns": h["recu_ns"], "recu_mono_bin_ns": b["recu_ns"],
                "age_hl_ms": round(age_h, 2), "age_bin_ms": round(age_b, 2), "desync_ms": round(desync, 2),
                "read_only": True, "real_execution": False}


def mesurer_lead_lag(series: list[tuple[float, float, float]], *, lag_ms: float) -> float | None:
    """Corrélation Δ(mid Binance) à t vs Δ(mid HL) à t+lag, sur (ts_mono_ms, hl_mid, bin_mid).
    > 0 croissant avec lag -> Binance MÈNE HL. None si pas assez de points."""
    s = sorted(series)
    if len(s) < 30:
        return None
    import bisect
    ts = [x[0] for x in s]
    dbin, dhl = [], []
    for i in range(1, len(s)):
        db = s[i][2] - s[i - 1][2]
        j = bisect.bisect_left(ts, s[i][0] + lag_ms)
        if j <= 0 or j >= len(s):
            continue
        dbin.append(db); dhl.append(s[j][1] - s[j - 1][1])
    if len(dbin) < 20:
        return None
    import statistics as st
    mb, mh = st.mean(dbin), st.mean(dhl)
    num = sum((dbin[k] - mb) * (dhl[k] - mh) for k in range(len(dbin)))
    den = (sum((x - mb) ** 2 for x in dbin) * sum((x - mh) ** 2 for x in dhl)) ** 0.5
    return round(num / den, 4) if den > 0 else None


def sceller_shard(root: Path, *, seuil_octets: int = SHARD_OCTETS, max_shards: int = MAX_SHARDS) -> str | None:
    """SCELLE la tape vivante en shard IMMUABLE compresse (gzip) + retention FIFO bornee. Preserve
    l'historique pour le forward/OOS sans laisser le disque exploser. None si la tape est trop petite.
    Appelee UNIQUEMENT depuis la tache d'ecriture, juste apres un flush (aucune ecriture concurrente
    du fichier entre le flush et le scellement : asyncio mono-thread, pas d'await entre les deux)."""
    import gzip
    import os
    src = root / TAPE
    if not src.exists() or src.stat().st_size < seuil_octets:
        return None
    dossier = root / SHARDS_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    nom = "bbo_tape_%d.jsonl.gz" % time.time_ns()
    tmp = dossier / (nom + ".tmp")
    with src.open("rb") as fi, gzip.open(tmp, "wb") as fo:    # compresse ~10×
        while True:
            buf = fi.read(1 << 20)
            if not buf:
                break
            fo.write(buf)
    os.replace(tmp, dossier / nom)                            # atomique -> shard IMMUABLE (jamais reouvert)
    src.write_text("", encoding="utf-8")                      # la tape vivante repart a zero (= recent)
    # PRÉSERVATION (Flo 25/07) : on NE SUPPRIME PLUS les vieux shards — « il te faut des données, on
    # n'écrase pas les anciennes sessions ». Le set de travail reste borné à max_shards (fraîcheur/scan
    # rapide) ; au-delà, on DÉPLACE le plus vieux vers bbo_shards_archive/ (immuable, jamais effacé).
    shards = sorted(dossier.glob("bbo_tape_*.jsonl.gz"))
    archive = root / ARCHIVE_DIR
    for vieux in shards[:-max_shards]:                        # rétention bornée du SET DE TRAVAIL, sans perte
        try:
            archive.mkdir(parents=True, exist_ok=True)
            os.replace(vieux, archive / vieux.name)          # ARCHIVE (déplace), ne supprime jamais
        except OSError:
            pass
    return nom


# ─────────────────────────────── boucle WS PERSISTANTE (asyncio) ───────────────────────────────

async def _boucle(root: Path, coins: list[str]) -> None:  # pragma: no cover (I/O réseau)
    import asyncio

    import websockets

    from hl_observer.collection.tick_dataset import TickDatasetWriter, TickEnvelope
    from hl_observer.normalization.market_events import (
        CanonicalEventWriter,
        canonicalize_tick_record,
    )
    from hl_observer.realtime.feed_quality import (
        FeedEventKind,
        FeedMode,
        FeedQualityConfig,
        FeedQualityGate,
        stable_event_id,
    )
    from hl_observer.runtime.lead_lag_event_runtime import LeadLagEventPaperRuntime

    # Hyperliquid subscription names are case-sensitive (for example kPEPE),
    # while all internal joins intentionally use normalized upper-case keys.
    symboles_hl = {str(coin).upper(): str(coin) for coin in coins}
    coins = list(symboles_hl)
    mag = MagasinBBO()
    lead_lag_runtime = LeadLagEventPaperRuntime(root)
    sym = {c: symbole_binance(c) for c in coins if symbole_binance(c)}
    coins_set = set(coins)   # LIQUIDATION_LIVE_COVERAGE : le HL bbo est écrit pour TOUS les coins (memes/HL-only
    #                          inclus) ; la jambe Binance (sym) ne couvre que les coins réellement listés là-bas.
    from hl_observer.collection import collecte_fiable as CF
    cache = CF.CacheDedup()
    dataset = TickDatasetWriter(root / TICK_DATASET_DIR, flush_every=1)
    canonical_writer = CanonicalEventWriter(
        root / "runtime" / "data" / "canonical_events" / "canonical_market_events.jsonl"
    )
    raw_queue: deque[TickEnvelope] = deque()
    quality_config = FeedQualityConfig(
        max_age_ms=1_500.0,
        heartbeat_max_age_ms=3_000.0,
        max_gap_ms=GAP_MS,
        max_jitter_ms=1_000.0,
        max_latency_ms=1_500.0,
        max_spread_bps=1_000.0,
        max_mid_jump_fraction=0.15,
        min_coherent_events=2,
        min_score=75.0,
    )
    quality_gates: dict[tuple[str, str], FeedQualityGate] = {}
    for coin in coins:
        for channel, mode in (
            ("bbo", FeedMode.FULL_SNAPSHOT),
            ("l2Book", FeedMode.FULL_SNAPSHOT),
            ("trades", FeedMode.EVENT_STREAM),
        ):
            quality_gates[(channel, coin)] = FeedQualityGate(
                source_id="hyperliquid_mainnet_readonly",
                channel=channel,
                instrument=coin,
                mode=mode,
                config=quality_config,
            )
    local_sequences: dict[tuple[str, str], int] = {}
    hl_connection_serial = 0
    bin_bbo_connection_serial = 0
    bin_trade_connection_serial = 0
    #: TAPE BRUTE par message (horloge MONOTONE) — indispensable pour un lead-lag à 50/100 ms : un
    #: snapshot échantillonné à 250 ms ne peut PAS mesurer une réaction sous 250 ms. On enregistre
    #: chaque BBO reçu ; `lead_lag_shadow` reconstruit ensuite la réaction HL à n'importe quel horizon.
    tape: list[dict] = []
    stats = {"ecrits": 0, "rejets": 0, "reconnexions_hl": 0, "reconnexions_bin": 0, "trous": 0,
             "frames_bookticker": 0, "frames_trades": 0, "shards_scelles": 0,
             "frames_l2_hl": 0, "frames_trades_hl": 0, "raw_frames_received": 0,
             "raw_records_written": 0, "raw_queue_drops": 0, "parse_errors_hl": 0,
             "canonical_events_written": 0, "canonical_events_rejected": 0,
             "dernier_hl_ns": 0, "dernier_bin_ns": 0, "debut_mono_ns": time.monotonic_ns()}
    heartbeat_canonique = {"dernier_ecrit": 0, "dernier_ts_ns": 0}
    marqueur0 = MARQUEUR.read_text(encoding="utf-8").strip() if MARQUEUR.exists() else ""

    def next_sequence(channel: str, coin: str) -> int:
        key = (channel, coin)
        value = local_sequences.get(key, 0) + 1
        local_sequences[key] = value
        return value

    def queue_raw(envelope: TickEnvelope) -> None:
        if len(raw_queue) >= TICK_QUEUE_MAX:
            dropped = raw_queue.popleft()
            stats["raw_queue_drops"] += 1
            gate = quality_gates.get((dropped.channel, dropped.instrument))
            if gate is not None:
                gate.mark_gap(reason="LOCAL_RAW_QUEUE_OVERFLOW")
        raw_queue.append(envelope)

    def mark_hl_gap(*, received_ts_ms: int, connection_id: str, gap_ms: float) -> None:
        for gate in quality_gates.values():
            gate.mark_gap(reason="HYPERLIQUID_WS_TEMPORAL_GAP")
        queue_raw(
            TickEnvelope(
                source_id="hyperliquid_mainnet_readonly",
                channel="connection",
                instrument="*",
                event_kind=FeedEventKind.GAP,
                raw_payload={
                    "gap_ms": round(gap_ms, 3),
                    "reason": "HYPERLIQUID_WS_TEMPORAL_GAP",
                },
                received_ts_ms=received_ts_ms,
                local_monotonic_ns=time.monotonic_ns(),
                connection_id=connection_id,
                reconnect_count=stats["reconnexions_hl"],
                gap_count=stats["trous"],
                provenance={
                    "url": WS_HL,
                    "network": "mainnet",
                    "access": "read_only",
                    "transport": "websocket",
                },
            )
        )

    async def hl_legacy():
        while True:
            try:
                async with websockets.connect(WS_HL, ping_interval=20) as ws:
                    for c in coins:                          # HL bbo pour TOUS les coins (HL-only inclus)
                        await ws.send(json.dumps({"method": "subscribe",
                                                  "subscription": {"type": "bbo", "coin": c}}))
                    async for raw in ws:
                        r = time.monotonic_ns()
                        recv_wall_ms = int(time.time() * 1000)
                        if stats["dernier_hl_ns"] and (r - stats["dernier_hl_ns"]) / 1e6 > GAP_MS:
                            stats["trous"] += 1
                        stats["dernier_hl_ns"] = r
                        q = parser_bbo_hl(json.loads(raw))
                        if q and q["coin"] in coins_set:      # écrit le bid/ask HL des coins de liquidation
                            mag.maj_hl(
                                q,
                                recu_mono_ns=r,
                                recu_wall_ms=recv_wall_ms,
                                connection_id="hl-legacy",
                            )
                            tape.append({"venue": "HL", "coin": q["coin"], "recu_ns": r,
                                         "mid": (q["bid"] + q["ask"]) / 2, "bid": q["bid"], "ask": q["ask"],
                                         "bid_sz": q["bid_sz"], "ask_sz": q["ask_sz"],
                                         "ts_wall_ms": recv_wall_ms,
                                         "recv_wall_ts_ms": recv_wall_ms,
                                         "connection_id": "hl-legacy", "ts_ex": q["ts_ex"]})
            except Exception:  # noqa: BLE001 — reconnecte SEULEMENT sur panne
                stats["reconnexions_hl"] += 1
                await asyncio.sleep(1.0)

    def hl_provenance(channel: str) -> dict[str, Any]:
        return {
            "url": WS_HL,
            "network": "mainnet",
            "access": "read_only",
            "transport": "websocket",
            "channel_semantics": (
                "full_snapshot" if channel in {"bbo", "l2Book"} else "event_stream"
            ),
        }

    async def hl():
        nonlocal hl_connection_serial
        while True:
            try:
                async with websockets.connect(WS_HL, ping_interval=20) as ws:
                    hl_connection_serial += 1
                    connection_id = "hl-%d-%d" % (
                        int(time.time() * 1000),
                        hl_connection_serial,
                    )
                    if hl_connection_serial > 1:
                        reconnect_ts = int(time.time() * 1000)
                        for gate in quality_gates.values():
                            gate.mark_reconnect(
                                received_ts_ms=reconnect_ts,
                                connection_id=connection_id,
                            )
                        queue_raw(
                            TickEnvelope(
                                source_id="hyperliquid_mainnet_readonly",
                                channel="connection",
                                instrument="*",
                                event_kind=FeedEventKind.RECONNECT,
                                raw_payload={
                                    "connection_id": connection_id,
                                    "reconnect_count": stats["reconnexions_hl"],
                                },
                                received_ts_ms=reconnect_ts,
                                local_monotonic_ns=time.monotonic_ns(),
                                connection_id=connection_id,
                                reconnect_count=stats["reconnexions_hl"],
                                gap_count=stats["trous"],
                                provenance=hl_provenance("connection"),
                            )
                        )
                    for coin_name in coins:
                        for subscription_type in ("bbo", "l2Book", "trades"):
                            await ws.send(
                                json.dumps(
                                    {
                                        "method": "subscribe",
                                        "subscription": {
                                            "type": subscription_type,
                                            "coin": symboles_hl[coin_name],
                                        },
                                    }
                                )
                            )
                    async for raw in ws:
                        received_mono_ns = time.monotonic_ns()
                        received_ts_ms = int(time.time() * 1000)
                        gap_ms = (
                            (received_mono_ns - stats["dernier_hl_ns"]) / 1e6
                            if stats["dernier_hl_ns"]
                            else 0.0
                        )
                        if gap_ms > GAP_MS:
                            stats["trous"] += 1
                            mark_hl_gap(
                                received_ts_ms=received_ts_ms,
                                connection_id=connection_id,
                                gap_ms=gap_ms,
                            )
                        stats["dernier_hl_ns"] = received_mono_ns
                        stats["raw_frames_received"] += 1
                        try:
                            message = json.loads(raw)
                        except (TypeError, ValueError):
                            stats["parse_errors_hl"] += 1
                            queue_raw(
                                TickEnvelope(
                                    source_id="hyperliquid_mainnet_readonly",
                                    channel="invalid_json",
                                    instrument="*",
                                    event_kind=FeedEventKind.EVENT,
                                    raw_payload=raw,
                                    received_ts_ms=received_ts_ms,
                                    local_monotonic_ns=received_mono_ns,
                                    connection_id=connection_id,
                                    reconnect_count=stats["reconnexions_hl"],
                                    gap_count=stats["trous"],
                                    provenance=hl_provenance("invalid_json"),
                                )
                            )
                            continue

                        channel = str(message.get("channel") or "control")
                        data = message.get("data")
                        coin_name = ""
                        if isinstance(data, dict):
                            coin_name = str(data.get("coin") or "").upper()
                        elif isinstance(data, list) and data and isinstance(data[0], dict):
                            coin_name = str(data[0].get("coin") or "").upper()
                        exchange_ts_ms: int | None = None
                        if isinstance(data, dict) and data.get("time") is not None:
                            exchange_ts_ms = int(float(data["time"]))
                        elif isinstance(data, list):
                            exchange_times = [
                                int(float(item["time"]))
                                for item in data
                                if isinstance(item, dict) and item.get("time") is not None
                            ]
                            exchange_ts_ms = max(exchange_times) if exchange_times else None
                        sequence = next_sequence(channel, coin_name or "*")
                        envelope = TickEnvelope(
                            source_id="hyperliquid_mainnet_readonly",
                            channel=channel,
                            instrument=coin_name or "*",
                            event_kind=(
                                FeedEventKind.SNAPSHOT
                                if channel in {"bbo", "l2Book"}
                                else FeedEventKind.EVENT
                            ),
                            raw_payload=raw,
                            exchange_ts_ms=exchange_ts_ms,
                            received_ts_ms=received_ts_ms,
                            local_monotonic_ns=received_mono_ns,
                            connection_id=connection_id,
                            sequence=sequence,
                            reconnect_count=stats["reconnexions_hl"],
                            gap_count=stats["trous"],
                            provenance=hl_provenance(channel),
                        )
                        queue_raw(envelope)

                        quote = parser_bbo_hl(message)
                        if quote and quote["coin"] in coins_set:
                            gate = quality_gates[("bbo", quote["coin"])]
                            gate.mark_heartbeat(received_ts_ms=received_ts_ms)
                            quality = gate.ingest_book_snapshot(
                                bids=[{"px": quote["bid"], "sz": quote["bid_sz"]}],
                                asks=[{"px": quote["ask"], "sz": quote["ask_sz"]}],
                                exchange_ts_ms=int(quote["ts_ex"] or received_ts_ms),
                                received_ts_ms=received_ts_ms,
                                event_id=stable_event_id(message),
                                sequence=sequence,
                            )
                            envelope.parsed_summary = {
                                "best_bid": quote["bid"],
                                "best_ask": quote["ask"],
                                "bid_size": quote["bid_sz"],
                                "ask_size": quote["ask_sz"],
                                "feed_quality_score": quality.feed_quality_score,
                                "data_gate_ready": quality.ready,
                                "quality_reasons": list(quality.reasons),
                            }
                            mag.maj_hl(
                                quote,
                                recu_mono_ns=received_mono_ns,
                                recu_wall_ms=received_ts_ms,
                                connection_id=connection_id,
                                sequence=sequence,
                            )
                            tape.append(
                                {
                                    "venue": "HL",
                                    "coin": quote["coin"],
                                    "recu_ns": received_mono_ns,
                                    "mid": (quote["bid"] + quote["ask"]) / 2,
                                    "bid": quote["bid"],
                                    "ask": quote["ask"],
                                    "bid_sz": quote["bid_sz"],
                                    "ask_sz": quote["ask_sz"],
                                    "ts_wall_ms": received_ts_ms,
                                    "recv_wall_ts_ms": received_ts_ms,
                                    "connection_id": connection_id,
                                    "sequence": sequence,
                                    "event_id": stable_event_id(message),
                                    "ts_ex": quote["ts_ex"],
                                }
                            )
                            continue

                        book = parser_l2_hl(message)
                        if book and book["coin"] in coins_set:
                            stats["frames_l2_hl"] += 1
                            gate = quality_gates[("l2Book", book["coin"])]
                            gate.mark_heartbeat(received_ts_ms=received_ts_ms)
                            quality = gate.ingest_book_snapshot(
                                bids=book["bids"],
                                asks=book["asks"],
                                exchange_ts_ms=book["ts_ex"] or received_ts_ms,
                                received_ts_ms=received_ts_ms,
                                event_id=stable_event_id(message),
                                sequence=sequence,
                            )
                            try:
                                bid_depth_usd = sum(
                                    float(level["px"]) * float(level["sz"])
                                    for level in book["bids"]
                                )
                                ask_depth_usd = sum(
                                    float(level["px"]) * float(level["sz"])
                                    for level in book["asks"]
                                )
                            except (KeyError, TypeError, ValueError):
                                bid_depth_usd = ask_depth_usd = 0.0
                            envelope.parsed_summary = {
                                "bid_levels": len(book["bids"]),
                                "ask_levels": len(book["asks"]),
                                "bid_depth_usd": round(bid_depth_usd, 6),
                                "ask_depth_usd": round(ask_depth_usd, 6),
                                "feed_quality_score": quality.feed_quality_score,
                                "data_gate_ready": quality.ready,
                                "quality_reasons": list(quality.reasons),
                            }
                            continue

                        trades = parser_trades_hl(message)
                        if trades:
                            stats["frames_trades_hl"] += 1
                            quality_by_coin: dict[str, dict[str, Any]] = {}
                            for trade in trades:
                                trade_coin = str(trade.get("coin") or coin_name).upper()
                                gate = quality_gates.get(("trades", trade_coin))
                                if gate is None:
                                    continue
                                gate.mark_heartbeat(received_ts_ms=received_ts_ms)
                                trade_ts = int(float(trade.get("time") or received_ts_ms))
                                trade_id = "%s|%s|%s" % (
                                    trade_ts,
                                    trade_coin,
                                    trade.get("tid", trade.get("hash", "")),
                                )
                                quality = gate.ingest_event(
                                    payload=trade,
                                    exchange_ts_ms=trade_ts,
                                    received_ts_ms=received_ts_ms,
                                    event_id=trade_id,
                                )
                                quality_by_coin[trade_coin] = {
                                    "feed_quality_score": quality.feed_quality_score,
                                    "data_gate_ready": quality.ready,
                                    "quality_reasons": list(quality.reasons),
                                }
                            envelope.parsed_summary = {
                                "trade_count": len(trades),
                                "quality_by_coin": quality_by_coin,
                            }
            except Exception:  # noqa: BLE001 - reconnect only after a real failure
                stats["reconnexions_hl"] += 1
                await asyncio.sleep(1.0)

    inv = {s.upper(): c for c, s in sym.items()}

    async def binance_bt():
        nonlocal bin_bbo_connection_serial
        # bookTicker (entrée exécutable) sur SA connexion. Séparée de l'aggTrade : la très haute
        # fréquence du bookTicker ne peut plus AFFAMER l'aggTrade (cause probable des 0 trades captés).
        streams = "/".join("%s@bookTicker" % s.lower() for s in sym.values())
        while True:
            try:
                async with websockets.connect("%s?streams=%s" % (WS_BINANCE, streams), ping_interval=20) as ws:
                    bin_bbo_connection_serial += 1
                    connection_id = "bin-bbo-%d-%d" % (
                        int(time.time() * 1000),
                        bin_bbo_connection_serial,
                    )
                    async for raw in ws:
                        r = time.monotonic_ns()
                        recv_wall_ms = int(time.time() * 1000)
                        if stats["dernier_bin_ns"] and (r - stats["dernier_bin_ns"]) / 1e6 > GAP_MS:
                            stats["trous"] += 1
                        stats["dernier_bin_ns"] = r
                        q = parser_bookticker_binance(json.loads(raw))
                        if q and q["symbol"] in inv:
                            stats["frames_bookticker"] += 1
                            coin_name = inv[q["symbol"]]
                            sequence = next_sequence("binance_bbo", coin_name)
                            mag.maj_binance(
                                q,
                                coin_name,
                                recu_mono_ns=r,
                                recu_wall_ms=recv_wall_ms,
                                connection_id=connection_id,
                                sequence=sequence,
                            )
                            tape.append({"venue": "BIN", "coin": inv[q["symbol"]], "recu_ns": r,
                                         "mid": (q["bid"] + q["ask"]) / 2, "bid": q["bid"], "ask": q["ask"],
                                         "ts_wall_ms": recv_wall_ms,
                                         "recv_wall_ts_ms": recv_wall_ms,
                                         "connection_id": connection_id,
                                         "sequence": sequence,
                                         "event_id": "bin-bbo:%s:%s" % (
                                             q["symbol"],
                                             q.get("update_id") or recv_wall_ms,
                                         ),
                                         "ts_ex": q["ts_ex"],
                                         "update_id": q.get("update_id")})
            except Exception:  # noqa: BLE001 — reconnecte SEULEMENT sur panne
                stats["reconnexions_bin"] += 1
                await asyncio.sleep(1.0)

    async def binance_ag():
        nonlocal bin_trade_connection_serial
        # TRADES = le CHOC exécutable (jamais le mid, qui reste un simple CONTRÔLE dans lead_lag).
        # `@trade` et NON `@aggTrade` : prouvé au navigateur que fstream ...@aggTrade ne pousse rien ici.
        streams = "/".join("%s@trade" % s.lower() for s in sym.values())
        while True:
            try:
                async with websockets.connect("%s?streams=%s" % (WS_BINANCE, streams), ping_interval=20) as ws:
                    bin_trade_connection_serial += 1
                    connection_id = "bin-trade-%d-%d" % (
                        int(time.time() * 1000),
                        bin_trade_connection_serial,
                    )
                    async for raw in ws:
                        r = time.monotonic_ns()
                        recv_wall_ms = int(time.time() * 1000)
                        t = parser_aggtrade_binance(json.loads(raw))
                        if t and t["symbol"] in inv:
                            stats["frames_trades"] += 1
                            coin_name = inv[t["symbol"]]
                            sequence = next_sequence("binance_trade", coin_name)
                            trade_event = {
                                "venue": "BIN_TRADE",
                                "coin": coin_name,
                                "recu_ns": r,
                                "px": t["px"],
                                "sz": t["sz"],
                                "side": t["side"],
                                "ts_wall_ms": recv_wall_ms,
                                "recv_wall_ts_ms": recv_wall_ms,
                                "connection_id": connection_id,
                                "sequence": sequence,
                                "event_id": "bin-trade:%s:%s:%s" % (
                                    t["symbol"],
                                    t.get("ts_ex") or recv_wall_ms,
                                    sequence,
                                ),
                                "ts_ex": t["ts_ex"],
                            }
                            tape.append(trade_event)
                            dispatch_lead_lag_trade(
                                lead_lag_runtime,
                                trade_event,
                                mag.hl.get(coin_name),
                                now_ms=recv_wall_ms,
                            )
            except Exception:  # noqa: BLE001
                stats["reconnexions_bin"] += 1
                await asyncio.sleep(1.0)

    async def ecrire_et_superviser():
        while True:
            await asyncio.sleep(0.25)
            now_ns = time.monotonic_ns()
            snaps = [s for c in sym if (s := mag.snapshot(c, now_mono_ns=now_ns, ts_wall_ms=time.time() * 1000))]
            # une paire connue mais rejetée (périmée/désynchro) = donnée rejetée -> on la compte
            stats["rejets"] += sum(1 for c in sym if (mag.hl.get(c) and mag.bin.get(c)) and c not in {s["coin"] for s in snaps})
            if snaps:
                propres = CF.collecter_proprement(snaps, source="bbo_hl_bin",
                                                  champs_cle=("coin", "ts_ms"), cache=cache)
                stats["ecrits"] += CF.append_jsonl(root / SORTIE, propres)
            if tape:                                           # flush de la TAPE brute (lead-lag fin)
                CF.append_jsonl(root / TAPE, list(tape))
                tape.clear()
                if sceller_shard(root):                        # scelle un shard gz immuable si la tape est pleine
                    stats["shards_scelles"] += 1
            if raw_queue:
                batch = [raw_queue.popleft() for _ in range(min(5_000, len(raw_queue)))]
                durable_records = await asyncio.to_thread(
                    dataset.append_batch_records,
                    batch,
                )
                stats["raw_records_written"] += len(durable_records)
                canonical_results = [
                    canonicalize_tick_record(record) for record in durable_records
                ]
                canonical_events = [
                    result.event for result in canonical_results if result.event is not None
                ]
                stats["canonical_events_rejected"] += sum(
                    1 for result in canonical_results if result.event is None
                )
                stats["canonical_events_written"] += await asyncio.to_thread(
                    canonical_writer.append,
                    canonical_events,
                )
            now_wall_ms = int(time.time() * 1000)
            feed_snapshots = {
                "hyperliquid:%s:%s" % (channel, coin): gate.snapshot(
                    now_ms=now_wall_ms
                ).as_dict()
                for (channel, coin), gate in quality_gates.items()
            }
            quality_payload = {
                "schema_version": "hypersmart.feed_quality.v1",
                "generated_at_ms": now_wall_ms,
                "feeds": feed_snapshots,
                "ready_feeds": sum(
                    1 for snapshot in feed_snapshots.values() if snapshot["ready"]
                ),
                "total_feeds": len(feed_snapshots),
                "raw_queue_depth": len(raw_queue),
                "raw_queue_drops": stats["raw_queue_drops"],
                "dataset": dataset.stats(),
                "canonical_events": {
                    "path": str(canonical_writer.path),
                    "written": canonical_writer.written,
                    "duplicates": canonical_writer.duplicates,
                    "rejected_by_quality_gate": stats["canonical_events_rejected"],
                },
                "read_only": True,
                "real_execution": False,
            }
            CF.ecrire_atomique(
                root / FEED_QUALITY,
                json.dumps(quality_payload, ensure_ascii=False),
            )
            duree_s = (now_ns - stats["debut_mono_ns"]) / 1e9
            hb = {"ts": time.time(), "duree_continue_s": round(duree_s, 1), **stats,
                  "taux_rejet": round(stats["rejets"] / max(1, stats["ecrits"] + stats["rejets"]), 4),
                  "raw_queue_depth": len(raw_queue),
                  "feed_quality_ready": quality_payload["ready_feeds"],
                  "feed_quality_total": quality_payload["total_feeds"],
                  "tick_dataset": dataset.stats()}
            CF.ecrire_atomique(root / HEARTBEAT, json.dumps(hb, ensure_ascii=False))
            if now_ns - heartbeat_canonique["dernier_ts_ns"] >= 2_000_000_000:
                total_ecrit = int(stats["canonical_events_written"])
                delta_ecrit = max(0, total_ecrit - int(heartbeat_canonique["dernier_ecrit"]))
                exchange_timestamps = [
                    int(snapshot["last_exchange_ts_ms"])
                    for snapshot in feed_snapshots.values()
                    if snapshot.get("last_exchange_ts_ms") is not None
                ]
                HB.battre(
                    root,
                    "bbo-collector",
                    pid=os.getppid(),
                    n_ecrites=delta_ecrit,
                    dernier_exchange_ts=max(exchange_timestamps) if exchange_timestamps else None,
                    souscription_ack=bool(stats["raw_frames_received"]),
                    note="%d canonical market events" % total_ecrit,
                    metriques={
                        "gaps_critiques": int(stats["raw_queue_drops"]),
                        "reconnects": int(stats["reconnexions_hl"]),
                        "stale": not bool(stats["raw_frames_received"]),
                    },
                )
                heartbeat_canonique["dernier_ecrit"] = total_ecrit
                heartbeat_canonique["dernier_ts_ns"] = now_ns
            marq = MARQUEUR.read_text(encoding="utf-8").strip() if MARQUEUR.exists() else marqueur0
            if marq != marqueur0:                              # anti-orphelin : la session a changé -> stop
                return

    # 🔴 SORTIE PROPRE (bug corrige le 23/07). Avant : `gather(hl, binance_bt, binance_ag, superviseur)`.
    # Quand le superviseur RETOURNE (marqueur de session change), les 3 coroutines WS tournaient a
    # l'INFINI via gather -> le process ne mourait JAMAIS -> a la relance suivante, un ZOMBIE gardait
    # les WS ouverts et le heartbeat/tape se figeait (« fichier utilise par un autre processus »).
    # Desormais on n'attend QUE le superviseur, puis on ANNULE les WS -> le process sort et libere tout.
    taches = [asyncio.create_task(c()) for c in (hl, binance_bt, binance_ag)]
    try:
        await ecrire_et_superviser()
    finally:
        for t in taches:
            t.cancel()
        await asyncio.gather(*taches, return_exceptions=True)
        while raw_queue:
            batch = [raw_queue.popleft() for _ in range(min(5_000, len(raw_queue)))]
            durable_records = await asyncio.to_thread(
                dataset.append_batch_records,
                batch,
            )
            stats["raw_records_written"] += len(durable_records)
            canonical_results = [
                canonicalize_tick_record(record) for record in durable_records
            ]
            canonical_events = [
                result.event for result in canonical_results if result.event is not None
            ]
            stats["canonical_events_rejected"] += sum(
                1 for result in canonical_results if result.event is None
            )
            stats["canonical_events_written"] += await asyncio.to_thread(
                canonical_writer.append,
                canonical_events,
            )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import asyncio
    p = argparse.ArgumentParser(description="Collecteur BBO rapide HL/Binance (PERSISTANT, lecture seule).")
    p.add_argument("--root", default=".")
    p.add_argument("--coins", default="AUTO")   # AUTO = majors + coins fréquents des liquidations (journal)
    a = p.parse_args(argv)
    if a.coins.strip().upper() == "AUTO":
        requested_coins = coins_couverture(a.root)
    else:
        requested_coins = [c.strip() for c in a.coins.split(",") if c.strip()]
    try:
        universe = charger_symboles_hyperliquid()
        coins, rejected = resoudre_symboles_hyperliquid(requested_coins, universe)
    except Exception as exc:  # noqa: BLE001 - required live source must fail visibly
        print("[bbo] /info meta indisponible ou invalide: %r" % exc, flush=True)
        return 2
    if rejected:
        print(
            "[bbo] marches ignorees (absentes de /info meta): %s" % ", ".join(rejected),
            flush=True,
        )
    if not coins:
        print("[bbo] aucune marche Hyperliquid valide a surveiller.", flush=True)
        return 2
    try:                                                     # 🔴 sans `websockets`, RIEN ne se collecte
        import websockets  # noqa: F401
    except ImportError:
        print("[bbo] MODULE `websockets` MANQUANT -> lance:  pip install websockets  (collecteur inactif "
              "tant qu'il n'est pas installe).", flush=True)
        return 0
    print("[bbo] demarrage PERSISTANT : %d coins, WS HL bbo+l2Book+trades + Binance bookTicker/trades..."
          % len(coins), flush=True)
    try:
        asyncio.run(_boucle(Path(a.root), coins))            # PERSISTANT : sort seulement sur fin de session
    except KeyboardInterrupt:
        return 0
    except Exception as exc:                                 # noqa: BLE001 — une panne DOIT etre visible
        import traceback
        print("[bbo] ARRET sur exception: %r" % exc, flush=True)
        traceback.print_exc()
        return 1
    print("[bbo] boucle terminee (fin de session).", flush=True)
    return 0


def resume(root: str | Path = ".") -> dict[str, Any]:
    """État du BBO pour le rapport : durée continue, événements propres, taux de rejet, reconnexions."""
    p = Path(root) / HEARTBEAT
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"duree_continue_s": 0, "ecrits": 0, "taux_rejet": None, "verdict": "PAS_ENCORE_LANCE"}


__all__ = ["symbole_binance", "extraire_symboles_hyperliquid", "charger_symboles_hyperliquid",
           "resoudre_symboles_hyperliquid", "parser_bbo_hl", "parser_l2_hl", "parser_trades_hl",
           "parser_bookticker_binance", "parser_aggtrade_binance", "dispatch_lead_lag_trade",
           "MagasinBBO", "mesurer_lead_lag", "sceller_shard", "resume",
           "AGE_MAX_MS", "FENETRE_SYNCHRO_MS", "GAP_MS", "SHARD_OCTETS", "MAX_SHARDS",
           "SORTIE", "FEED_QUALITY", "TICK_DATASET_DIR", "TICK_QUEUE_MAX"]


if __name__ == "__main__":                                 # 🔴 MANQUAIT : sans ce garde, le script
    raise SystemExit(main())                               # definissait tout et sortait sans lancer main()
