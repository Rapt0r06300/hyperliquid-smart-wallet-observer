"""AlinaSync — télécharge les fills des lanes GitHub (workflow copy-vault-poll-lanes)
et les fusionne dans runtime/data/vault_fills_poll.jsonl.

Utilise la CLI ``gh`` (déjà utilisée par le projet) pour lister les runs réussis
puis télécharger leurs artefacts (poll-fills-shard-*). La fusion applique la
dédup + le gate de fraîcheur (via fusionner_fills_lanes). PAPER / lecture seule.

FAIL-SOFT : si ``gh`` est absent/non authentifié ou qu'aucun run n'est trouvé,
on log et on rend 0 — jamais d'échec bloquant pour AlinaSync.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from fusionner_fills_lanes import fusionner  # noqa: E402

WORKFLOW = "copy-vault-poll-lanes.yml"


def _gh_reel(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )


def gh_disponible(gh=_gh_reel, *, cwd: Path = RACINE) -> bool:
    try:
        res = gh(["--version"], cwd)
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0


def lister_runs_reussis(gh, cwd: Path, limite: int) -> list[str]:
    """IDs des derniers runs TERMINÉS AVEC SUCCÈS du workflow de lanes."""
    res = gh([
        "run", "list", "--workflow", WORKFLOW, "-L", str(max(1, limite * 3)),
        "--json", "databaseId,status,conclusion",
    ], cwd)
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


def telecharger_runs(gh, cwd: Path, run_ids: list[str], dest: Path) -> int:
    """Télécharge les artefacts de chaque run dans dest/run-<id>/. Renvoie le nb OK."""
    ok = 0
    for rid in run_ids:
        cible = dest / f"run-{rid}"
        cible.mkdir(parents=True, exist_ok=True)
        res = gh(["run", "download", rid, "-D", str(cible)], cwd)
        if res.returncode == 0:
            ok += 1
    return ok


def telecharger_et_fusionner(
    root: Path, *, gh=_gh_reel, limite_runs: int = 3, max_lag_ms: int = 600_000,
) -> dict:
    if not gh_disponible(gh, cwd=root):
        return {"statut": "gh_indisponible", "runs": 0, "fusion": None}
    run_ids = lister_runs_reussis(gh, root, limite_runs)
    if not run_ids:
        return {"statut": "aucun_run", "runs": 0, "fusion": None}
    tmp = Path(tempfile.mkdtemp(prefix="alina_lanes_"))
    try:
        telecharges = telecharger_runs(gh, root, run_ids, tmp)
        if telecharges == 0:
            return {"statut": "telechargement_vide", "runs": 0, "fusion": None}
        rapport = fusionner(root, tmp, max_lag_ms)
        return {"statut": "OK", "runs": telecharges, "fusion": rapport}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Telecharge+fusionne les fills des lanes GitHub (AlinaSync).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--runs", type=int, default=3, help="nb de runs recents a rapatrier")
    p.add_argument("--max-lag-ms", type=int, default=600_000)
    args = p.parse_args(argv)
    res = telecharger_et_fusionner(
        Path(args.root), limite_runs=max(1, args.runs), max_lag_ms=max(0, args.max_lag_ms))
    if res["statut"] == "gh_indisponible":
        print("[lanes] gh indisponible/non authentifie -> fills GitHub non rapatries (non bloquant).", flush=True)
        return 0
    if res["statut"] == "aucun_run":
        print("[lanes] aucun run reussi du workflow copy-vault-poll-lanes -> rien a fusionner.", flush=True)
        return 0
    if res["statut"] == "telechargement_vide":
        print("[lanes] aucun artefact telecharge (expires ?) -> rien a fusionner.", flush=True)
        return 0
    f = res["fusion"]
    print(f"[lanes] {res['runs']} run(s) GitHub rapatrie(s) ; "
          f"total final {f['total_final']} fills "
          f"(doublons {f['doublons_retires']}, rejets qualite {f['rejets_qualite']}).", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
