"""AlinaSync — télécharge les fills LIVE_WS des lanes GitHub (workflow
userfills-live-lanes) et les fusionne dans runtime/data/vault_fills_live.jsonl.

Miroir de ``telecharger_fills_lanes_github.py`` (poll), mais pour le flux WS :
workflow ``userfills-live-lanes.yml`` → artefacts ``ws-fills-shard-*`` (fichiers
``vault_fills_ws_lane.jsonl``) → cible ``vault_fills_live.jsonl``. Dédup + gate de
fraîcheur identiques (``fusionner``). PAPER / lecture seule.

FAIL-SOFT : si ``gh`` est absent/non authentifié ou qu'aucun run n'est trouvé, on
log et on rend 0 — jamais d'échec bloquant pour AlinaSync.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from fusionner_fills_lanes import fusionner  # noqa: E402
from telecharger_fills_lanes_github import (  # noqa: E402 (réutilise la plomberie gh)
    _gh_reel, gh_disponible, lister_runs_reussis as _lister_generic, telecharger_runs,
)

WORKFLOW = "userfills-live-lanes.yml"
CIBLE_WS = Path("runtime") / "data" / "vault_fills_live.jsonl"
MOTIF_WS = "vault_fills_ws_lane.jsonl"


def lister_runs_reussis(gh, cwd: Path, limite: int) -> list[str]:
    # même logique que le poll, mais sur le workflow WS.
    import json
    res = gh(["run", "list", "--workflow", WORKFLOW, "-L", str(max(1, limite * 3)),
              "--json", "databaseId,status,conclusion"], cwd)
    if res.returncode != 0:
        return []
    try:
        runs = json.loads(res.stdout or "[]")
    except (ValueError, TypeError):
        return []
    ids: list[str] = []
    for r in runs if isinstance(runs, list) else []:
        if r.get("status") == "completed" and r.get("conclusion") == "success":
            ids.append(str(r.get("databaseId")))
        if len(ids) >= limite:
            break
    return ids


def telecharger_et_fusionner(root: Path, *, gh=_gh_reel, limite_runs: int = 3,
                             max_lag_ms: int = 600_000) -> dict:
    if not gh_disponible(gh, cwd=root):
        return {"statut": "gh_indisponible", "runs": 0, "fusion": None}
    run_ids = lister_runs_reussis(gh, root, limite_runs)
    if not run_ids:
        return {"statut": "aucun_run", "runs": 0, "fusion": None}
    tmp = Path(tempfile.mkdtemp(prefix="alina_ws_lanes_"))
    try:
        telecharges = telecharger_runs(gh, root, run_ids, tmp)
        if telecharges == 0:
            return {"statut": "telechargement_vide", "runs": 0, "fusion": None}
        rapport = fusionner(root, tmp, max_lag_ms, cible_rel=CIBLE_WS, motif=MOTIF_WS)
        return {"statut": "OK", "runs": telecharges, "fusion": rapport}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Telecharge+fusionne les fills LIVE_WS des lanes GitHub (AlinaSync).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--max-lag-ms", type=int, default=600_000)
    args = p.parse_args(argv)
    res = telecharger_et_fusionner(Path(args.root), limite_runs=max(1, args.runs),
                                   max_lag_ms=max(0, args.max_lag_ms))
    if res["statut"] == "gh_indisponible":
        print("[ws-lanes] gh indisponible/non authentifie -> fills WS non rapatries (non bloquant).", flush=True)
        return 0
    if res["statut"] == "aucun_run":
        print("[ws-lanes] aucun run reussi du workflow userfills-live-lanes -> rien a fusionner.", flush=True)
        return 0
    if res["statut"] == "telechargement_vide":
        print("[ws-lanes] aucun artefact telecharge (expires ?) -> rien a fusionner.", flush=True)
        return 0
    f = res["fusion"]
    print(f"[ws-lanes] {res['runs']} run(s) GitHub rapatrie(s) ; total final {f['total_final']} fills "
          f"LIVE_WS (doublons {f['doublons_retires']}, rejets qualite {f['rejets_qualite']}).", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
