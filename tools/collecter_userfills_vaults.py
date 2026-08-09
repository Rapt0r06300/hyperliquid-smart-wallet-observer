"""MOTEUR WS userFills INLINE (rectif Flo 23/07) — ouvre dans le MÊME flux que le fill, sans bloquer.

Boucle WS = réception PURE (met chaque message dans une FILE BORNÉE) ; un WORKER consomme la file et
appelle `cohortes.traiter_fill` pour les DEUX cohortes (ALPHA + PROBE) : admission → L2<1s → open inline,
avec latence fill→copie. Snapshot INITIAL ignoré ; après RECONNEXION, on rejoue seulement les fills
INCONNUS plus récents que le CURSEUR PERSISTANT par vault (aucun événement perdu pendant la coupure).
REDUCE/CLOSE/FLIP du leader suivis proportionnellement. Exits stop/TP re-vérifiés à chaque événement
(fill) + toutes ~2 s. Lecture seule ; 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.collection import userfills_live as UL  # noqa: E402
from hl_observer.collection import verrou_instance as VI  # noqa: E402
from hl_observer.experimental import cohortes as CO  # noqa: E402
from hl_observer.market_data.live_l2_service import (  # noqa: E402
    LiveL2Snapshot,
    snapshot_from_mapping,
    write_dynamic_snapshot,
)
from hl_observer.experimental import liquidation_sentinels as LS  # noqa: E402  (LIQUIDATOR_SENTINELS_V2)
import sonde_confirmation_vaults as SD  # noqa: E402  (helpers de réconciliation par CLÉ COMPOSITE, partagés)
import heartbeat_collecteur as HB  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
FILLS_LIVE = Path("runtime") / "data" / "vault_fills_live.jsonl"
JOURNAL = Path("runtime") / "data" / "fills_journal.jsonl"       # CHAQUE fill live non-snapshot + gate + latence
LIQ_CONFIRMEES = Path("runtime") / "data" / "liquidations_confirmees.jsonl"  # 25/07 : fill.liquidation non-null = REAL_LIQUIDATION
# 25/07 — userEvents/WsLiquidation NON ajouté À DESSEIN : le champ `liquidation` {liquidatedUser, markPx,
# method} est DÉJÀ porté par les messages userFills qu'on reçoit (une liquidation du user suivi apparaît
# comme un fill portant ce champ). Ajouter un abonnement userEvents doublerait les abonnements par socket
# et risquerait le plafond HL (~5/connexion) -> MOINS de données, pas plus. On préserve donc le champ
# userFills (ci-dessus) plutôt qu'ouvrir un 2e canal redondant. Réactiver seulement si HL cesse de porter
# `liquidation` sur userFills (mesuré, pas supposé).
CURSEURS = Path("runtime") / "data" / "userfills_curseurs.json"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
FILE_MAX = 2000                  # file bornée : si saturée, on drop (on ne bloque JAMAIS la reception WS)
NOM_VERROU = "userfills_live"
RUN_ID = ""
RUN_TOKEN = ""                    # provenance HORS PAYLOAD (en mémoire) — arme le trade + l'écriture runtime
_MUTEX = None                     # handle du mutex Windows (à garder vivant)
TRIGGER_VERSION = "v1"            # version du déclencheur (estampillée OPEN+CLOSE ; filtre les stats config courante)
GIT_COMMIT = ""                   # commit git chargé (audit SÉPARÉ, JAMAIS dans config_hash)
TRANSPORT_VERSION = "userfills_2sock_v1"   # transport WS (HORS config_hash) : 2 sockets de 5 vaults + L2 ; compare latence
TAILLE_SHARD = 5                           # HL cape ~5 abonnements userFills/connexion -> shards déterministes de 5
_WS_PAR_SOCKET: dict = {}                   # socket_id -> connexion WS vivante (pour reconnecter UN shard depuis le garde)
_WS_KEYS: dict = {}                          # vault -> deque(maxlen) des CLÉS COMPOSITES de fills REÇUES par le WS
WS_KEYS_CAP = 6000                          # borne par vault (couvre très largement la fenêtre de réconciliation)
_DEMARRAGE_MS = 0.0                          # instant de démarrage : _WS_KEYS ne peut contenir QUE des fills reçus après
_HEARTBEAT_WS = {"messages": 0, "fills": 0, "acks": 0, "reconnects": 0,
                 "drops": 0, "dernier_exchange_ts": None}


def _activite_par_vault(root: Path, *, fenetre_h: float = 2.0, max_lignes: int = 4000) -> dict:
    """Fills récents par vault (activité LIVE) depuis vault_fills_live.jsonl — un vault qui trade offre plus
    d'occasions de mesure. Lecture bornée (les dernières lignes)."""
    seuil = time.time() * 1000 - fenetre_h * 3_600_000.0
    cnt: dict[str, int] = {}
    try:
        lignes = (root / FILLS_LIVE).read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]
    except OSError:
        return cnt
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if float(d.get("ts_ms") or 0) >= seuil and d.get("vault"):
            cnt[d["vault"]] = cnt.get(d["vault"], 0) + 1
    return cnt


