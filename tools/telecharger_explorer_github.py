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
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.collection.collecte_fiable import ajouter_atomique  # noqa: E402
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


# 26/11/2026 -- AJOUT SEUL, JAMAIS DE REECRITURE DU RUBAN VIVANT. Cette fusion reecrivait le ruban local (tri +
# renommage) pendant que son collecteur l'alimentait. Mesure le 26/11 a 04:13 : `WinError 32` (le ruban etait ouvert
# par un autre processus), et meme quand le renommage passait, les lignes ajoutees par le collecteur pendant la
# fusion partaient dans le `.bak`, efface a la fusion suivante ; les lecteurs par decalage (explorer_autonome) et le
# scelleur (suivi par prefixe) voyaient un fichier change sous eux. Desormais : le ruban local n'est QUE lu, les
# lignes des lanes absentes sont AJOUTEES par `ajouter_atomique` (une ecriture que Windows place lui-meme en fin de
# fichier ; le collecteur passe par la meme fonction).


def _iter_jsonl(path: Path):
    """Les objets JSON d'un fichier, un par un (le ruban local pese plus d'un Go : jamais tout en memoire)."""
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
                    yield obj
    except OSError:
        return


def _instant(row: dict) -> int:
    try:
        return int(row.get("time") or 0)
    except (TypeError, ValueError):
        return 0


def fusionner_explorer(root: Path, artefacts: Path) -> dict:
    cible = root / CIBLE
    connus: set[str] = set()
    sans_hash: set[str] = set()
    locales = 0
    for row in _iter_jsonl(cible):
        locales += 1
        h = row.get("hash")
        if isinstance(h, str) and h:
            connus.add(h)
        else:
            sans_hash.add(json.dumps(row, sort_keys=True, ensure_ascii=False))
    nouvelles: list[dict] = []
    entrees = 0
    for src in sorted(p for p in artefacts.rglob(MOTIF) if p.resolve() != cible.resolve()):
        for row in _iter_jsonl(src):
            entrees += 1
            h = row.get("hash")
            if isinstance(h, str) and h:
                if h in connus:
                    continue
                connus.add(h)
            else:
                cle = json.dumps(row, sort_keys=True, ensure_ascii=False)
                if cle in sans_hash:
                    continue
                sans_hash.add(cle)
            nouvelles.append(row)
    nouvelles.sort(key=lambda r: (_instant(r), str(r.get("hash"))))
    if nouvelles:
        ajouter_atomique(cible, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in nouvelles), fsync=True)
    return {"mode": "AJOUT_SEUL", "entrees": entrees, "locales": locales, "ajoutees": len(nouvelles),
            "doublons_retires": entrees - len(nouvelles), "total_final": locales + len(nouvelles)}


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
