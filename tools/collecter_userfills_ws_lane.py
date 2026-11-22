#!/usr/bin/env python3
"""Collecteur WS userFills LÉGER pour LANE multi-IP (capacité ×N de fills LIVE_WS).

Cap Hyperliquid = ~5 userFills/connexion et ≤10 users uniques/IP. Pour collecter PLUS
de fills live, on fait tourner CE collecteur sur plusieurs IP (runners GitHub) : chaque
lane suit une TRANCHE DISJOINTE des leaders (``--shard-index``/``--shard-count``), en
WS temps réel. Autonome (aucun mutex/cohorte/rotation du gros collecteur), time-boxé,
pensé pour un runner.

Discipline causale STRICTE (comme le poll forward) :
- 1re observation d'un user = SNAPSHOT (``isSnapshot=true``) → fixe le high-water, n'émet
  AUCUN fill (préexistants) ;
- messages suivants (``isSnapshot=false``) → n'émet que les fills STRICTEMENT nouveaux
  (``ts_ms`` > high-water), estampillés à l'instant RÉEL de réception (``observed_at_ms``),
  source ``LIVE_WS``.
Au reconnect : gap-fill REST ``userFillsByTime`` sur la fenêtre de coupure (zéro trou),
dédupliqué par identité (partagé avec le poll).

LECTURE SEULE / PAPER : aucune clé, aucun ordre, aucune signature.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.userfills_live import parser_message_userfills  # noqa: E402
from hl_observer.collection.userfills_resilience import (  # noqa: E402
    DedupFills, fenetre_gapfill,
)
from hl_observer.collection.forward_poll_fills import shard_leaders  # noqa: E402
from hl_observer.collection.subscription_universe import (  # noqa: E402
    selectionner_challengers_ucb,
)
from hl_observer.collection.orchestrateur_lanes import (  # noqa: E402
    leaders_par_lane,
    orchestrer,
)
from hl_observer.collection.activite_predictive import classer_leaders  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
REST_URL = "https://api.hyperliquid.xyz/info"
SOURCE_ID = "hyperliquid_public_userfills"
OUT_DEFAUT = Path("runtime") / "data" / "vault_fills_ws_lane.jsonl"
DEFAULT_LEADERS_FILE = "config/copy_vault_leaders.json"
SUBS_PAR_CONNEXION = 5           # HL cape ~5 userFills/connexion
MAX_USERS_IP = 10                # HL cape ~10 users uniques/IP


# --------------------------------------------------------------------------- #
# Cœur PUR (testable) : discipline causale forward
# --------------------------------------------------------------------------- #

def filtrer_forward(fills: list[dict[str, Any]], high_water_ms: int | None) -> tuple[list[dict[str, Any]], int | None]:
    """Garde les fills STRICTEMENT nouveaux (ts_ms > high-water) et renvoie le
    nouveau high-water. Jamais d'émission d'un fill <= high-water (anti-doublon causal).
    """
    nouveaux: list[dict[str, Any]] = []
    hw = high_water_ms
    for f in fills:
        ts = f.get("ts_ms")
        if not isinstance(ts, int):
            continue
        if high_water_ms is None or ts > high_water_ms:
            nouveaux.append(f)
        hw = ts if hw is None else max(hw, ts)
    return nouveaux, hw


def high_water_snapshot(fills: list[dict[str, Any]], now_ms: int) -> int:
    """High-water d'amorçage depuis un snapshot : max(ts) des fills, sinon maintenant."""
    tss = [f["ts_ms"] for f in fills if isinstance(f.get("ts_ms"), int)]
    return max(tss) if tss else int(now_ms)


# --------------------------------------------------------------------------- #
# REST (gap-fill) — lecture seule
# --------------------------------------------------------------------------- #

