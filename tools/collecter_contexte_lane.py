#!/usr/bin/env python3
"""Collecteur WS de CONTEXTE leader (positions + TWAP + ordres en attente) — idées #26, #29.

Canaux user (sans signature) d'Hyperliquid, par leader :
- ``clearinghouseState`` : état complet du compte (positions par coin) en push →
  **snapshots de position frais** (le labo seede ses épisodes dessus).
- ``userTwapSliceFills`` : slices de TWAP/metaorders → **anticipation** et densité de fills.
- ``openOrders`` : ordres en attente (entrées limites, prises de profit, stops) → ce que le leader
  COMPTE faire, avant son exécution ; écrit sur changement seulement.

Par-user = soumis au cap 10 users/IP : chaque lane suit une tranche disjointe des
leaders (``--shard-index``/``--shard-count``). PAPER / LECTURE SEULE.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.forward_poll_fills import shard_leaders  # noqa: E402
from hl_observer.collection.ordres_leader import construire_instantane_ordres, signature_ordres  # noqa: E402
from hl_observer.collection.portefeuille_compte import construire_portefeuille, etat_du_compte  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
POS_OUT = Path("runtime") / "data" / "copy_vault_positions_lane.jsonl"
#: portefeuilles complets (une ligne = toutes les positions + valeur du compte), même format que
#: les instantanés de vault : cible directe de l'étude de réplication lente
SNAP_OUT = Path("runtime") / "data" / "copy_vault_snapshots_lane.jsonl"
CHANGEMENT_MIN_MS = 10_000              # au plus un instantané toutes les 10 s par compte et par dex
BATTEMENT_PORTEFEUILLE_MS = 300_000     # portefeuille inchangé : un battement toutes les 5 min
DEXS_DEFAUT = "xyz"                     # dex HIP-3 portant la majorité du notionnel des leaders
TWAP_OUT = Path("runtime") / "data" / "copy_vault_twap_lane.jsonl"
#: ordres en attente des leaders (une ligne = le carnet d'ordres d'un compte à un instant observé)
ORDRES_OUT = Path("runtime") / "data" / "copy_vault_orders_lane.jsonl"
ORDRES_CHANGEMENT_MIN_MS = 30_000       # au plus un carnet d'ordres toutes les 30 s par compte et par dex
DEFAULT_LEADERS_FILE = "config/copy_vault_leaders.json"
USERS_PAR_CONNEXION = 5


def _nb(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def parser_positions(data: Any, *, user: str, recv_ms: int) -> list[dict[str, Any]]:
    """Positions ouvertes depuis un message clearinghouseState."""
    etat = etat_du_compte(data)
    if etat is None:
        return []
    user = str(user or "").strip().lower()
    out: list[dict[str, Any]] = []
    for item in etat.get("assetPositions") or []:
        pos = item.get("position") if isinstance(item, dict) else None
        if not isinstance(pos, dict) or not pos.get("coin"):
            continue
        szi = _nb(pos.get("szi"))
        if szi is None or szi == 0:  # position plate = pas de position ouverte (bruit pour le seed)
            continue
        out.append({
            "schema_version": "hypersmart.copy_vault_positions.v1", "vault": user,
            "coin": str(pos.get("coin")), "szi": szi, "entry_px": _nb(pos.get("entryPx")),
            "position_value": _nb(pos.get("positionValue")), "unrealized_pnl": _nb(pos.get("unrealizedPnl")),
            "received_at_ms": int(recv_ms), "source": "CLEARINGHOUSE_WS", "data_origin": "REAL_OBSERVED",
        })
    return out


def parser_twap_fills(data: Any, *, user: str, recv_ms: int) -> list[dict[str, Any]]:
    """Fills de slices TWAP → schéma fill (source LIVE_TWAP, causal forward)."""
    if not isinstance(data, dict):
        return []
    user = str(user or "").strip().lower()
    fills = data.get("fills") or data.get("twapSliceFills") or []
    out: list[dict[str, Any]] = []
    for f in fills if isinstance(fills, list) else []:
        if isinstance(f, dict) and isinstance(f.get("fill"), dict):
            f = f["fill"]
        if not isinstance(f, dict):
            continue
        coin = f.get("coin")
        px, sz = _nb(f.get("px")), _nb(f.get("sz"))
        ts = f.get("time")
        if not coin or px is None or sz is None or px <= 0 or sz <= 0 or not isinstance(ts, int):
            continue
        side = str(f.get("side") or "")
        signe = 1 if side in ("B", "b") else -1 if side in ("A", "S", "a") else None
        if signe is None:
            continue
        out.append({
            "vault": user, "coin": str(coin), "px": px, "sz": sz, "signe": signe,
            "ts_ms": int(ts), "observed_at_ms": int(recv_ms), "isSnapshot": False, "is_snapshot": False,
            "hash": f.get("hash"), "tid": f.get("tid"), "oid": f.get("oid"),
            "source": "LIVE_TWAP", "source_id": "hyperliquid_twap_slice_fills",
        })
    return out


class LaneContexte:
    def __init__(self, pos_out: Path, twap_out: Path, snap_out: Path | None = None,
                 ordres_out: Path | None = None) -> None:
        self.pos_out = pos_out
        self.twap_out = twap_out
        self.snap_out = snap_out if snap_out is not None else pos_out.with_name(SNAP_OUT.name)
        self.ordres_out = ordres_out if ordres_out is not None else pos_out.with_name(ORDRES_OUT.name)
        self._derniers_ordres: dict[tuple[str, str], tuple[int, tuple]] = {}
        self._cadence_ordres: dict[tuple[str, str], int] = {}
        self.ordres = 0
        pos_out.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._vus_twap: set = set()
        self._dernier_portefeuille: dict[tuple[str, str], tuple[int, tuple]] = {}
        self.positions = 0
        self.portefeuilles = 0
        self.twap = 0
        self.reconnects = 0

    async def ecrire_portefeuille(self, snap: dict[str, Any] | None) -> bool:
        """Écrit l'instantané s'il CHANGE le portefeuille connu (10 s au moins entre deux), ou
        comme battement toutes les ``BATTEMENT_PORTEFEUILLE_MS`` : la continuité est prouvée sans
        recopier le même portefeuille à chaque message poussé par le serveur."""
        if snap is None:
            return False
        cle = (snap["vault"], snap["dex"])
        tailles = tuple(sorted((p["coin"], p["szi"]) for p in snap["positions"]))
        precedent = self._dernier_portefeuille.get(cle)
        if precedent is not None:
            age = snap["ts_ms"] - precedent[0]
            if age < CHANGEMENT_MIN_MS or (tailles == precedent[1] and age < BATTEMENT_PORTEFEUILLE_MS):
                return False
        self._dernier_portefeuille[cle] = (snap["ts_ms"], tailles)
        async with self._lock:
            with self.snap_out.open("a", encoding="utf-8") as h:
                h.write(json.dumps(snap, ensure_ascii=False) + "\n")
            self.portefeuilles += 1
        return True

    async def ecrire_ordres(self, snap: dict[str, Any] | None) -> bool:
        """Écrit le carnet d'ordres d'un compte s'il a CHANGÉ (30 s au moins entre deux écritures), ou
        comme battement : le serveur repousse la liste entière en continu, la recopier ne prouverait rien.

        Un carnet VIDE est écrit comme les autres : il prouve que le compte était suivi et n'avait
        aucun ordre — sans lui, une exécution non annoncée passerait pour une exécution non observée."""
        if snap is None:
            return False
        cle = (snap["vault"], snap["dex"])
        signature = signature_ordres(snap)
        precedent = self._derniers_ordres.get(cle)
        cadence = self._cadence_ordres.get(cle, ORDRES_CHANGEMENT_MIN_MS)
        if precedent is not None:
            age = snap["ts_ms"] - precedent[0]
            if age < cadence or (signature == precedent[1] and age < BATTEMENT_PORTEFEUILLE_MS):
                return False
            # Un carnet qui change à CHAQUE fenêtre est celui d'un compte qui cote en continu : on
            # l'échantillonne de moins en moins souvent (30 s, 1 min, 2 min... jusqu'au battement), sinon
            # il pèserait des dizaines de Mo par jour. Dès qu'il se calme, la cadence fine revient.
            if signature != precedent[1] and age < 2 * cadence:
                cadence = min(2 * cadence, BATTEMENT_PORTEFEUILLE_MS)
            else:
                cadence = ORDRES_CHANGEMENT_MIN_MS
        self._cadence_ordres[cle] = cadence
        snap = {**snap, "cadence_ms": cadence}
        self._derniers_ordres[cle] = (snap["ts_ms"], signature)
        async with self._lock:
            with self.ordres_out.open("a", encoding="utf-8") as h:
                h.write(json.dumps(snap, ensure_ascii=False) + "\n")
            self.ordres += 1
        return True

    async def ecrire_positions(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self._lock:
            with self.pos_out.open("a", encoding="utf-8") as h:
                for r in rows:
                    h.write(json.dumps(r, ensure_ascii=False) + "\n")
            self.positions += len(rows)

    async def ecrire_twap(self, rows: list[dict[str, Any]]) -> None:
        nouveaux = []
        for r in rows:
            cle = (r.get("vault"), r.get("coin"), r.get("ts_ms"), r.get("tid"), r.get("hash"))
            if cle in self._vus_twap:
                continue
            self._vus_twap.add(cle)
            nouveaux.append(r)
        if not nouveaux:
            return
        async with self._lock:
            with self.twap_out.open("a", encoding="utf-8") as h:
                for r in nouveaux:
                    h.write(json.dumps(r, ensure_ascii=False) + "\n")
            self.twap += len(nouveaux)


async def _connexion(lane: LaneContexte, users: list[str], socket_id: str, deadline: float,
                     lane_dexs: tuple[str, ...] = ()) -> None:
    import websockets

    connus = {v.lower(): v for v in users}
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22,
                                          compression="deflate") as ws:
                for v in users:
                    for t in ("clearinghouseState", "userTwapSliceFills", "openOrders"):
                        await ws.send(json.dumps({"method": "subscribe",
                                                  "subscription": {"type": t, "user": v}}))
                        await asyncio.sleep(0.2)
                    # un compte a un état par dex : sans cet abonnement, les positions prises sur
                    # un dex HIP-3 (la majorité du notionnel des leaders) restent invisibles
                    for dex in lane_dexs:
                        for t in ("clearinghouseState", "openOrders"):
                            await ws.send(json.dumps({"method": "subscribe", "subscription":
                                                      {"type": t, "user": v, "dex": dex}}))
                            await asyncio.sleep(0.2)
                print(f"[contexte] socket {socket_id} : {len(users)} leaders (positions+TWAP+ordres)", flush=True)
                while time.monotonic() < deadline:
                    reste = max(0.0, deadline - time.monotonic())
                    try:
                        brut = await asyncio.wait_for(ws.recv(), timeout=min(30.0, reste or 1.0))
                    except asyncio.TimeoutError:
                        if time.monotonic() >= deadline:
                            return
                        continue
                    recv_ms = int(time.time() * 1000)
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    canal = msg.get("channel")
                    data = msg.get("data")
                    if not isinstance(data, dict):
                        continue
                    user = str(data.get("user") or "")
                    if user and user.lower() not in connus:
                        continue
                    if canal == "clearinghouseState":
                        # Le serveur repousse l'état complet en continu : positions par coin et
                        # portefeuille ne sont écrits que sur changement, ou comme battement.
                        if await lane.ecrire_portefeuille(
                                construire_portefeuille(data, user=user, recv_ms=recv_ms)):
                            await lane.ecrire_positions(parser_positions(data, user=user, recv_ms=recv_ms))
                    elif canal == "userTwapSliceFills":
                        await lane.ecrire_twap(parser_twap_fills(data, user=user, recv_ms=recv_ms))
                    elif canal == "openOrders":
                        await lane.ecrire_ordres(construire_instantane_ordres(data, user=user, recv_ms=recv_ms))
        except Exception as exc:  # noqa: BLE001
            lane.reconnects += 1
            print(f"[contexte] socket {socket_id} reconnexion ({type(exc).__name__})", flush=True)
            await asyncio.sleep(min(5.0, 1.0 + lane.reconnects * 0.5))


def _charger_leaders(root: Path, chemin: str) -> list[str]:
    try:
        data = json.loads((root / chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    vaults = data.get("vaults") if isinstance(data, dict) else data
    if not isinstance(vaults, list):
        return []
    vus: dict[str, None] = {}
    for v in vaults:
        s = str(v).strip()
        if s.lower().startswith("0x") and len(s) >= 10:
            vus.setdefault(s, None)
    return list(vus)


#: Sources possibles pour la liste de leaders de cette lane.
SOURCE_FICHIER = "fichier"
SOURCE_FILLS = "fills"


def leaders_alignes_sur_les_fills(root: Path) -> list[str]:
    """Les comptes dont le collecteur de fills LOCAL capte reellement les fills (``vaults_suivis``).

    POURQUOI. Mesure du 12/11 : l'etude des ordres en attente (``copy_vault_order_intent``) voyait
    « 0 fill pendant le suivi des carnets d'ordres ». Cause trouvee par inspection : cette lane suit
    ``config/copy_vault_leaders.json`` (liste partagee, alimentee par l'explorer) tandis que le
    collecteur de fills LOCAL suit sa PROPRE selection (<=10 slots WS : CORE + sentinelles + rotation).
    Deux ensembles qui se recoupent a peine : des ordres d'un cote, des fills de l'autre, donc jamais
    le couple ordre -> fill dont l'etude maker a besoin. Aligner les deux sources est LE correctif.

    Lecture seule et sans effet de bord : le module importe ne fait que lire des variables
    d'environnement et construire des chemins (verifie par analyse de l'AST). Rend ``[]`` si la
    selection est indisponible — l'alignement est un confort, jamais un point de panne.
    """
    try:
        import collecter_userfills_vaults as fills   # tools/ est dans sys.path (voir en-tete)
        retenus = fills.vaults_suivis(root)
    except Exception:  # noqa: BLE001
        return []
    vus: dict[str, None] = {}
    for v in retenus or ():
        s = str(v).strip()
        if s.lower().startswith("0x") and len(s) >= 10:
            vus.setdefault(s, None)
    return list(vus)


def choisir_les_leaders(root: Path, *, source: str, chemin: str,
                        selection_fills=None) -> tuple[list[str], str, str]:
    """(leaders, source retenue, raison lisible).

    Ne rend JAMAIS une liste vide en silence : si l'alignement sur les fills ne donne rien, on retombe
    sur la liste partagee ET on l'annonce (un desalignement silencieux est ce qui a coute la mesure).
    """
    depuis_fichier = _charger_leaders(root, chemin)
    if str(source) != SOURCE_FILLS:
        return depuis_fichier, SOURCE_FICHIER, f"liste partagee {chemin}"
    selection = (selection_fills or leaders_alignes_sur_les_fills)(root)
    if selection:
        communs = len(set(selection) & set(depuis_fichier))
        return (selection, SOURCE_FILLS,
                f"alignes sur les fills locaux ({len(selection)} comptes, {communs} aussi dans {chemin})")
    return (depuis_fichier, SOURCE_FICHIER,
            f"selection des fills vide -> repli sur {chemin} "
            f"(ATTENTION : ordres et fills risquent d'etre desalignes)")


async def _battement(lane: "LaneContexte", deadline: float, intervalle_s: float = 60.0,
                     dormir=None, horloge=None) -> int:
    """Une ligne de vie par minute. Rend le nombre de lignes emises.

    POURQUOI. Le superviseur juge la vie d'un collecteur SANS fichier heartbeat sur la FRAICHEUR DE SON
    LOG (13 entrees du registre fonctionnent ainsi). Or cette lane n'ecrit que sur CHANGEMENT : un
    marche calme la rendrait muette plusieurs minutes et le superviseur relancerait un processus
    VIVANT — c'est-a-dire une double collecte, exactement ce que la regle anti-relance interdit.
    Une ligne par minute supprime ce faux positif, et donne en prime l'observabilite de la session.
    """
    dormir = dormir or asyncio.sleep
    horloge = horloge or time.monotonic
    lignes = 0
    while float(horloge()) < deadline:
        reste = deadline - float(horloge())
        await dormir(min(max(1.0, float(intervalle_s)), max(1.0, reste)))
        if float(horloge()) >= deadline:
            break
        lignes += 1
        print(f"[contexte] vivant : {lane.positions} positions, {lane.portefeuilles} portefeuilles, "
              f"{lane.twap} TWAP, {lane.ordres} carnets d'ordres, {lane.reconnects} reconnexions",
              flush=True)
    return lignes


async def _boucle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    tous, source_retenue, raison_source = choisir_les_leaders(
        root, source=getattr(args, "leaders_source", SOURCE_FICHIER), chemin=args.leaders_file)
    print(f"[contexte] leaders : {raison_source}", flush=True)
    lane_leaders = shard_leaders(tous, args.shard_count, args.shard_index)[: max(1, int(args.max_users))]
    if not lane_leaders:
        print("[contexte] aucun leader pour cette lane.", flush=True)
        return 0
    pos_out = (root / POS_OUT) if not args.pos_out else Path(args.pos_out)
    twap_out = (root / TWAP_OUT) if not args.twap_out else Path(args.twap_out)
    pos_out = pos_out if pos_out.is_absolute() else root / pos_out
    twap_out = twap_out if twap_out.is_absolute() else root / twap_out
    snap_out = (root / SNAP_OUT) if not args.snap_out else Path(args.snap_out)
    snap_out = snap_out if snap_out.is_absolute() else root / snap_out
    ordres_out = (root / ORDRES_OUT) if not args.ordres_out else Path(args.ordres_out)
    ordres_out = ordres_out if ordres_out.is_absolute() else root / ordres_out
    lane = LaneContexte(pos_out, twap_out, snap_out, ordres_out)
    lane_dexs = tuple(d.strip() for d in str(args.dexs or "").split(",") if d.strip())
    pas = max(1, int(args.users_par_connexion))
    groupes = [lane_leaders[i:i + pas] for i in range(0, len(lane_leaders), pas)]
    deadline = time.monotonic() + max(10.0, float(args.duree_s))
    print(f"[contexte] lane {args.shard_index}/{args.shard_count} : {len(lane_leaders)} leaders "
          f"(source {source_retenue}), {int(args.duree_s)}s.", flush=True)
    taches = [asyncio.create_task(_connexion(lane, g, chr(65 + i), deadline, lane_dexs))
              for i, g in enumerate(groupes)]
    taches.append(asyncio.create_task(_battement(lane, deadline)))
    await asyncio.gather(*taches, return_exceptions=True)
    print(f"[contexte] fini : {lane.positions} positions + {lane.portefeuilles} portefeuilles complets + "
          f"{lane.twap} TWAP fills + {lane.ordres} carnets d'ordres, {lane.reconnects} reconnexions.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur contexte leader (positions+TWAP), lecture seule.")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--leaders-file", default=DEFAULT_LEADERS_FILE)
    p.add_argument("--leaders-source", choices=(SOURCE_FICHIER, SOURCE_FILLS),
                   default=SOURCE_FICHIER,
                   help="'fichier' = liste partagee (defaut : lanes cloud inchangees) ; "
                        "'fills' = EXACTEMENT les comptes dont le collecteur de fills local "
                        "capte les fills, pour aligner ordres <-> fills (etude maker)")
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--max-users", type=int, default=10)
    p.add_argument("--users-par-connexion", type=int, default=USERS_PAR_CONNEXION)
    p.add_argument("--duree-s", type=float, default=1500.0)
    p.add_argument("--pos-out", default="")
    p.add_argument("--twap-out", default="")
    p.add_argument("--snap-out", default="", help="instantanés complets de portefeuille (positions + valeur du compte)")
    p.add_argument("--ordres-out", default="", help="ordres en attente des leaders (écrits sur changement)")
    p.add_argument("--dexs", default=DEXS_DEFAUT,
                   help="dex HIP-3 dont l'état du compte est aussi suivi (séparés par des virgules ; vide = aucun)")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_boucle(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
