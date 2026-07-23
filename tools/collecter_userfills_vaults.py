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
from hl_observer.experimental import cohortes as CO  # noqa: E402

WS_URL = "wss://api.hyperliquid.xyz/ws"
FILLS_LIVE = Path("runtime") / "data" / "vault_fills_live.jsonl"
CURSEURS = Path("runtime") / "data" / "userfills_curseurs.json"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
FILE_MAX = 2000                  # file bornée : si saturée, on drop (on ne bloque JAMAIS la reception WS)


def vaults_suivis(root: Path, *, n: int = 8) -> list[str]:
    """CORE + CHALLENGERS réellement abonnés (deny-by-default). On complète progressivement jusqu'à
    2 CORE + 6 CHALLENGERS À MESURE qu'ils passent la barre de sécurité — jamais tout-venant."""
    from hl_observer.experimental.exploratoire import tiers
    core, chal = tiers(root)
    return sorted(core) + sorted(chal)[: max(0, n - len(core))]


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


def _traiter_un(root: Path, fill: dict, coins_a_verifier: set) -> None:
    with (root / FILLS_LIVE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(fill, ensure_ascii=False) + "\n")
    coins_a_verifier.add(fill.get("coin"))
    for nom, coh in CO.COHORTES.items():
        r = CO.traiter_fill(coh, ETATS[nom], fill, root)
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


async def _boucle(root: Path) -> None:
    for nom, coh in CO.COHORTES.items():
        ETATS[nom] = CO.etat_initial(coh, root)
    vaults = vaults_suivis(root)
    if not vaults:
        print("[userfills] aucun vault suivi (deny-by-default) — rien a faire", flush=True)
        return
    (root / FILLS_LIVE).parent.mkdir(parents=True, exist_ok=True)
    print("[userfills] VAULTS ABONNES (%d) : %s" % (len(vaults), ", ".join(v[:10] for v in vaults)), flush=True)
    file: asyncio.Queue = asyncio.Queue(maxsize=FILE_MAX)
    await asyncio.gather(_worker(root, file), _exits_periodiques(root),
                         *[_un_vault(root, v, file) for v in vaults])


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
