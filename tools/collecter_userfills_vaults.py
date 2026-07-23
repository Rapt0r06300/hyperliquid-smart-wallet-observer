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


def vaults_et_roles(root: Path, *, n_candidats: int = 6) -> list[tuple[str, str, str]]:
    """(vault, role, raison) réellement ABONNÉS : CORE (retenus stricts, TRADENT ALPHA+PROBE) + jusqu'à
    n_candidats CANDIDATS (suivants par composite, OBSERVÉS en WS ; PROBE ne les TRADE que s'ils passent la
    sécurité mini via _vaults_cohorte). Deny-by-default : sans score, aucun abonnement."""
    try:
        d = json.loads((root / SCORES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    classement = d.get("classement") or []
    core = [c["vault"] for c in classement if c.get("retenu")][:2]
    out = [(v, "CORE", "retenu strict (score) → trade ALPHA+PROBE") for v in core]
    for c in classement:
        if c["vault"] in core:
            continue
        f = c.get("facteurs", {})
        sur = (float(f.get("anciennete_j") or 0) >= 45 and float(f.get("drawdown_pct") or 100) <= 45
               and float(f.get("copyabilite") or 0) >= 0.5)
        role = "CANDIDAT_TRADABLE" if sur else "CANDIDAT_OBSERVE"
        raison = "observé en WS ; PROBE l'ouvre" if sur else "observé en WS seulement (sécurité mini non passée)"
        out.append((c["vault"], role, raison))
        if len(out) >= 2 + n_candidats:
            break
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
             "dir": fill.get("dir"), "source": fill.get("source"), "fill_ts_ms": fill.get("ts_ms"),
             "latence_fill_decision_ms": round(recu_ms - float(fill.get("ts_ms") or recu_ms)),
             "decision": etat, "run_id": RUN_ID}
    with (root / JOURNAL).open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")


def _traiter_un(root: Path, fill: dict, coins_a_verifier: set) -> None:
    import time as _t
    recu = _t.time() * 1000
    with (root / FILLS_LIVE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(fill, ensure_ascii=False) + "\n")
    coins_a_verifier.add(fill.get("coin"))
    for nom, coh in CO.COHORTES.items():
        r = CO.traiter_fill(coh, ETATS[nom], fill, root, token=RUN_TOKEN)   # token hors-payload
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
        vault, fills = await file.get()
        try:
            a_traiter = fills_a_traiter(vault, fills, curseurs)
            if a_traiter:
                coins = set()
                for f in a_traiter:
                    _traiter_un(root, f, coins)
                _sauver_curseurs(root, curseurs)
                for coh in CO.COHORTES.values():                 # exits ÉVÉNEMENTIELS sur les coins bougés
                    CO.gerer_exits(coh, root)
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
                    try:
                        file.put_nowait((vault, fills))           # ne bloque JAMAIS la réception
                    except asyncio.QueueFull:
                        print("[userfills] FILE SATUREE — drop (%s)" % vault[:10], flush=True)
        except Exception as exc:  # noqa: BLE001 — reconnect
            print("[userfills] %s reconnect (%s)" % (vault[:10], str(exc)[:50]), flush=True)
            await asyncio.sleep(3.0)


async def _exits_periodiques(root: Path, *, intervalle_s: float = 2.0) -> None:
    while True:
        for coh in CO.COHORTES.values():
            try:
                CO.gerer_exits(coh, root)
                CO.statut(coh, root)
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
    from hl_observer.experimental import cohortes as _CO
    from hl_observer.experimental.copy_edge_forward import charger_prix_tape
    while True:
        try:
            observes = {v for v, role, _w in vaults_et_roles(root) if role.startswith("CANDIDAT")}
            coins_probe = set(_CO.charger_table(_CO.PROBE, root))
            PC.construire(root, coins_probe=coins_probe, tape=charger_prix_tape(root), candidats_observes=observes)
        except Exception as exc:  # noqa: BLE001
            print("[userfills] promotion err %s" % str(exc)[:40], flush=True)
        await asyncio.sleep(intervalle_s)


async def _boucle(root: Path) -> None:
    global RUN_ID, RUN_TOKEN, _MUTEX
    import secrets
    # VERROU PRINCIPAL = mutex nommé Windows ; le verrou fichier ne sert plus qu'au DIAGNOSTIC
    ok_mx, _MUTEX = VI.acquerir_mutex(NOM_VERROU)
    if ok_mx is False:
        print("[userfills] REFUS DEMARRAGE — mutex Windows deja tenu (instance active)", flush=True)
        return
    ok, info = VI.acquerir(root, NOM_VERROU)                       # verrou fichier = diagnostic/heartbeat
    if ok_mx is None and not ok:                                   # hors Windows : le fichier fait foi
        print("[userfills] REFUS DEMARRAGE — instance deja active: %s" % info.get("detenteur"), flush=True)
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
                             _promotion_periodique(root), *[_un_vault(root, v, file) for v in vaults])
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
