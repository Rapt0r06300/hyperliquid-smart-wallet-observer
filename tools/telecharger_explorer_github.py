"""AlinaSync — télécharge le feed explorer des jobs GitHub (workflow explorer-collecte)
et fusionne dans runtime/data/explorer_tx_tape.jsonl (dédup par hash). PAPER / lecture
seule. FAIL-SOFT : jamais d'échec bloquant.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

from telecharger_fills_lanes_github import _gh_reel, gh_disponible, telecharger_runs  # noqa: E402

WORKFLOW = "explorer-collecte.yml"
CIBLE = Path("runtime") / "data" / "explorer_tx_tape.jsonl"
MOTIF = "explorer_tx_tape.jsonl"


def _lire_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    return rows


def fusionner_explorer(root: Path, artefacts: Path) -> dict:
    cible = root / CIBLE
    sources = ([cible] if cible.exists() else []) + sorted(
        p for p in artefacts.rglob(MOTIF) if p.resolve() != cible.resolve())
    par_hash: dict[str, dict] = {}
    sans_hash: list[dict] = []
    entrees = 0
    for src in sources:
        for row in _lire_jsonl(src):
            entrees += 1
            h = row.get("hash")
            if isinstance(h, str) and h:
                par_hash.setdefault(h, row)
            else:
                sans_hash.append(row)
    fusionnes = sorted(par_hash.values(),
                       key=lambda r: (int(r.get("time") or 0), str(r.get("hash")))) + sans_hash
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_suffix(".jsonl.fusion.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in fusionnes:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    if cible.exists():
        bak = cible.with_suffix(".jsonl.avant-fusion.bak")
        if bak.exists():
            bak.unlink()
        cible.rename(bak)
    tmp.rename(cible)
    return {"entrees": entrees, "doublons_retires": max(0, entrees - len(fusionnes)),
            "total_final": len(fusionnes)}


def _lister_runs(gh, cwd: Path, limite: int) -> list[str]:
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


def telecharger_et_fusionner(root: Path, *, gh=_gh_reel, limite_runs: int = 3) -> dict:
    if not gh_disponible(gh, cwd=root):
        return {"statut": "gh_indisponible", "runs": 0, "fusion": None}
    run_ids = _lister_runs(gh, root, limite_runs)
    if not run_ids:
        return {"statut": "aucun_run", "runs": 0, "fusion": None}
    tmp = Path(tempfile.mkdtemp(prefix="alina_explorer_"))
    try:
        telecharges = telecharger_runs(gh, root, run_ids, tmp)
        if telecharges == 0:
            return {"statut": "telechargement_vide", "runs": 0, "fusion": None}
        return {"statut": "OK", "runs": telecharges, "fusion": fusionner_explorer(root, tmp)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Telecharge+fusionne le feed explorer GitHub (AlinaSync).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--runs", type=int, default=3)
    args = p.parse_args(argv)
    res = telecharger_et_fusionner(Path(args.root), limite_runs=max(1, args.runs))
    if res["statut"] != "OK":
        print(f"[explorer] {res['statut']} -> rien a fusionner (non bloquant).", flush=True)
        return 0
    f = res["fusion"]
    print(f"[explorer] {res['runs']} run(s) ; total final {f['total_final']} tx "
          f"(doublons {f['doublons_retires']}).", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
