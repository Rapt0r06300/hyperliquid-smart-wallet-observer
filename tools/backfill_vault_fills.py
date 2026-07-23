"""BACKFILL userFillsByTime des vaults RETENUS + groupe TÉMOIN (rectif Flo 23/07) — LECTURE SEULE.

Ne pas attendre plusieurs jours : on backfill l'HISTORIQUE public des fills de chaque vault retenu
(et d'un groupe témoin, pour le placebo/contrôle), on reconstruit les épisodes OPEN/ADD/REDUCE/CLOSE,
on exclut les réductions de RETRAIT (pro-rata multi-coins), et on écrit fills + épisodes + couverture.
Le module `vault_fills_backfill` fait le travail pur ; ici on ne fait que la boucle réseau (bornée,
polie, dédupliquée). Un seul endpoint PUBLIC `userFillsByTime`. 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import collecte_fiable as CF  # noqa: E402
from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402

URL_HL = "https://api.hyperliquid.xyz/info"
SCORES = Path("runtime") / "data" / "vaults_scores.json"
SUIVIS = Path("runtime") / "data" / "vaults_suivis.json"
OUT_FILLS = Path("runtime") / "data" / "vault_fills.jsonl"
OUT_EPISODES = Path("runtime") / "data" / "vault_episodes.jsonl"
OUT_COUVERTURE = Path("runtime") / "data" / "vault_fills_couverture.json"
LOOKBACK_J_DEFAUT = 14


def _post_userfills(vault: str, start_ms: int, end_ms: int, *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps({"type": "userFillsByTime", "user": vault,
                        "startTime": int(start_ms), "endTime": int(end_ms)}).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def vaults_cibles(root: Path, *, n_temoin: int = 10) -> tuple[list[str], list[str]]:
    """(retenus, témoins). Retenus = vaults_scores.retenus. Témoins = vaults NON retenus du classement
    (groupe de contrôle pour le placebo). Si pas de score, retenus vide (deny-by-default)."""
    retenus: list[str] = []
    temoin: list[str] = []
    try:
        d = json.loads((root / SCORES).read_text(encoding="utf-8"))
        retenus = [str(a) for a in (d.get("retenus") or [])]
        for c in (d.get("classement") or []):
            if not c.get("retenu") and len(temoin) < n_temoin:
                temoin.append(str(c["vault"]))
    except (OSError, ValueError):
        pass
    return retenus, temoin


def backfill_un_vault(root: Path, vault: str, *, lookback_j: int, limiteur: CF.Limiteur,
                      poster=_post_userfills) -> list[dict]:
    """Backfill paginé d'UN vault → fills propres (parsés + dédupliqués). Réseau borné + backoff géré."""
    fin = int(time.time() * 1000)
    debut = fin - lookback_j * 24 * VB.MS_PAR_HEURE
    brut: list[dict] = []
    for a, b in VB.plan_de_requetes(debut, fin):
        limiteur.attente()
        try:
            rep = poster(vault, a, b)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue
        brut.extend(VB.parser_fills(rep, vault=vault))
    return VB.dedupliquer(brut)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill userFillsByTime des vaults (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--lookback-j", type=int, default=LOOKBACK_J_DEFAUT)
    p.add_argument("--une-fois", action="store_true", default=True)
    a = p.parse_args(argv)
    root = Path(a.root)
    retenus, temoin = vaults_cibles(root)
    if not retenus:
        print("[backfill-fills] aucun vault retenu (deny-by-default) — rien a backfiller", flush=True)
        return 0
    limiteur = CF.Limiteur(0.2)
    tous_fills: list[dict] = []
    for grp, vaults in (("RETENU", retenus), ("TEMOIN", temoin)):
        for v in vaults:
            fills = backfill_un_vault(root, v, lookback_j=a.lookback_j, limiteur=limiteur)
            for f in fills:
                f["groupe"] = grp
            tous_fills.extend(fills)
            print("[backfill-fills] %s %s : %d fills" % (grp, v[:10], len(fills)), flush=True)
    episodes = VB.marquer_retraits(VB.reconstruire_episodes(tous_fills))
    (root / OUT_FILLS).write_text("\n".join(json.dumps(f, ensure_ascii=False) for f in tous_fills), encoding="utf-8")
    (root / OUT_EPISODES).write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in episodes), encoding="utf-8")
    cov = VB.couverture(tous_fills)
    cov["n_episodes"] = len(episodes)
    cov["n_entrees_alpha"] = len(VB.entrees_alpha(episodes))
    (root / OUT_COUVERTURE).write_text(json.dumps(cov, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[backfill-fills] couverture: %d fills, %.1f h, %d coins, %d episodes, %d entrees alpha"
          % (cov["n_fills"], cov["span_h"], len(cov["coins"]), cov["n_episodes"], cov["n_entrees_alpha"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
