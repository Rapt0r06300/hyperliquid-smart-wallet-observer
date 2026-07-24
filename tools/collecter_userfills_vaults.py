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
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import userfills_live as UL  # noqa: E402
from hl_observer.collection import verrou_instance as VI  # noqa: E402
from hl_observer.experimental import cohortes as CO  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
FILLS_LIVE = Path("runtime") / "data" / "vault_fills_live.jsonl"
JOURNAL = Path("runtime") / "data" / "fills_journal.jsonl"       # CHAQUE fill live non-snapshot + gate + latence
CURSEURS = Path("runtime") / "data" / "userfills_curseurs.json"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
FILE_MAX = 2000                  # file bornée : si saturée, on drop (on ne bloque JAMAIS la reception WS)
NOM_VERROU = "userfills_live"
RUN_ID = ""
RUN_TOKEN = ""                    # provenance HORS PAYLOAD (en mémoire) — arme le trade + l'écriture runtime
_MUTEX = None                     # handle du mutex Windows (à garder vivant)
TRIGGER_VERSION = "v1"            # version du déclencheur (estampillée OPEN+CLOSE ; filtre les stats config courante)


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


def vaults_et_roles(root: Path, *, n_candidats: int = 8) -> list[tuple[str, str, str]]:
    """(vault, role, raison) sur les 10 places WS : 2 CORE (retenus stricts, TRADENT ALPHA+PROBE) + jusqu'à
    n_candidats=8 CANDIDATS OBSERVÉS choisis par ROTATION = activité live + qualité shadow + copyabilité
    (pas seulement le composite). PROBE ne TRADE un candidat que s'il passe la sécurité mini (via
    _vaults_cohorte). Deny-by-default : sans score, aucun abonnement."""
    try:
        d = json.loads((root / SCORES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    classement = d.get("classement") or []
    core = [c["vault"] for c in classement if c.get("retenu")][:2]
    out = [(v, "CORE", "retenu strict (score) → trade ALPHA+PROBE") for v in core]
    act, sha = _activite_par_vault(root), _shadow_par_vault(root)
    a_max = max(act.values()) if act else 1
    s_max = max(sha.values()) if sha else 1
    def _rotation(c: dict) -> float:                                  # score de rotation des candidats
        v, f = c["vault"], c.get("facteurs", {})
        a = act.get(v, 0) / a_max if a_max else 0.0                   # activité live
        s = max(0.0, sha.get(v, 0.0)) / s_max if s_max else 0.0       # qualité shadow (positive)
        cp = float(f.get("copyabilite") or 0.0)                       # copyabilité
        return 0.45 * a + 0.30 * s + 0.25 * cp
    cands = sorted((c for c in classement if c["vault"] not in core), key=_rotation, reverse=True)
    for c in cands[:n_candidats]:
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
    d = {"hl_bid": bid, "hl_ask": ask, "depth_usd": round(depth, 2), "age_ms": 0.0}
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


def _ecrire_book_live(root: Path, coin: str, bid: float, ask: float, depth: float) -> None:
    p = root / RAW_L2_LIVE
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        cur = {}
    cur[coin] = {"hl_bid": bid, "hl_ask": ask, "depth_usd": depth, "collecte_ts": time.time()}
    try:
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _book_ws_frais(coin: str, *, age_max_s: float = 1.5) -> dict | None:
    """Book WS FRAIS (<age_max_s) alimenté par l'abonnement dynamique — pour le MARQUAGE (pas le REST)."""
    try:
        d = (json.loads((_ROOT_LIVE / RAW_L2_LIVE).read_text(encoding="utf-8")) or {}).get(coin)
    except (OSError, ValueError):
        return None
    if not d or float(d.get("hl_bid") or 0) <= 0 or float(d.get("hl_ask") or 0) <= 0:
        return None
    age = time.time() - float(d.get("collecte_ts") or 0)
    if age > age_max_s:
        return None
    return {"hl_bid": float(d["hl_bid"]), "hl_ask": float(d["hl_ask"]),
            "depth_usd": float(d.get("depth_usd") or 0.0), "age_ms": age * 1000.0}


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
                            _ecrire_book_live(root, coin, b[0], b[1], b[2])
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


async def _un_vault(root: Path, vault: str, file: asyncio.Queue) -> None:
    import websockets
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
                await ws.send(json.dumps({"method": "subscribe",
                                          "subscription": {"type": "userFills", "user": vault}}))
                print("[userfills] ACK subscribe userFills %s" % vault[:10], flush=True)
                async for brut in ws:
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    fills = UL.parser_message_userfills(msg, vault=vault)
                    if not fills:
                        continue
                    t_ws = time.monotonic()                       # HORLOGE MONOTONE LOCALE : réception WS
                    try:
                        file.put_nowait((vault, fills, t_ws))     # ne bloque JAMAIS la réception
                    except asyncio.QueueFull:
                        print("[userfills] FILE SATUREE — drop (%s)" % vault[:10], flush=True)
        except Exception as exc:  # noqa: BLE001 — reconnect
            print("[userfills] %s reconnect (%s)" % (vault[:10], str(exc)[:50]), flush=True)
            await asyncio.sleep(3.0)


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
    while True:
        VI.heartbeat(root, NOM_VERROU, info)
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


async def _boucle(root: Path) -> None:
    global RUN_ID, RUN_TOKEN, _MUTEX, _ROOT_LIVE, TRIGGER_VERSION
    _ROOT_LIVE = root
    TRIGGER_VERSION = CO._params_trigger(root).get("variante", "v1")
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
    for nom, coh in CO.COHORTES.items():
        ETATS[nom] = CO.etat_initial(coh, root, run_id=RUN_ID, token=RUN_TOKEN)
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
        await asyncio.gather(_worker(root, file), _exits_periodiques(root), _heartbeat(root, info),
                             _promotion_periodique(root), _rapport_periodique(root), _l2_dynamique(root),
                             *[_un_vault(root, v, file) for v in vaults])
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