def _shadow_par_vault(root: Path) -> dict:
    """Qualité shadow par vault (moyenne des shadow_net_bps de ses paires, part positive) depuis paires_shadow.json."""
    try:
        d = json.loads((root / "runtime" / "data" / "paires_shadow.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    agg: dict[str, list] = {}
    for p in (d.get("paires") or {}).values():
        if p.get("vault") and p.get("shadow_net_bps") is not None:
            agg.setdefault(p["vault"], []).append(float(p["shadow_net_bps"]))
    return {v: sum(x for x in xs if x > 0) / len(xs) for v, xs in agg.items() if xs}


MAX_SLOTS = 10                          # plafond dur des places userFills (inchangé)
SENTINELLES_K = 3                       # ≤3 slots RÉSERVÉS aux LIQUIDATOR_SENTINELS (top liquidateurs)


def charger_sentinelles(root: Path, *, k: int = SENTINELLES_K) -> list[str]:
    """LIQUIDATOR_SENTINELS = les vaults les plus souvent LIQUIDATEURS dans le journal confirmé
    (`liquidations_confirmees.jsonl`). Les épingler garantit qu'on capte leurs fills de liquidation forward.
    Deny-by-default : sans journal, aucune sentinelle. Pur (réutilise le cœur testé LS)."""
    try:
        recs = [json.loads(l) for l in (root / LIQ_CONFIRMEES).read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []
    return LS.selectionner_sentinelles(recs, k=k)["sentinelles"]


def vaults_et_roles(root: Path, *, n_candidats: int = 8) -> list[tuple[str, str, str]]:
    """(vault, role, raison) sur ≤10 places WS : 2 CORE (retenus stricts, TRADENT ALPHA+PROBE) + ≤3
    LIQUIDATOR_SENTINELS ÉPINGLÉS (top liquidateurs confirmés — pour capter les liquidations forward) +
    le reste en CANDIDATS OBSERVÉS par ROTATION = activité live + qualité shadow + copyabilité. Total borné
    à MAX_SLOTS : les sentinelles NE dépassent JAMAIS la limite et NE volent PAS les slots CORE. PROBE ne
    TRADE un candidat que s'il passe la sécurité mini. Deny-by-default : sans score, aucun abonnement."""
    try:
        d = json.loads((root / SCORES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    classement = d.get("classement") or []
    core = [c["vault"] for c in classement if c.get("retenu")][:2]
    out = [(v, "CORE", "retenu strict (score) → trade ALPHA+PROBE") for v in core]
    pris = set(core)
    # Sentinelles épinglées (dédupliquées vs CORE), sans jamais dépasser MAX_SLOTS
    for v in charger_sentinelles(root):
        if v in pris or len(out) >= MAX_SLOTS:
            continue
        out.append((v, "LIQUIDATOR_SENTINEL", "top liquidateur confirmé → épinglé pour capter les liquidations"))
        pris.add(v)
    act, sha = _activite_par_vault(root), _shadow_par_vault(root)
    a_max = max(act.values()) if act else 1
    s_max = max(sha.values()) if sha else 1
    def _rotation(c: dict) -> float:                                  # score de rotation des candidats
        v, f = c["vault"], c.get("facteurs", {})
        a = act.get(v, 0) / a_max if a_max else 0.0                   # activité live
        s = max(0.0, sha.get(v, 0.0)) / s_max if s_max else 0.0       # qualité shadow (positive)
        cp = float(f.get("copyabilite") or 0.0)                       # copyabilité
        return 0.45 * a + 0.30 * s + 0.25 * cp
    reste = max(0, min(n_candidats, MAX_SLOTS - len(out)))            # les autres slots pour le runtime existant
    cands = sorted((c for c in classement if c["vault"] not in pris), key=_rotation, reverse=True)
    for c in cands[:reste]:
        f = c.get("facteurs", {})
        sur = (float(f.get("anciennete_j") or 0) >= 45 and float(f.get("drawdown_pct") or 100) <= 45
               and float(f.get("copyabilite") or 0) >= 0.5)
        role = "CANDIDAT_TRADABLE" if sur else "CANDIDAT_OBSERVE"
        raison = "observé en WS ; PROBE l'ouvre" if sur else "observé en WS seulement (sécurité mini non passée)"
        out.append((c["vault"], role, raison))
    return out


def vaults_suivis(root: Path) -> list[str]:
    return [v for v, _r, _why in vaults_et_roles(root)]


def _charger_curseurs(root: Path) -> dict:
    try:
        return json.loads((root / CURSEURS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sauver_curseurs(root: Path, cur: dict) -> None:
    (root / CURSEURS).parent.mkdir(parents=True, exist_ok=True)
    tmp = (root / CURSEURS).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    tmp.replace(root / CURSEURS)


def fills_a_traiter(vault: str, fills: list[dict], curseurs: dict) -> list[dict]:
    """Filtre anti-perte : snapshot INITIAL (curseur absent) → ignoré + curseur posé à maintenant ;
    sinon (live OU snapshot de reconnexion) → seulement les fills STRICTEMENT plus récents que le curseur.
    Met le curseur à jour. Rend la liste à traiter."""
    if not fills:
        return []
    est_snap = bool(fills[0].get("isSnapshot"))
    cur = float(curseurs.get(vault, 0) or 0)
    if est_snap and cur == 0:                                     # première connexion : on ne trade pas l'historique
        curseurs[vault] = max(f["ts_ms"] for f in fills)
        return []
    a_traiter = [f for f in fills if float(f["ts_ms"]) > cur]     # catch-up : uniquement les inconnus récents
    if a_traiter:
        curseurs[vault] = max(float(f["ts_ms"]) for f in a_traiter)
    return a_traiter


ETATS = {}


def _journal(root: Path, fill: dict, cohorte: str, decision: dict | None, recu_ms: float) -> None:
    """Journalise CHAQUE fill live non-snapshot (même refusé) : gate/motif, latence fill→décision, source."""
    d = decision or {}
    etat = "OUVERTURE" if d.get("ouverture") else ("FERMETURE" if d.get("fermeture") else (
        "REDUCTION" if d.get("reduction") else ("REFUS:" + str(d.get("refus")) if d.get("refus") else "AUCUN")))
    ligne = {"recu_ms": int(recu_ms), "cohorte": cohorte, "coin": fill.get("coin"), "vault": str(fill.get("vault") or "")[:12],
             "dir": fill.get("dir"), "sz": fill.get("sz"), "px": fill.get("px"),
             "source": fill.get("source"), "fill_ts_ms": fill.get("ts_ms"),
             "latence_fill_decision_ms": round(recu_ms - float(fill.get("ts_ms") or recu_ms)),
             "decision": etat, "run_id": RUN_ID}
    with (root / JOURNAL).open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")


def _journal_liquidations(root: Path, recs: list, *, socket_id: str = "") -> None:
    """Journalise les liquidations CONFIRMÉES (fill.liquidation non-null) dans LIQ_CONFIRMEES — NO-OP si la
    liste est vide (cas quasi systématique) : zéro coût sur les fills normaux. Best-effort, ne lève JAMAIS
    (le hot-path WS ne doit pas casser pour un journal). Purement observationnel : aucune décision de trade."""
    if not recs:
        return
    try:
        with (root / LIQ_CONFIRMEES).open("a", encoding="utf-8") as f:
            for r in recs:
                # CAUSALITÉ (25/07) : recv_wall_ms = horloge WALL commune inter-processus (join avec la BBO) ;
                # recv_mono_ns = monotone INTRA-processus (latence/provenance, PAS comparable à un autre process).
                # source LIVE_WS -> éligible à un fade causal ; le backfill REST marque REST_BACKFILL (OOS only).
                wall_ms = int(time.time() * 1000)
                f.write(json.dumps({**r, "recu_ms": wall_ms, "recv_wall_ms": wall_ms,
                                    "recv_mono_ns": time.monotonic_ns(), "source": "LIVE_WS",
                                    "socket": socket_id, "run_id": RUN_ID}, ensure_ascii=False) + "\n")
        for r in recs:
            print("[userfills] LIQUIDATION CONFIRMEE %s sz=%s px=%s method=%s user=%s" % (
                r.get("coin"), r.get("sz"), r.get("px"), r.get("method"),
                str(r.get("liquidatedUser") or "")[:10]), flush=True)
    except OSError:
        pass


# ── L2 ON-DEMAND (rectif Flo 23/07) : fetch L2<1s du coin EXACT du fill, pour que RAW_PROBE/ALPHA/PROBE
#    puissent juger un coin CANDIDAT (AERO/LDO/WLD…) hors table BBO/carnet. PUBLIC lecture seule (l2Book).
#    Cache TTL 0.8 s partagé entre cohortes -> une seule requête par coin par vague de fills (poli, borné).
#    Le réseau ne fait JAMAIS crasher le worker (tout est capté). 0 ordre, 0 clé, 0 signature.
_L2_CACHE: dict[str, tuple[float, dict | None]] = {}
_L2_TTL_S = 0.8
_L2_POST = None
_L2_PARSE = None


def _depth_executable(rep: dict, mid: float, *, n: int = 5) -> float:
    """Profondeur EXÉCUTABLE en USD sur les `n` premiers niveaux, côté le plus mince. Plus HONNÊTE que le
    seul top tick (qui sous-estime massivement un carnet profond : un alt liquide a peu au 1er tick mais
    beaucoup juste en dessous). `rep` = réponse l2Book HL ({'levels': [bids, asks]}, niveaux {px,sz})."""
    try:
        bids, asks = rep["levels"][0], rep["levels"][1]
    except (KeyError, IndexError, TypeError):
        return 0.0
    def somme(cote: list) -> float:
        return sum(float(x.get("sz") or 0.0) for x in (cote or [])[:n]) * mid
    return min(somme(bids), somme(asks))


def _full_levels(rep: dict) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Return every valid observed level; never extend the visible book."""

    try:
        raw_bids, raw_asks = rep["levels"][0], rep["levels"][1]
        bids = [(float(row["px"]), float(row["sz"])) for row in raw_bids]
        asks = [(float(row["px"]), float(row["sz"])) for row in raw_asks]
    except (KeyError, IndexError, TypeError, ValueError):
        return [], []
    return (
        [(px, sz) for px, sz in bids if px > 0 and sz > 0],
        [(px, sz) for px, sz in asks if px > 0 and sz > 0],
    )


def _lecteur_l2_ondemand(coin: str) -> dict | None:
    """L2 HL FRAIS (<1 s) pour `coin`, à la demande (POST public l2Book). Rend
    {hl_bid, hl_ask, depth_usd, age_ms} ou None. Cache court pour ne pas marteler l'API."""
    global _L2_POST, _L2_PARSE
    if not coin:
        return None
    now = time.monotonic()
    hit = _L2_CACHE.get(coin)
    if hit is not None and (now - hit[0]) < _L2_TTL_S:
        return hit[1]
    if _L2_POST is None:
        try:
            sys.path.insert(0, str(RACINE / "tools"))
            from collecter_carnet import _post_hl as _p, parser_book_hl as _q
            _L2_POST, _L2_PARSE = _p, _q
        except Exception:  # noqa: BLE001
            _L2_CACHE[coin] = (now, None)
            return None
    rep = None
    try:
        rep = _L2_POST(coin, timeout_s=2.0)
        p = _L2_PARSE(rep)
    except Exception:  # noqa: BLE001 — le réseau ne doit jamais faire crasher le tick paper
        p = None
    if not p:
        _L2_CACHE[coin] = (now, None)
        return None
    bid, ask, bsz, asz = p
    mid = 0.5 * (bid + ask)
    depth = _depth_executable(rep, mid) or (min(bsz, asz) * mid)   # top-5 niveaux (secours : top tick)
    bids, asks = _full_levels(rep)
    received_ts_ms = int(time.time() * 1_000)
    d = {
        "hl_bid": bid,
        "hl_ask": ask,
        "depth_usd": round(depth, 2),
        "age_ms": 0.0,
        "received_ts_ms": received_ts_ms,
        "exchange_ts_ms": rep.get("time") if isinstance(rep, dict) else None,
        "source": "hyperliquid:/info:l2Book:on_demand",
        "data_origin": "REAL",
        "bids": bids,
        "asks": asks,
    }
    _L2_CACHE[coin] = (now, d)
    return d


# ── L2 DYNAMIQUE WS (rectif Flo 24/07) : pour chaque coin à position RAW ouverte, on s'abonne RÉELLEMENT au
#    l2Book HL (WS) — demande → subscriptionResponse (ACK) → premier book → désabonnement à la clôture — et
#    on alimente un book FRAIS pour le marquage. Écrire dans coins_bouges ne suffisait pas. Lecture seule.
L2_LIFECYCLE = Path("runtime") / "data" / "raw_l2_lifecycle.jsonl"
RAW_L2_LIVE = Path("runtime") / "data" / "raw_l2_live.json"
_ROOT_LIVE: Path = RACINE                            # racine réelle (posée dans _boucle) pour le book WS


def _log_l2(root: Path, evt: str, coin: str, extra: dict | None = None) -> None:
    try:
        with (root / L2_LIFECYCLE).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts_ms": int(time.time() * 1000), "evt": evt, "coin": coin,
                                "run_id": RUN_ID, **(extra or {})}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _coins_actifs(root: Path) -> set:
    """Cibles d'abonnement L2 WS = coins à POSITION RAW ouverte UNION coins en AGRÉGATION (prewarm, TTL 12 s)
    -> l'abonnement L2 démarre EN PARALLÈLE dès le début de l'agrégation (course avec le REST)."""
    coins: set = set()
    try:
        coins |= set(json.loads((root / CO.COINS_ACTIFS_RELPATH).read_text(encoding="utf-8")).get("coins") or [])
    except (OSError, ValueError):
        pass
    try:
        pw = json.loads((root / CO.COINS_PREWARM_RELPATH).read_text(encoding="utf-8")).get("coins") or {}
        maintenant = time.time() * 1000
        coins |= {c for c, t in pw.items() if maintenant - float(t) <= 12_000}
    except (OSError, ValueError):
        pass
    return coins


def _parse_l2_ws(d: dict) -> tuple | None:
    """(bid, ask, depth_usd top-5) depuis un message l2Book WS ({'levels':[bids,asks]}). None si illisible."""
    try:
        bids, asks = d["levels"][0], d["levels"][1]
        bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0:
        return None
    return bid, ask, round(_depth_executable(d, 0.5 * (bid + ask)), 2)


def _ecrire_book_live(
    root: Path,
    coin: str,
    bid: float,
    ask: float,
    depth: float,
    *,
    bids: list[tuple[float, float]] | None = None,
    asks: list[tuple[float, float]] | None = None,
    received_ts_ms: int | None = None,
    exchange_ts_ms: int | None = None,
) -> None:
    received = int(received_ts_ms or time.time() * 1_000)
    try:
        snapshot = LiveL2Snapshot(
            coin=str(coin).upper(),
            best_bid=float(bid),
            best_ask=float(ask),
            depth_usd=float(depth),
            source="hyperliquid:ws:l2Book:dynamic",
            received_ts_ms=received,
            exchange_ts_ms=exchange_ts_ms,
            bids=tuple(bids or ()),
            asks=tuple(asks or ()),
        )
        write_dynamic_snapshot(root, snapshot, relpath=RAW_L2_LIVE)
    except (OSError, TypeError, ValueError):
        pass


def _book_ws_frais(coin: str, *, age_max_s: float = 1.5) -> dict | None:
    """Book WS FRAIS (<age_max_s) alimenté par l'abonnement dynamique — pour le MARQUAGE (pas le REST)."""
    try:
        d = (json.loads((_ROOT_LIVE / RAW_L2_LIVE).read_text(encoding="utf-8")) or {}).get(coin)
    except (OSError, ValueError):
        return None
    now_ms = int(time.time() * 1_000)
    snapshot = snapshot_from_mapping(
        coin,
        d,
        source="hyperliquid:ws:l2Book:dynamic",
        now_ms=now_ms,
    )
    if snapshot is None:
        return None
    age_ms = snapshot.age_ms(now_ms)
    if age_ms > age_max_s * 1_000:
        return None
    return snapshot.as_legacy_payload(now_ms=now_ms)


def _lecteur_l2_marquage(coin: str) -> dict | None:
    """MARQUAGE pendant la position : préfère le book WS FRAIS (abonnement dynamique) ; sinon repli REST
    on-demand. Marquage continu sans marteler le REST. (L'ADMISSION, elle, reste REST on-demand.)"""
    return _book_ws_frais(coin) or _lecteur_l2_ondemand(coin)


async def _l2_dynamique(root: Path, *, sync_s: float = 1.0) -> None:
    """Abonnement L2 WS DYNAMIQUE des coins à position RAW ouverte : demande → subscriptionResponse (ACK) →
    premier book → désabonnement à la clôture. Journalise le cycle (raw_l2_lifecycle.jsonl) + alimente
    raw_l2_live.json. Reconnexion résiliente. PUBLIC lecture seule (l2Book)."""
    import websockets
    abonnes: set = set()
    premier: set = set()
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
                abonnes.clear()
                premier.clear()
                while True:
                    cibles = _coins_actifs(root)
                    for c in cibles - abonnes:
                        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "l2Book", "coin": c}}))
                        abonnes.add(c)
                        _log_l2(root, "L2_SUB_DEMANDE", c)
                        print("[userfills] L2 sub demande %s" % c, flush=True)
                    for c in abonnes - cibles:
                        await ws.send(json.dumps({"method": "unsubscribe", "subscription": {"type": "l2Book", "coin": c}}))
                        abonnes.discard(c)
                        premier.discard(c)
                        _log_l2(root, "L2_UNSUB", c)
                        print("[userfills] L2 unsub %s" % c, flush=True)
                    try:
                        brut = await asyncio.wait_for(ws.recv(), timeout=sync_s)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    ch = msg.get("channel")
                    if ch == "subscriptionResponse":
                        sub = ((msg.get("data") or {}).get("subscription")) or {}
                        if sub.get("type") == "l2Book":
                            _log_l2(root, "L2_SUB_ACK", sub.get("coin"))
                            print("[userfills] L2 ACK subscriptionResponse %s" % sub.get("coin"), flush=True)
                    elif ch == "l2Book":
                        d = msg.get("data") or {}
                        coin, b = d.get("coin"), _parse_l2_ws(d)
                        if coin and b:
                            bids, asks = _full_levels(d)
                            received_ts_ms = int(time.time() * 1_000)
                            raw_exchange_ts = d.get("time")
                            try:
                                exchange_ts_ms = int(raw_exchange_ts) if raw_exchange_ts is not None else None
                            except (TypeError, ValueError):
                                exchange_ts_ms = None
                            _ecrire_book_live(
                                root,
                                coin,
                                b[0],
                                b[1],
                                b[2],
                                bids=bids,
                                asks=asks,
                                received_ts_ms=received_ts_ms,
                                exchange_ts_ms=exchange_ts_ms,
                            )
                            if coin not in premier:
                                premier.add(coin)
                                _log_l2(root, "L2_PREMIER_BOOK", coin, {"hl_bid": b[0], "hl_ask": b[1], "depth_usd": b[2]})
                                print("[userfills] L2 premier book %s bid=%s ask=%s depth=%s$" % (coin, b[0], b[1], b[2]), flush=True)
        except Exception as exc:  # noqa: BLE001 — reconnexion
            print("[userfills] L2 dyn reconnect (%s)" % str(exc)[:50], flush=True)
            await asyncio.sleep(3.0)


def _traiter_un(root: Path, fill: dict, coins_a_verifier: set, t_ws_mono: float) -> None:
    import time as _t
    recu = _t.time() * 1000
    with (root / FILLS_LIVE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(fill, ensure_ascii=False) + "\n")
    coins_a_verifier.add(fill.get("coin"))
    if _TAPE_FILLS is not None:                                   # → tape L2/OFI : réception MONOTONE (même process)
        try:
            _TAPE_FILLS.put_nowait((fill, t_ws_mono * 1000))
        except asyncio.QueueFull:
            pass
    for nom, coh in CO.COHORTES.items():
        r = CO.traiter_fill(coh, ETATS[nom], fill, root, token=RUN_TOKEN, t_ws_mono=t_ws_mono,
                            lecteur_l2=_lecteur_l2_marquage)               # admission = book WS prewarmé si frais, sinon REST
        _journal(root, fill, nom, r, recu)                        # trace TOUT, même les refus
        if r and r.get("ouverture"):
            print("[userfills] %s OUVRE %s @ %.4f latence=%dms (fill %s ts=%s)"
                  % (nom, r["ouverture"]["coin"], r["ouverture"]["prix_entree"], r.get("latence_ms", 0),
                     fill.get("vault", "")[:10], fill.get("ts_ms")), flush=True)
        elif r and (r.get("fermeture") or r.get("reduction")):
            e = r.get("fermeture") or r.get("reduction")
            print("[userfills] %s %s %s pnl=%.4f$" % (nom, e["raison"], e["coin"], e["realized_usd"]), flush=True)


async def _worker(root: Path, file: asyncio.Queue) -> None:
    curseurs = _charger_curseurs(root)
    while True:
        vault, fills, t_ws = await file.get()
        try:
            a_traiter = fills_a_traiter(vault, fills, curseurs)
            if a_traiter:
                coins = set()
                for f in a_traiter:
                    _traiter_un(root, f, coins, t_ws)
                _sauver_curseurs(root, curseurs)
                for coh in CO.COHORTES.values():                 # exits ÉVÉNEMENTIELS sur les coins bougés
                    CO.gerer_exits(coh, root, lecteur_l2=_lecteur_l2_marquage, close_run_id=RUN_ID)   # marquage book WS frais
        except Exception as exc:  # noqa: BLE001
            print("[userfills] worker err %s" % str(exc)[:60], flush=True)
        finally:
            file.task_done()


def _shards_userfills(vaults: list, taille: int = TAILLE_SHARD) -> list:
    """Découpe DÉTERMINISTE des vaults en shards de `taille` (5) — HL cape ~5 userFills/connexion. Rend
    [("A", [v...]), ("B", [v...]), ...] : groupes DISJOINTS (aucun doublon), ordre stable. Une socket par shard."""
    lettres = "ABCDEFGH"
    return [(lettres[i // taille], vaults[i:i + taille]) for i in range(0, len(vaults), taille)]


def _vault_du_message(msg, connus_par_lc: dict) -> str | None:
    """Démux d'un message userFills MULTIPLEXÉ : extrait le user (data.user) et le mappe sur la forme
    canonique abonnée (insensible à la casse). None si inconnu/illisible."""
    data = msg.get("data") if isinstance(msg, dict) else None
    u = (data or {}).get("user") if isinstance(data, dict) else None
    return connus_par_lc.get(str(u).lower()) if u else None


async def _userfills_multiplex(root: Path, vaults: list, file: asyncio.Queue, socket_id: str = "A") -> None:
    """UNE socket WS pour un SHARD de ≤5 userFills (HL cape ~5/connexion). 2 shards (A,B) de 5 + la socket L2
    = 3 connexions au total (< 10). Démux par data.user ; ACK réel = subscriptionResponse. Si CETTE socket
    tombe, SEUL son groupe de 5 se reconnecte ; le curseur + la dédup rejouent ses fills manqués (catch-up)."""
    import websockets
    connus = {v.lower(): v for v in vaults}
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
                _WS_PAR_SOCKET[socket_id] = ws                    # exposé au garde REST↔WS (reconnexion ciblée)
                for i, v in enumerate(vaults):
                    await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "userFills", "user": v}}))
                    print("[userfills] socket %s subscribe %d/%d userFills %s" % (socket_id, i + 1, len(vaults), v[:10]), flush=True)
                    await asyncio.sleep(0.3)                   # THROTTLE léger (5 subscribes) : évite tout drop HL
                print("[userfills] socket %s — %d abonnements userFills demandes" % (socket_id, len(vaults)), flush=True)
                confirmes: set = set()                            # vaults ayant envoyé ≥1 message = ABONNEMENT CONFIRMÉ
                async for brut in ws:
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and msg.get("channel") == "subscriptionResponse":
                        sub = ((msg.get("data") or {}).get("subscription")) or {}
                        if sub.get("type") == "userFills":
                            _HEARTBEAT_WS["acks"] += 1
                            print("[userfills] socket %s ACK subscribe userFills %s" % (socket_id, str(sub.get("user") or "")[:10]), flush=True)
                        continue
                    vault = _vault_du_message(msg, connus)
                    if not vault:
                        continue
                    _HEARTBEAT_WS["messages"] += 1
                    if vault not in confirmes:                     # 1er message (snapshot/fill) = ABONNEMENT CONFIRMÉ (fiable,
                        confirmes.add(vault)                       # contrairement au subscriptionResponse partiel de HL)
                        print("[userfills] socket %s vault CONFIRME (1er msg) %s [%d/%d]" % (socket_id, vault[:10], len(confirmes), len(vaults)), flush=True)
                    bruts = (msg.get("data") or {}).get("fills") or []   # CLÉS COMPOSITES REÇUES (pour REST−WS par id)
                    if bruts:
                        timestamps = []
                        for raw_fill in bruts:
                            try:
                                timestamps.append(int(raw_fill.get("time")))
                            except (AttributeError, TypeError, ValueError):
                                continue
                        if timestamps:
                            _HEARTBEAT_WS["dernier_exchange_ts"] = max(
                                max(timestamps), _HEARTBEAT_WS["dernier_exchange_ts"] or 0
                            )
                        dq = _WS_KEYS.setdefault(vault, collections.deque(maxlen=WS_KEYS_CAP))
                        for rf in bruts:
                            dq.append(SD.cle_fill(rf))
                    fills = UL.parser_message_userfills(msg, vault=vault)
                    if not fills:
                        continue
                    _HEARTBEAT_WS["fills"] += len(fills)
                    _journal_liquidations(root, UL.liquidations_confirmees(fills), socket_id=socket_id)  # CONFIRMÉES only
                    t_ws = time.monotonic()                       # HORLOGE MONOTONE LOCALE : réception WS
                    try:
                        file.put_nowait((vault, fills, t_ws))     # ne bloque JAMAIS la réception
                    except asyncio.QueueFull:
                        _HEARTBEAT_WS["drops"] += len(fills)
                        print("[userfills] FILE SATUREE — drop (%s)" % vault[:10], flush=True)
        except Exception as exc:  # noqa: BLE001 — reconnecte SEULEMENT ce shard de 5 (curseur+dédup -> catch-up)
            _HEARTBEAT_WS["reconnects"] += 1
            _WS_PAR_SOCKET.pop(socket_id, None)
            print("[userfills] socket %s reconnect (%s)" % (socket_id, str(exc)[:50]), flush=True)
            await asyncio.sleep(3.0)


async def _garde_reconciliation_rest(root: Path, shards: list, *, intervalle_s: float = 90.0,
                                     age_min_ms: float = 45_000.0, overlap_ms: float = 60_000.0) -> None:
    """GARDE REST↔WS (TRANSPORT seulement, config_hash inchangé) : périodiquement, pour chaque vault, on lit
    `userFillsByTime` depuis (curseur − chevauchement) [fenêtre BORNÉE ⇒ poids REST faible], on déduplique, et
    on compare les ENSEMBLES de fills par CLÉ COMPOSITE (time, hash, tid, oid, coin) — pas un simple curseur —
    contre les clés REÇUES par le WS (`_WS_KEYS`). Un vault est COUVERT tant que REST − WS = 0 par identifiant.
    Si REST − WS > 0 (fills assez vieux que le WS AURAIT DÛ recevoir) → shard DÉFAILLANT : on ferme SA socket →
    reconnexion CIBLÉE (curseur+dédup rejouent les manqués). On journalise le POIDS REST estimé (budget IP HL).
    REST hors event-loop ; le garde n'ouvre AUCUNE connexion WS. Lecture seule ; 0 ordre, 0 clé, 0 signature."""
    vault_socket = {v: sid for sid, grp in shards for v in grp}
    loop = asyncio.get_event_loop()
    await asyncio.sleep(intervalle_s)                             # laisse le WS s'installer avant tout jugement
    while True:
        cur = _charger_curseurs(root)
        maintenant = time.time() * 1000
        n_appels, total_manquants, defaillants, appels_budget = 0, 0, set(), []
        for v, sid in vault_socket.items():
            # fenêtre BORNÉE (curseur − chevauchement), JAMAIS avant le démarrage (clés en mémoire depuis là) :
            start = SD.fenetre_debut_ms(cur.get(v), _DEMARRAGE_MS, maintenant, overlap_ms=overlap_ms)
            try:
                rep = await loop.run_in_executor(None, SD.userfills_by_time_rest, v, start)   # REST hors event-loop
                n_appels += 1
                appels_budget.append(("userFillsByTime", len(rep) if isinstance(rep, list) else 0))
            except Exception:  # noqa: BLE001 — le réseau ne fait JAMAIS crasher le garde
                continue
            if not isinstance(rep, list):
                continue
            manquants = SD.fills_manquants_par_id(rep, _WS_KEYS.get(v, ()), age_min_ms=age_min_ms)
            if manquants:
                total_manquants += len(manquants)
                defaillants.add(sid)
                k0 = SD.cle_fill(manquants[0]) or (None, None, None, None, None)
                print("[userfills] ⛔ shard %s DEFAILLANT : REST-WS=%d par id sur %s (ex tid=%s ts=%s) -> reconnexion ciblee"
                      % (sid, len(manquants), v[:10], k0[2], k0[0]), flush=True)
        for sid in defaillants:                                   # reconnecte CHAQUE shard fautif (curseur+dédup -> catch-up)
            ws = _WS_PAR_SOCKET.get(sid)
            if ws is not None:
                try:
                    await ws.close()                              # rompt le async-for -> except -> reconnect de CE shard
                except Exception:  # noqa: BLE001
                    pass
        poids_passe = SD.poids_info(appels_budget)                # poids HL EXACT (20 + floor(items/20)) de la rafale
        SD.journaliser_budget(root, "garde_rest_ws", poids_passe, intervalle_s)
        bt = SD.budget_total(root)
        print("[userfills] garde REST↔WS : REST-WS=%d par id · %d appels · poids/passe=%d (rafale) · total REST~%.0f/%d IP·min · %s"
              % (total_manquants, n_appels, poids_passe, bt["total_par_min_moyen"], bt["limite_ip_par_min"],
                 ("defaillants=%s" % sorted(defaillants)) if defaillants else "10/10 couverts (REST-WS=0)"), flush=True)
        await asyncio.sleep(intervalle_s)


async def _exits_periodiques(root: Path, *, intervalle_s: float = 2.0) -> None:
    while True:
        for coh in CO.COHORTES.values():
            try:
                CO.gerer_exits(coh, root, lecteur_l2=_lecteur_l2_marquage, close_run_id=RUN_ID)
                CO.statut(coh, root, lecteur_l2=_lecteur_l2_marquage, run_id=RUN_ID, trigger_version=TRIGGER_VERSION,
                          config_hash=CO.config_hash_courant(coh, root))
            except Exception as exc:  # noqa: BLE001
                print("[userfills] exits %s err %s" % (coh.nom, str(exc)[:40]), flush=True)
        await asyncio.sleep(intervalle_s)


async def _heartbeat(root: Path, info: dict, *, intervalle_s: float = 10.0) -> None:
    derniers_messages = 0
    while True:
        VI.heartbeat(root, NOM_VERROU, info)
        messages = int(_HEARTBEAT_WS["messages"])
        HB.battre(
            root,
            "userfills-live",
            pid=os.getppid(),
            n_ecrites=max(0, messages - derniers_messages),
            dernier_exchange_ts=_HEARTBEAT_WS["dernier_exchange_ts"],
            souscription_ack=bool(_HEARTBEAT_WS["acks"] or messages),
            note="%d WS messages, %d fills" % (messages, int(_HEARTBEAT_WS["fills"])),
            metriques={
                "gaps_critiques": int(_HEARTBEAT_WS["drops"]),
                "reconnects": int(_HEARTBEAT_WS["reconnects"]),
                "stale": False,
            },
        )
        derniers_messages = messages
        await asyncio.sleep(intervalle_s)


async def _promotion_periodique(root: Path, *, intervalle_s: float = 300.0) -> None:
    """Note les CANDIDAT_OBSERVE depuis le journal et promeut les 2 meilleurs en mini-PROBE (5-10 $)."""
    from hl_observer.experimental import promotion_candidats as PC
    from hl_observer.experimental import raw_shadow_variantes as RS
    from hl_observer.experimental import cohortes as _CO
    from hl_observer.experimental.copy_edge_forward import charger_prix_tape
    while True:
        try:
            observes = {v for v, role, _w in vaults_et_roles(root) if role.startswith("CANDIDAT")}
            coins_probe = set(_CO.charger_table(_CO.PROBE, root))
            tape = charger_prix_tape(root)
            PC.construire(root, coins_probe=coins_probe, tape=tape, candidats_observes=observes)
            PC.scorer_paires(root, tape=tape)                     # SHADOW PAR PAIRE (même hors table PROBE)
            RS.ecrire(root, tape=tape)                            # SHADOW multi-seuils × âge réel (versionné)
        except Exception as exc:  # noqa: BLE001
            print("[userfills] promotion err %s" % str(exc)[:40], flush=True)
        await asyncio.sleep(intervalle_s)


async def _rapport_periodique(root: Path, *, intervalle_s: float = 30.0) -> None:
    """WATCHER LÉGER : dès qu'un 1er OPEN RAW réel existe, écrit runtime/rapports/PREMIER_RAW.md (OPEN puis
    CLOSE : timestamps monotones, prix L2, coûts, MFE/MAE, PnL, ROI, paire vault+coin). Signale une fois."""
    from hl_observer.experimental import rapport_raw as RR
    deja = False
    while True:
        try:
            p = RR.ecrire_rapport(root)
            if p and not deja:
                print("[userfills] PREMIER RAW capturé → %s" % p, flush=True)
                deja = True
        except Exception as exc:  # noqa: BLE001
            print("[userfills] rapport err %s" % str(exc)[:40], flush=True)
        await asyncio.sleep(intervalle_s)


async def _metaorder_shadow_periodique(root: Path, vaults: list, *, intervalle_s: float = 600.0) -> None:
    """SHADOW METAORDER_V1 : toutes les ~10 min, mesure l'edge par STADE de métaordre (TWAP étiqueté via
    userTwapSliceFills, métaordres cachés agrégés, stades FIRST/CONTINUATION/LATE/REVERSAL, PnL forward net
    après coûts, placebo, taille rel, maker/taker, âges). N'OUVRE AUCUNE POSITION ; ledger SÉPARÉ, jamais
    mélangé au PnL live. REST hors event-loop ; poids journalisé. 0 ordre, 0 clé, 0 signature."""
    from hl_observer.experimental import metaorder_shadow as MS
    import sonde_confirmation_vaults as SD
    loop = asyncio.get_event_loop()
    await asyncio.sleep(30.0)                                     # démarrage doux (laisse le live s'installer)
    while True:
        try:
            chash = CO.config_hash_courant(CO.RAW_PROBE, root)
            res = await loop.run_in_executor(
                None, lambda: MS.executer(root, list(vaults), config_hash=chash, git_commit=GIT_COMMIT))
            bt = res.get("budget_total") or {}
            stades = {k: (v.get("n_metaordres"), v.get("pnl_net_bps_moy")) for k, v in (res.get("stats") or {}).items()}
            cap = {k: v.get("capacite_edge_prouve_usd") for k, v in (res.get("courbe") or {}).items()}
            print("[userfills] metaorder_shadow : %d signaux · %d metaordres · L2_sync=%.0f%% · %d appels · poids/passe=%d · total REST~%.0f/%d IP·min · stades(n_mo,pnl)=%s · cap_edge_prouve$=%s"
                  % (res.get("n_signaux", 0), res.get("n_metaordres", 0), res.get("l2_synchronise_pct", 0),
                     res.get("n_appels", 0), res.get("poids_passe", 0), bt.get("total_par_min_moyen", 0),
                     bt.get("limite_ip_par_min", 1200), stades, cap), flush=True)
        except Exception as exc:  # noqa: BLE001 — la passe shadow ne fait JAMAIS crasher le collecteur
            print("[userfills] metaorder_shadow err %s" % str(exc)[:60], flush=True)
        await asyncio.sleep(intervalle_s)


# ── TAPE L2/OFI SHADOW v2 : buffer WS l2Book (snapshots SUCCESSIFS horodatés) + consommateur (états pré/post
#    par fill, VRAI OFI, 4 horloges séparées, latence pipeline ≥ 0). 1 connexion WS de plus (total 4 < 10).
_TAPE_FILLS = None                           # asyncio.Queue((fill, fill_recv_mono_ms)) — alimentée par le worker
_TAPE_COINS_ACTIFS: dict = {}                # coin -> dernier fill_recv (ms wall) : fenêtre d'abonnement l2Book
_TAPE_BUFFER: dict = {}                      # coin -> list[{recv_mono, resume}] (snapshots successifs)
TAPE_BUFFER_MAX = 400
TAPE_COIN_TTL_MS = 360_000.0                # coin abonné jusqu'à horizon(5 min)+marge après le dernier fill


async def _tape_l2_buffer(root: Path, *, sync_s: float = 0.5) -> None:
    """Abonne au l2Book WS les coins à métaordre ACTIF (dès le 1er fill = FIRST_SLICE) et BUFFERISE des
    snapshots HORODATÉS (réception MONOTONE) → base du VRAI OFI (variations successives). 1 connexion WS
    (total 4 < 10). Résilient. Lecture seule ; aucune position, RAW intact."""
    import websockets
    from hl_observer.experimental import metaorder_l2_tape as T
    abonnes: set = set()
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
                abonnes.clear()
                while True:
                    now = time.time() * 1000
                    cibles = {c for c, t in _TAPE_COINS_ACTIFS.items() if now - t <= TAPE_COIN_TTL_MS}
                    for c in cibles - abonnes:
                        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "l2Book", "coin": c}}))
                        abonnes.add(c)
                    for c in abonnes - cibles:
                        await ws.send(json.dumps({"method": "unsubscribe", "subscription": {"type": "l2Book", "coin": c}}))
                        abonnes.discard(c)
                        _TAPE_BUFFER.pop(c, None)
                    try:
                        brut = await asyncio.wait_for(ws.recv(), timeout=sync_s)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and msg.get("channel") == "l2Book":
                        d = msg.get("data") or {}
                        coin = str(d.get("coin") or "").upper()
                        r = T.resume_book(d)
                        if coin and r:
                            buf = _TAPE_BUFFER.setdefault(coin, [])
                            buf.append({"recv_mono": time.monotonic() * 1000, "resume": r})
                            if len(buf) > TAPE_BUFFER_MAX:
                                del buf[:len(buf) - TAPE_BUFFER_MAX]
        except Exception as exc:  # noqa: BLE001
            print("[userfills] tape_l2 reconnect (%s)" % str(exc)[:50], flush=True)
            await asyncio.sleep(3.0)


