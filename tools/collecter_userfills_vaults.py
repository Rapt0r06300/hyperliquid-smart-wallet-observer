"""MOTEUR WS userFills INLINE (rectif Flo 23/07) — ouvre dans le MÊME flux que le fill.

S'abonne au WS `userFills` des vaults CORE+CHALLENGERS et, DÈS chaque fill, appelle
`cohortes.traiter_fill` pour les DEUX cohortes (ALPHA stricte + DISCOVERY_PROBE) : dédup isSnapshot/hash,
agrégation des OPEN/ADD en dollars, admission → L2<1s → coûts → edge net>0 → OUVERTURE paper immédiate,
avec mesure de la latence fill→copie. Les REDUCE/CLOSE du leader sortent inline. Une tâche périodique
gère les sorties prix/temps (stop calibré / take-profit / horizon), écrit les statuts, et l'auto-KILL
d'une cohorte à expectancy live négative. Lecture seule ; 0 ordre, 0 clé, 0 signature.
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
SCORES = Path("runtime") / "data" / "vaults_scores.json"


def vaults_suivis(root: Path, *, n: int = 8) -> list[str]:
    """CORE + CHALLENGERS (deny-by-default : sans score, aucun vault donc aucun abonnement)."""
    try:
        d = json.loads((root / SCORES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    core = [c["vault"] for c in (d.get("classement") or []) if c.get("retenu")][:2]
    autres = [c["vault"] for c in (d.get("classement") or []) if not c.get("retenu")][: n - len(core)]
    return core + autres


ETATS = {}  # {cohorte_nom: etat} — partagé entre les tâches vault (asyncio mono-thread : pas de course réelle)


def _traiter(root: Path, fills: list[dict]) -> None:
    for x in fills:
        with (root / FILLS_LIVE).open("a", encoding="utf-8") as f:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    for x in fills:
        for nom, coh in CO.COHORTES.items():
            r = CO.traiter_fill(coh, ETATS[nom], x, root)
            if r and r.get("ouverture"):
                print("[userfills] %s OUVRE %s @ %.4f latence=%dms (fill %s)"
                      % (nom, r["ouverture"]["coin"], r["ouverture"]["prix_entree"], r.get("latence_ms", 0),
                         x.get("vault", "")[:10]), flush=True)
            elif r and r.get("fermeture"):
                print("[userfills] %s FERME %s (%s) pnl=%.4f$"
                      % (nom, r["fermeture"]["coin"], r["fermeture"]["raison"], r["fermeture"]["realized_usd"]), flush=True)


async def _un_vault(root: Path, vault: str) -> None:
    import websockets
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, max_size=2 ** 22) as ws:
                await ws.send(json.dumps({"method": "subscribe",
                                          "subscription": {"type": "userFills", "user": vault}}))
                async for brut in ws:
                    try:
                        msg = json.loads(brut)
                    except ValueError:
                        continue
                    fills = UL.parser_message_userfills(msg, vault=vault)
                    if fills:
                        _traiter(root, fills)
        except Exception as exc:  # noqa: BLE001 — reconnect, on ne meurt pas
            print("[userfills] %s reconnect (%s)" % (vault[:10], str(exc)[:50]), flush=True)
            await asyncio.sleep(3.0)


async def _exits_periodiques(root: Path, *, intervalle_s: float = 10.0) -> None:
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
    print("[userfills] userFills WS de %d vaults -> 2 cohortes inline (ALPHA + PROBE)" % len(vaults), flush=True)
    await asyncio.gather(_exits_periodiques(root), *[_un_vault(root, v) for v in vaults])


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
