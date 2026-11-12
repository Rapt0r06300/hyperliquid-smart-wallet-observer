"""AlinaSync — rapatrie les lanes cloud « marché » et « contexte », jusqu'ici jamais téléchargées.

Six lanes collectent sur GitHub ; quatre seulement étaient rapatriées (fills poll, fills WS,
carnets L2, explorer). Les deux autres produisaient des données qui n'atteignaient ni le coffre
ni le laboratoire :

* ``copy-vault-market-lanes``   : transactions publiques et bougies 1 min ;
* ``copy-vault-contexte-lanes`` : positions des leaders (``clearinghouseState``, relevées 24 h/24
  dans le cloud — la continuité qui manquait à l'étude de réplication lente) et tranches TWAP.

Le certificateur est l'UNIQUE autorité de validation et d'identité : chaque ligne d'artefact est
soumise à la règle de sa famille (``certifier_lignes``) ; seules les lignes acceptées et non déjà
présentes sont AJOUTÉES au ruban local du même nom, telles que la lane les a écrites (leur
provenance n'est pas réécrite). Le ruban passe ensuite par le Certificateur comme toute collecte.

PAPER / lecture seule. FAIL-SOFT : sans ``gh``, sans run ou sans artefact, rien n'est modifié.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from telecharger_fills_lanes_github import _gh_reel, gh_disponible, telecharger_runs  # noqa: E402

from hl_observer.datasets import coffre_certifie as C  # noqa: E402

DATA = Path("runtime") / "data"
#: lane -> (workflow, rubans produits). Chaque ruban doit être connu du certificateur.
LANES: dict[str, tuple[str, tuple[str, ...]]] = {
    "market": ("copy-vault-market-lanes.yml", ("copy_vault_trades_lane.jsonl", "copy_vault_candle_lane.jsonl")),
    "contexte": ("copy-vault-contexte-lanes.yml", ("copy_vault_positions_lane.jsonl", "copy_vault_twap_lane.jsonl",
                                                    "copy_vault_snapshots_lane.jsonl",
                                                    "copy_vault_orders_lane.jsonl")),
}


def lister_runs(gh, cwd: Path, workflow: str, limite: int) -> list[str]:
    """Identifiants des derniers runs terminés avec succès du workflow."""
    res = gh(["run", "list", "--workflow", workflow, "-L", str(max(1, limite * 3)),
              "--json", "databaseId,status,conclusion"], cwd)
    if res.returncode != 0:
        return []
    try:
        runs = json.loads(res.stdout or "[]")
    except (ValueError, TypeError):
        return []
    ids = [str(r.get("databaseId")) for r in runs if isinstance(r, dict)
           and r.get("status") == "completed" and r.get("conclusion") == "success"]
    return ids[:limite]


def _lignes(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            yield from handle
    except OSError:
        return


def fusionner_ruban(root: Path, artefacts: Path, nom: str, *, now_ms: int | None = None) -> dict[str, Any]:
    """Ajoute au ruban local ``nom`` les lignes d'artefact certifiables et encore absentes."""
    detecte = C.detecter_famille(nom)
    if detecte is None:
        return {"ruban": nom, "statut": "FAMILLE_INCONNUE", "ajoutees": 0}
    famille, source = detecte
    maintenant = int(time.time() * 1000) if now_ms is None else int(now_ms)
    cible = root / DATA / nom
    deja: set = set()
    # identités déjà présentes au ruban local (mêmes règles : une ligne locale invalide ne compte pas)
    for _ in C.certifier_lignes(_lignes(cible), famille=famille, source=source, now_ms=maintenant, deja_vus=deja):
        pass
    stats = C.StatsCertif()
    acceptees: list[str] = []
    fichiers = sorted(p for p in artefacts.rglob(nom) if p.is_file())
    for fichier in fichiers:
        for brut in _lignes(fichier):
            ligne = brut.strip()
            if not ligne:
                continue
            for norm, decision, _raison in C.certifier_lignes(
                    [ligne], famille=famille, source=source, now_ms=maintenant, deja_vus=deja, stats=stats):
                if norm is not None and decision in (C.PASS, C.REPARE):
                    acceptees.append(ligne)
    if acceptees:
        cible.parent.mkdir(parents=True, exist_ok=True)
        with cible.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("".join(ligne + "\n" for ligne in acceptees))
            handle.flush()
            with contextlib.suppress(OSError):
                os.fsync(handle.fileno())
    return {"ruban": nom, "statut": "OK", "famille": famille, "fichiers_artefact": len(fichiers),
            "lues": stats.entrees, "ajoutees": len(acceptees), "doublons": stats.doublons,
            "rejetees": stats.quarantaine, "raisons_rejet": dict(sorted(stats.raisons.items()))}


def telecharger_et_fusionner(root: Path, lane: str, *, gh=_gh_reel, limite_runs: int = 3,
                             now_ms: int | None = None) -> dict[str, Any]:
    workflow, rubans = LANES[lane]
    if not gh_disponible(gh, cwd=root):
        return {"lane": lane, "statut": "gh_indisponible", "runs": 0, "rubans": []}
    run_ids = lister_runs(gh, root, workflow, limite_runs)
    if not run_ids:
        return {"lane": lane, "statut": "aucun_run", "runs": 0, "rubans": []}
    tmp = Path(tempfile.mkdtemp(prefix=f"alina_{lane}_lanes_"))
    try:
        telecharges = telecharger_runs(gh, root, run_ids, tmp)
        if telecharges == 0:
            return {"lane": lane, "statut": "telechargement_vide", "runs": 0, "rubans": []}
        return {"lane": lane, "statut": "OK", "runs": telecharges,
                "rubans": [fusionner_ruban(root, tmp, nom, now_ms=now_ms) for nom in rubans]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--lane", choices=(*LANES, "toutes"), default="toutes")
    p.add_argument("--runs", type=int, default=3)
    args = p.parse_args(argv)
    for lane in (LANES if args.lane == "toutes" else (args.lane,)):
        res = telecharger_et_fusionner(Path(args.root), lane, limite_runs=max(1, args.runs))
        if res["statut"] != "OK":
            print(f"[lanes-{lane}] {res['statut']} -> rien a fusionner (non bloquant).", flush=True)
            continue
        detail = " ; ".join(f"{r['ruban']} +{r['ajoutees']} (doublons {r.get('doublons', 0)}, rejets {r.get('rejetees', 0)})"
                            for r in res["rubans"])
        print(f"[lanes-{lane}] {res['runs']} run(s) rapatrie(s) ; {detail}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