async def _tape_consumer(root: Path, *, horizon_ms: float = 300_000.0, post_window_ms: float = 8_000.0,
                         intervalle_s: float = 1.0) -> None:
    """Consomme les fills (file EN PROCESS → réception MONOTONE fiable) : marque le coin actif (abonnement),
    attend des snapshots POST-fill, puis extrait l'état PRÉ-fill + l'état d'ENTRÉE (postérieur au fill) + posts
    → ligne v2 (VRAI OFI, imbalance séparé, horloges séparées, latence ≥ 0). Sortie à +horizon avec retard réel.
    Aucun fill fictif : sans état d'entrée, on n'écrit rien. RAW intact ; aucune position."""
    from hl_observer.experimental import metaorder_l2_tape as T
    en_attente: list = []
    exits: list = []
    meta_etat: dict = {}                                          # (vault,coin) -> métaordre live (id/sens/last_ft)
    await asyncio.sleep(15.0)
    while True:
        try:
            while _TAPE_FILLS is not None and not _TAPE_FILLS.empty():
                f, frm = _TAPE_FILLS.get_nowait()
                _TAPE_COINS_ACTIFS[str(f.get("coin") or "").upper()] = time.time() * 1000   # abonne dès ce fill
                en_attente.append({"fill": f, "frm": float(frm), "due": time.monotonic() * 1000 + post_window_ms})
            mono = time.monotonic() * 1000
            lignes: list = []
            reste: list = []
            for it in en_attente:
                if mono < it["due"]:
                    reste.append(it)
                    continue
                buf = _TAPE_BUFFER.get(str(it["fill"].get("coin") or "").upper(), [])
                pre = T.etat_pre(buf, it["frm"])
                entree = T.etat_entree(buf, it["frm"], it["fill"].get("ts_ms"))
                posts = T.etats_post(buf, entree["recv_mono"], n=3) if entree else []
                mo, stade = T.stade_live(meta_etat, it["fill"])
                l = T.ligne_fill(it["fill"], metaorder_id=mo, stade=stade, pre=pre, entree=entree,
                                 posts=posts, fill_recv_mono=it["frm"])
                if l:
                    lignes.append(l)
                    exits.append({"fill": it["fill"], "frm": it["frm"], "due": it["frm"] + horizon_ms})
            en_attente = reste
            reste_ex: list = []
            for ex in exits:
                if mono < ex["due"]:
                    reste_ex.append(ex)
                    continue
                buf = _TAPE_BUFFER.get(str(ex["fill"].get("coin") or "").upper(), [])
                sortie = T.etat_entree(buf, ex["frm"] + horizon_ms, None)   # 1er carnet ≥ +horizon
                if sortie:
                    lignes.append(T.ligne_sortie(ex["fill"], sortie=sortie, capture_recv_mono=sortie["recv_mono"],
                                                 horizon_ms=horizon_ms, fill_recv_mono=ex["frm"]))
            exits = reste_ex
            T.ecrire_lignes(root, lignes)
        except Exception as exc:  # noqa: BLE001 — la tape ne fait JAMAIS crasher le collecteur
            print("[userfills] tape_consumer err %s" % str(exc)[:60], flush=True)
        await asyncio.sleep(intervalle_s)


