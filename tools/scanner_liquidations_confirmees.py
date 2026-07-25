"""SCANNER LIQUIDATIONS CONFIRMÉES (25/07) — backfill BORNÉ `userFillsByTime` sur les utilisateurs DÉJÀ
suivis, filtre les fills avec `liquidation` non-null = REAL_LIQUIDATION (jamais un proxy mark/oracle).

Réutilise l'EXISTANT : `backfill_vault_fills._post_userfills` (endpoint public, brut → préserve liquidation),
`collecte_fiable.Limiteur` (budget REST + backoff), `vault_fills_backfill.plan_de_requetes` (pagination),
et le parseur WS `userfills_live` (préservation du champ) → EXACTEMENT la même extraction que le live.
AUCUN nouvel utilisateur. Plafond dur de requêtes. LECTURE SEULE. 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.collection import collecte_fiable as CF   # noqa: E402
from hl_observer.collection import userfills_live as UL     # noqa: E402
from hl_observer.collection import vault_fills_backfill as VB  # noqa: E402
import backfill_vault_fills as BF                           # noqa: E402  (réutilise _post_userfills, SUIVIS, vaults_cibles)

LIQ_CONFIRMEES = Path("runtime") / "data" / "liquidations_confirmees.jsonl"
RESUME = Path("runtime") / "data" / "liquidations_confirmees_resume.json"
LOOKBACK_J_DEFAUT = 30
MAX_REQ_DEFAUT = 300                                        # plafond DUR de requêtes (budget borné)


def _fills_bruts(reponse: Any) -> list:
    """userFillsByTime rend soit une liste de fills, soit {fills:[...]}. Tolérant."""
    if isinstance(reponse, list):
        return reponse
    if isinstance(reponse, dict):
        return reponse.get("fills") or []
    return []


def confirmees_depuis_reponse(reponse: Any, vault: str) -> list[dict]:
    """Liquidations CONFIRMÉES d'une réponse brute. Réutilise le parseur WS (préservation `liquidation`) +
    `liquidations_confirmees` → cohérence stricte live/backfill. Pur, sans réseau."""
    parsed = UL.parser_message_userfills({"data": {"fills": _fills_bruts(reponse)}}, vault=vault)
    return UL.liquidations_confirmees(parsed)


def users_suivis(root: Path) -> list[str]:
    """Les utilisateurs DÉJÀ suivis (aucun nouveau). Source : vaults_suivis.json ; repli sur retenus scorés."""
    try:
        d = json.loads((root / BF.SUIVIS).read_text(encoding="utf-8"))
        xs = d if isinstance(d, list) else (
            (d.get("vaults") or d.get("suivis") or d.get("users") or list(d.keys())) if isinstance(d, dict) else [])
        xs = [str(x) for x in xs if isinstance(x, str) and x.startswith("0x")]
        if xs:
            return xs
    except (OSError, ValueError):
        pass
    retenus, _ = BF.vaults_cibles(root)
    return retenus


def scanner(root: Path, *, lookback_j: int = LOOKBACK_J_DEFAUT, poster=None, limiteur=None,
            max_req: int = MAX_REQ_DEFAUT) -> dict:
    """Boucle bornée : pour chaque user suivi, pagine userFillsByTime (budget CF.Limiteur), filtre
    liquidation!=null. Écrit LIQ_CONFIRMEES (append) + un résumé. Rend le résumé (avec les records)."""
    poster = poster or BF._post_userfills
    lim = limiteur or CF.Limiteur(0.2)
    users = users_suivis(root)
    fin = int(time.time() * 1000)
    debut = fin - lookback_j * 24 * VB.MS_PAR_HEURE
    resume: dict = {"ts_ms": fin, "lookback_j": lookback_j, "n_users": len(users),
                    "users": [u[:10] for u in users], "n_requetes": 0, "n_fills_scannes": 0,
                    "n_confirmees": 0, "par_user": {}, "confirmees": []}
    reqs = 0
    stop = False
    for u in users:
        resume["par_user"].setdefault(u[:10], 0)
        if stop:
            continue
        for a, b in VB.plan_de_requetes(debut, fin):
            if reqs >= max_req:
                stop = True
                break
            lim.attente()
            reqs += 1
            try:
                rep = poster(u, a, b)
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                continue
            resume["n_fills_scannes"] += len(_fills_bruts(rep))
            conf = confirmees_depuis_reponse(rep, u)
            resume["par_user"][u[:10]] += len(conf)
            resume["confirmees"].extend(conf)
    resume["n_requetes"] = reqs
    resume["n_confirmees"] = len(resume["confirmees"])
    (root / RESUME).parent.mkdir(parents=True, exist_ok=True)
    if resume["confirmees"]:
        with (root / LIQ_CONFIRMEES).open("a", encoding="utf-8") as f:
            for r in resume["confirmees"]:
                # PROVENANCE HONNÊTE (25/07) : trouvé APRÈS coup par REST -> REST_BACKFILL = descriptif/OOS,
                # jamais causal (ne peut pas déclencher une position rétroactive). Cf. liquidation_sentinels.est_causal.
                f.write(json.dumps({**r, "backfill": True, "source": "REST_BACKFILL", "recu_ms": fin},
                                   ensure_ascii=False) + "\n")
    (root / RESUME).write_text(json.dumps({k: v for k, v in resume.items() if k != "confirmees"},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    return resume


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scanner liquidations confirmées (userFillsByTime, lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--lookback-j", type=int, default=LOOKBACK_J_DEFAUT)
    p.add_argument("--max-req", type=int, default=MAX_REQ_DEFAUT)
    a = p.parse_args(argv)
    r = scanner(Path(a.root), lookback_j=a.lookback_j, max_req=a.max_req)
    print("[liq-confirmees] users=%d requetes=%d fills_scannes=%d -> CONFIRMEES=%d" % (
        r["n_users"], r["n_requetes"], r["n_fills_scannes"], r["n_confirmees"]), flush=True)
    if r["n_confirmees"] == 0:
        print("[liq-confirmees] AUCUNE_DONNEE_CONFIRMEE (0 fill.liquidation sur %d users suivis, fenetre %d j)"
              % (r["n_users"], a.lookback_j), flush=True)
    else:
        for u, n in r["par_user"].items():
            if n:
                print("  %s : %d liquidations confirmees" % (u, n), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