def _rest_userfills(user: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    corps = json.dumps({"type": "userFillsByTime", "user": user,
                        "startTime": int(start_ms), "endTime": int(end_ms)}).encode("utf-8")
    req = urllib.request.Request(REST_URL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:  # noqa: S310 (URL constante)
        data = json.loads(rep.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def _normaliser(message_data: dict[str, Any], *, user: str, received_at_ms: int,
                recv_mono_ns: int | None, connection_id: str) -> list[dict[str, Any]]:
    """Enveloppe des fills (WS ou REST) dans le format attendu par le parser pur."""
    msg = {"channel": "userFills", "data": message_data}
    return parser_message_userfills(
        msg, vault=user, received_at_ms=received_at_ms,
        receive_mono_ns=recv_mono_ns, connection_id=connection_id,
    )


class LaneWS:
    """État partagé d'une lane : écriture, dédup, high-water par user, compteurs."""

    def __init__(self, out_path: Path) -> None:
        self.out_path = out_path
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.dedup = DedupFills(capacite=300_000)
        self.high_water: dict[str, int] = {}
        self.seeded: set[str] = set()
        self._lock = asyncio.Lock()
        self.emis = 0
        self.reconnects = 0
        self.gapfills = 0
        self.resubscribes = 0

    async def emettre(self, fills: list[dict[str, Any]], *, observed_at_ms: int) -> None:
        if not fills:
            return
        nouveaux = self.dedup.filtrer_nouveaux(fills)
        if not nouveaux:
            return
        async with self._lock:
            with self.out_path.open("a", encoding="utf-8") as h:
                for f in nouveaux:
                    f = {**f, "source": "LIVE_WS", "is_snapshot": False,
                         "observed_at_ms": observed_at_ms, "source_id": SOURCE_ID}
                    h.write(json.dumps(f, ensure_ascii=False) + "\n")
            self.emis += len(nouveaux)

    async def gap_fill(self, users: list[str], *, now_ms: int) -> None:
        """Rattrape par REST la fenêtre manquée pour chaque user de la connexion."""
        for user in users:
            fen = fenetre_gapfill(self.high_water.get(user.lower()), now_ms)
            if fen is None:
                continue
            start, end = fen
            try:
                bruts = await asyncio.to_thread(_rest_userfills, user, start, end)
            except Exception as exc:  # noqa: BLE001 (gap-fill résilient)
                print(f"[ws-lane] gap-fill {user[:10]} erreur {type(exc).__name__}", flush=True)
                continue
            parsed = _normaliser({"user": user, "isSnapshot": False, "fills": bruts},
                                 user=user, received_at_ms=now_ms, recv_mono_ns=None,
                                 connection_id=f"gapfill-{user[:8]}")
            nouveaux, hw = filtrer_forward(parsed, self.high_water.get(user.lower()))
            if hw is not None:
                self.high_water[user.lower()] = hw
            await self.emettre(nouveaux, observed_at_ms=now_ms)
            self.gapfills += len(nouveaux)


async def _connexion(lane: LaneWS, users: list[str], socket_id: str, deadline: float) -> None:
    """Une connexion WS pour un groupe de ≤5 users. Reconnexion + gap-fill bornés."""
    import websockets

    connus = {v.lower(): v for v in users}
    serie = 0
    while time.monotonic() < deadline:
        try:
            # compression="deflate" : permessage-deflate explicite (plus de subs/bande passante).
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22,
                                          compression="deflate") as ws:
                serie += 1
                connection_id = f"ws-lane-{socket_id}-{int(time.time()*1000)}-{serie}"

                async def _souscrire(cibles):
                    for v in cibles:
                        await ws.send(json.dumps({"method": "subscribe",
                                                  "subscription": {"type": "userFills", "user": v}}))
                        await asyncio.sleep(0.3)   # throttle anti-drop HL

                await _souscrire(users)
                acks: set[str] = set()
                t_check = time.monotonic()
                print(f"[ws-lane] socket {socket_id} : {len(users)} userFills souscrits", flush=True)
                while time.monotonic() < deadline:
                    reste = max(0.0, deadline - time.monotonic())
                    try:
                        brut = await asyncio.wait_for(ws.recv(), timeout=min(10.0, reste or 1.0))
                    except asyncio.TimeoutError:
                        if time.monotonic() >= deadline:
                            return
                        # A23 : re-subscribe des users NON confirmes (subscribe perdu cote HL).
                        if time.monotonic() - t_check >= 12.0:
                            manquants = [connus[u] for u in connus if u not in acks]
                            if manquants:
                                lane.resubscribes += len(manquants)
                                print(f"[ws-lane] socket {socket_id} re-subscribe "
                                      f"{len(manquants)} non confirme(s)", flush=True)
                                await _souscrire(manquants)
                            t_check = time.monotonic()
                        continue
                    recv_mono_ns = time.monotonic_ns()
                    recv_wall_ms = int(time.time() * 1000)
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("channel") == "subscriptionResponse":
                        d = msg.get("data")
                        sub = d.get("subscription") if isinstance(d, dict) else None
                        if isinstance(sub, dict) and str(sub.get("user") or "").lower() in connus:
                            acks.add(str(sub.get("user")).lower())   # confirmation reelle
                        continue
                    data = msg.get("data")
                    if msg.get("channel") != "userFills" or not isinstance(data, dict):
                        continue
                    user = str(data.get("user") or "")
                    ucle = user.lower()
                    if ucle not in connus:
                        continue
                    parsed = parser_message_userfills(
                        msg, vault=user, received_at_ms=recv_wall_ms,
                        receive_mono_ns=recv_mono_ns, connection_id=connection_id,
                    )
                    if data.get("isSnapshot") is True or ucle not in lane.seeded:
                        # snapshot d'amorçage : fixe le high-water, n'émet rien de causal
                        lane.high_water[ucle] = high_water_snapshot(parsed, recv_wall_ms)
                        lane.seeded.add(ucle)
                        continue
                    nouveaux, hw = filtrer_forward(parsed, lane.high_water.get(ucle))
                    if hw is not None:
                        lane.high_water[ucle] = hw
                    await lane.emettre(nouveaux, observed_at_ms=recv_wall_ms)
        except Exception as exc:  # noqa: BLE001 (reconnexion résiliente)
            lane.reconnects += 1
            print(f"[ws-lane] socket {socket_id} reconnexion ({type(exc).__name__})", flush=True)
            await lane.gap_fill(users, now_ms=int(time.time() * 1000))
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


CLASSEMENT_ACTIFS = "config/leaders_actifs_classement.json"

#: Sous combien de fills PRÉVUS sur la fenêtre un leader déjà écouté est-il considéré
#: muet, et cède-t-il son slot ? Comparer à zéro ne marche pas : la prédiction est une
#: moyenne exponentielle, donc toujours strictement positive.
#:
#: MESURE DU 21/11/2026, qui encadre le seuil : un leader avec 2 fills dans la dernière
#: minute se prédit à **42,7** fills sur la fenêtre ; un leader muet depuis 50 h, à
#: **3,7e-91**. Les deux cas sont séparés de quatre-vingt-dix ordres de grandeur : tout
#: seuil entre les deux se comporte pareil. On prend donc une valeur volontairement
#: BASSE (moins d'un fill par jour) : elle ne démet que les leaders réellement morts, et
#: ne décide rien dans la zone grise — qui, elle, demanderait une mesure de terrain.
SEUIL_PREVU_MUET = 0.01


def charger_rangs(root: Path, chemin: str = CLASSEMENT_ACTIFS) -> dict[str, float]:
    """Scores d'activité mesurés par l'explorer : ``{vault_minuscule: score}``.

    Dictionnaire VIDE si le fichier manque ou est illisible — l'appelant doit alors le
    dire, pas faire semblant d'avoir classé.
    """
    try:
        data = json.loads((root / chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    actifs = data.get("actifs") if isinstance(data, dict) else None
    if not isinstance(actifs, list):
        return {}
    rangs: dict[str, float] = {}
    for entree in actifs:
        if not isinstance(entree, dict):
            continue
        vault = str(entree.get("vault") or "").strip().lower()
        score = entree.get("score")
        if vault and isinstance(score, (int, float)) and not isinstance(score, bool):
            rangs[vault] = float(score)
    return rangs


def historiques_recents(root: Path, chemin: Path | str | None = None, *,
                        limite_octets: int = 4_000_000, fenetre_ms: int = 6 * 3_600_000,
                        now_ms: int | None = None) -> dict[str, list[int]]:
    """Horodatages des fills récemment captés, par leader : ``{vault: [ts_ms, ...]}``.

    Lecture BORNÉE par la fin du ruban (``limite_octets``) : ce fichier atteint plusieurs
    gigaoctets sur le PC, et une sélection de slots ne doit jamais dépendre d'une lecture
    qui grandit sans fin. La première ligne lue est jetée — elle est presque toujours
    tronquée par la découpe en octets, et une ligne coupée n'est pas une mesure.

    Dictionnaire vide si le ruban n'existe pas (cas d'un runner GitHub, qui démarre sans
    historique) : l'appelant garde alors le classement global, sans rien inventer.
    """
    tape = Path(chemin) if chemin else (root / OUT_DEFAUT)
    if not tape.is_absolute():
        tape = root / tape
    try:
        taille = tape.stat().st_size
    except OSError:
        return {}
    borne = int(now_ms if now_ms is not None else time.time() * 1000) - int(fenetre_ms)
    out: dict[str, list[int]] = {}
    try:
        with tape.open("rb") as flux:
            if taille > limite_octets:
                flux.seek(taille - limite_octets)
                flux.readline()         # ligne tronquee par la decoupe : jetee
            for brut in flux:
                try:
                    enregistrement = json.loads(brut.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if not isinstance(enregistrement, dict):
                    continue
                vault = str(enregistrement.get("vault") or enregistrement.get("user") or "").strip()
                ts = enregistrement.get("ts_ms")
                if not vault or not isinstance(ts, int) or isinstance(ts, bool):
                    continue
                if ts < borne:
                    continue
                out.setdefault(vault.lower(), []).append(ts)
    except OSError:
        return {}
    return out


def choisir_les_slots(tous: list[str], rangs: dict[str, float], *, slots: int,
                      shard_count: int = 1, shard_index: int = 0,
                      challengers: int = 2,
                      historiques: dict[str, list[int]] | None = None,
                      now_ms: int | None = None) -> dict[str, Any]:
    """Les ``slots`` leaders qui méritent les abonnements rares de CETTE lane.

    DÉFAUT CORRIGÉ LE 21/11/2026. La lane faisait ``shard_leaders(...)[:10]`` : elle
    découpait les leaders par ``i % nb_lanes`` — donc dans l'ordre du fichier — puis
    gardait les dix premiers de sa tranche. Avec 120 leaders suivis et 4 lanes, chacune
    recevait ~30 candidats arbitraires, en jetait 20, et personne ne regardait jamais
    lesquels produisent des fills. Deux modules du dépôt, livrés et testés, n'étaient
    appelés par AUCUN code de production : ``orchestrateur_lanes`` et
    ``subscription_universe``.

    Ce qui est fait ici, et pourquoi c'est mieux qu'un classement par tranche :

    * ``orchestrer`` attribue les ``nb_lanes × slots`` MEILLEURS leaders du classement
      GLOBAL, en tourniquet par rang (lane = rang % nb_lanes). L'union des lanes couvre
      donc le top 40 réel, et non le meilleur de quatre tranches arbitraires — à nombre
      de slots égal, ce sont les leaders les plus actifs qui sont écoutés ;
    * les lanes restent DISJOINTES par construction (une assignation par leader) ;
    * un leader dont le score n'est pas strictement positif ne prend pas de slot WS : il
      retombe sur le poll, qui n'a pas le quota de 10/IP ;
    * ``challengers`` slots sont réservés à l'EXPLORATION (UCB1) parmi les leaders que
      cette lane n'aurait pas écoutés — un classement a toujours un âge, et sans
      exploration un leader devenu actif depuis resterait invisible pour toujours ;
    * sans classement lisible, l'ancien découpage est conservé **et déclaré**
      (``source_rang``), jamais déguisé en choix éclairé.
    """
    slots = max(1, int(slots))
    shard_count = max(1, int(shard_count))
    tous = [c for c in tous if c]
    if not tous:
        return {"retenus": [], "core": [], "challengers": [], "source_rang": "aucun candidat",
                "classes": 0, "candidats": 0, "non_couverts": 0,
                "demis_sans_activite": []}
    if not rangs:
        tranche = shard_leaders(tous, shard_count, shard_index)
        return {"retenus": tranche[:slots], "core": tranche[:slots], "challengers": [],
                "source_rang": "absent : decoupage par ordre du fichier conserve",
                "classes": 0, "candidats": len(tranche), "non_couverts": 0,
                "demis_sans_activite": []}

    # Demotion par PREDICTION locale (`activite_predictive`), et seulement en demotion.
    #
    # POURQUOI PAS EN PROMOTION. Classer les leaders par les fills qu'on a deja captes
    # reviendrait a nourrir le signal avec sa propre selection : les leaders deja ecoutes
    # auraient un historique, les autres non, et les slots se figeraient sur eux pour
    # toujours. La prediction ne sert donc QUE a liberer un slot : un leader qu'on ecoute
    # et dont la fenetre a venir est prevue VIDE cede sa place -- le classement global
    # garde la main sur qui monte, l'observation locale decide seulement qui descend.
    demis: list[str] = []
    if historiques:
        maintenant = int(now_ms if now_ms is not None else time.time() * 1000)
        prevus = dict(classer_leaders(historiques, now_ms=maintenant))
        observes = {k.lower() for k in historiques}
        for leader in tous:
            if leader.lower() not in observes:
                continue
            prevu = float(prevus.get(leader, prevus.get(leader.lower(), 0.0)))
            if prevu < SEUIL_PREVU_MUET:
                demis.append(leader)
    demis_bas = {d.lower() for d in demis}
    classement = sorted(
        ((c, -1.0 if c.lower() in demis_bas else float(rangs.get(c.lower(), 0.0)))
         for c in tous),
        key=lambda p: (-p[1], p[0].lower()))
    n_chall = max(0, min(int(challengers), slots - 1))
    plan = orchestrer(classement, lanes_ws=shard_count, slots_par_lane=slots)
    # `leaders_par_lane` rend la liste TRIEE PAR NOM : tronquer dessus jetterait par
    # ordre alphabetique et non par rang. On remet l'ordre du classement avant de couper
    # (defaut trouve par le test, pas par relecture).
    rang_de = {leader: position for position, (leader, _) in enumerate(classement)}
    lane_ws = sorted(leaders_par_lane(plan, int(shard_index)),
                     key=lambda leader: rang_de.get(leader, len(classement)))
    core = lane_ws[: slots - n_chall]

    # Exploration : parmi ceux que le classement n'a PAS retenus pour le WS, et seulement
    # la part qui revient a cette lane -- deux lanes ne doivent pas tirer le meme leader.
    hors_ws = [leader for leader, a in plan["assignations"].items() if a.get("source") != "ws"]
    hors_ws += list(plan.get("non_couverts") or ())
    a_explorer = shard_leaders(sorted(set(hors_ws)), shard_count, int(shard_index))
    stats = {c: {"fills_recents": 0, "fenetre_min": 1.0} for c in a_explorer}
    tires = (selectionner_challengers_ucb(a_explorer, stats, slots=n_chall)
             if n_chall and a_explorer else [])

    retenus = list(core) + [c for c in tires if c not in set(core)]
    if len(retenus) < slots:
        for leader in lane_ws:
            if leader not in set(retenus):
                retenus.append(leader)
            if len(retenus) >= slots:
                break
    return {"retenus": retenus[:slots], "core": list(core), "challengers": list(tires),
            "source_rang": CLASSEMENT_ACTIFS,
            "classes": sum(1 for _, s in classement if s > 0.0),
            "candidats": len(tous),
            "non_couverts": len(plan.get("non_couverts") or ()),
            "demis_sans_activite": sorted(demis)}


async def _boucle(args: argparse.Namespace) -> int:
    root = Path(args.root)
    tous = _charger_leaders(root, args.leaders_file)
    # Le classement est GLOBAL : la lane donne sa position, pas une tranche deja decoupee.
    choix = choisir_les_slots(tous, charger_rangs(root),
                              slots=max(1, int(args.max_users)),
                              shard_count=int(args.shard_count),
                              shard_index=int(args.shard_index),
                              historiques=historiques_recents(root))
    lane_leaders = choix["retenus"]
    if not lane_leaders:
        print("[ws-lane] aucun leader pour cette lane.", flush=True)
        return 0
    print(f"[ws-lane] slots : {len(choix['core'])} CORE + {len(choix['challengers'])} "
          f"challenger(s) sur {choix['candidats']} leader(s), {choix['classes']} classe(s), "
          f"{choix['non_couverts']} non couvert(s), rang = {choix['source_rang']}", flush=True)
    out = Path(args.out) if args.out else (root / OUT_DEFAUT)
    lane = LaneWS(out if out.is_absolute() else root / out)
    # groupes de ≤ subs-par-connexion users = une connexion WS chacun
    pas = max(1, int(args.subs_par_connexion))
    groupes = [lane_leaders[i:i + pas] for i in range(0, len(lane_leaders), pas)]
    deadline = time.monotonic() + max(10.0, float(args.duree_s))
    print(f"[ws-lane] lane {args.shard_index}/{args.shard_count} : {len(lane_leaders)} leaders "
          f"sur {len(groupes)} connexion(s), {int(args.duree_s)}s.", flush=True)
    taches = [asyncio.create_task(_connexion(lane, grp, chr(65 + i), deadline))
              for i, grp in enumerate(groupes)]
    await asyncio.gather(*taches, return_exceptions=True)
    print(f"[ws-lane] fini : {lane.emis} fills LIVE_WS emis, {lane.gapfills} par gap-fill, "
          f"{lane.reconnects} reconnexions, {lane.resubscribes} re-subscribes -> {lane.out_path}", flush=True)
    # B29 : sante JSON de la lane (metriques, sans changer l'affichage console).
    try:
        sante = {"lane": f"{args.shard_index}/{args.shard_count}", "leaders": len(lane_leaders),
                 "fills_emis": lane.emis, "gapfills": lane.gapfills,
                 "reconnects": lane.reconnects, "resubscribes": lane.resubscribes,
                 # Choix des slots RENDU : un classement absent ou perime doit se VOIR,
                 # pas se deviner en comparant des listes de leaders a la main.
                 "slots_core": choix["core"], "slots_challengers": choix["challengers"],
                 "slots_candidats": choix["candidats"], "slots_classes": choix["classes"],
                 "slots_source_rang": choix["source_rang"],
                 "slots_non_couverts": choix["non_couverts"],
                 "slots_demis_sans_activite": choix["demis_sans_activite"],
                 "genere_ms": int(time.time() * 1000)}
        (lane.out_path.parent / f"ws_lane_sante_{args.shard_index}.json").write_text(
            json.dumps(sante, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur WS userFills léger pour lane multi-IP (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--leaders-file", default=DEFAULT_LEADERS_FILE)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--max-users", type=int, default=MAX_USERS_IP)
    p.add_argument("--subs-par-connexion", type=int, default=SUBS_PAR_CONNEXION)
    p.add_argument("--duree-s", type=float, default=1500.0)
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    try:
        return asyncio.run(_boucle(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