def _git_commit(root: Path) -> str:
    """Commit git courant (audit SÉPARÉ du config_hash). Lit .git sans subprocess. '' si indisponible."""
    try:
        g = root / ".git"
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head                                          # detached HEAD = le sha directement
        ref = head[4:].strip()
        if (g / ref).exists():
            return (g / ref).read_text(encoding="utf-8").strip()
        for l in (g / "packed-refs").read_text(encoding="utf-8", errors="ignore").splitlines():
            if l.strip().endswith(ref):
                return l.split()[0]
        return ""
    except OSError:
        return ""


async def _boucle(root: Path) -> None:
    global RUN_ID, RUN_TOKEN, _MUTEX, _ROOT_LIVE, TRIGGER_VERSION, GIT_COMMIT, _DEMARRAGE_MS, _TAPE_FILLS
    _ROOT_LIVE = root
    _TAPE_FILLS = asyncio.Queue(maxsize=5000)                     # fills → tape L2 (réception MONOTONE en process)
    _DEMARRAGE_MS = time.time() * 1000                            # plancher de confiance du garde REST↔WS (clés en mémoire dès ici)
    _HEARTBEAT_WS.update({"messages": 0, "fills": 0, "acks": 0, "reconnects": 0,
                          "drops": 0, "dernier_exchange_ts": None})
    TRIGGER_VERSION = CO._params_trigger(root).get("variante", "v1")
    GIT_COMMIT = _git_commit(root)
    import secrets
    # VERROU PRINCIPAL = mutex nommé Windows ; le verrou fichier ne sert plus qu'au DIAGNOSTIC
    ok_mx, _MUTEX = VI.acquerir_mutex(NOM_VERROU)
    if ok_mx is False:
        print("[userfills] REFUS DEMARRAGE — mutex Windows deja tenu (instance active)", flush=True)
        return
    ok, info = VI.acquerir(root, NOM_VERROU)                       # verrou fichier (aussi gate : ancien code sans mutex)
    if not ok:                                                    # verrou fichier tenu par une instance FRAICHE -> refus
        print("[userfills] REFUS DEMARRAGE — verrou fichier deja tenu: %s" % info.get("detenteur"), flush=True)
        return
    RUN_ID = info["run_id"]
    RUN_TOKEN = secrets.token_hex(16)                             # provenance hors payload (en memoire)
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / CO.MARQUEUR_RUNTIME).write_text("runtime", encoding="utf-8")   # marque le RUNTIME_ROOT
    CO.autoriser_runtime(RUN_TOKEN)                               # SEUL le collecteur arme l'ecriture runtime
    print("[userfills] mutex=%s pid=%d run_id=%s (ecriture runtime armee)"
          % ("WIN" if ok_mx else "fichier", info["pid"], RUN_ID), flush=True)
    print("[userfills] commit=%s transport=%s trigger_version=%s config_hash(RAW)=%s"
          % (GIT_COMMIT[:12] or "?", TRANSPORT_VERSION, TRIGGER_VERSION, CO.config_hash_courant(CO.RAW_PROBE, root)[:19]), flush=True)
    for nom, coh in CO.COHORTES.items():
        ETATS[nom] = CO.etat_initial(coh, root, run_id=RUN_ID, token=RUN_TOKEN, git_commit=GIT_COMMIT,
                                     transport_version=TRANSPORT_VERSION)
    roles = vaults_et_roles(root)
    if not roles:
        print("[userfills] aucun vault suivi (deny-by-default) — rien a faire", flush=True)
        VI.liberer(root, NOM_VERROU, info)
        return
    (root / FILLS_LIVE).parent.mkdir(parents=True, exist_ok=True)
    print("[userfills] run_id=%s — VAULTS ABONNES (%d) :" % (RUN_ID, len(roles)), flush=True)
    for v, role, why in roles:
        print("[userfills]   %s [%s] %s" % (v[:12], role, why), flush=True)
    vaults = [v for v, _r, _w in roles]
    file: asyncio.Queue = asyncio.Queue(maxsize=FILE_MAX)
    try:
        shards = _shards_userfills(vaults)                            # ≤5 vaults par socket (HL cape ~5/connexion)
        for sid, grp in shards:
            print("[userfills] shard socket %s (%d vaults) : %s" % (sid, len(grp), ", ".join(v[:10] for v in grp)), flush=True)
        await asyncio.gather(_worker(root, file), _exits_periodiques(root), _heartbeat(root, info),
                             _promotion_periodique(root), _rapport_periodique(root), _l2_dynamique(root),
                             _garde_reconciliation_rest(root, shards),   # REST↔WS : reconnecte un shard qui rate un fill
                             _metaorder_shadow_periodique(root, vaults),  # SHADOW : edge par stade de métaordre (n'ouvre rien)
                             _tape_l2_buffer(root), _tape_consumer(root),  # TAPE L2/OFI v2 : buffer WS + états pré/post (n'ouvre rien)
                             *[_userfills_multiplex(root, grp, file, sid) for sid, grp in shards])   # 2 sockets de 5 + L2 = 3 conn
    finally:
        VI.liberer(root, NOM_VERROU, info)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Moteur WS userFills inline 2 cohortes (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    a = p.parse_args(argv)
    try:
        asyncio.run(_boucle(Path(a.root)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
