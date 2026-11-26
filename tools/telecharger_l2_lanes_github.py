"""AlinaSync — télécharge les carnets L2 des lanes GitHub (workflow copy-vault-l2-lanes)
et les fusionne dans runtime/data/copy_vault_l2_tape.jsonl.

Artefacts ``l2-shard-*`` (fichiers ``copy_vault_l2_lane.jsonl``) → cible
``copy_vault_l2_tape.jsonl``. Validation causale (received>=exchange, lag borné,
niveaux ordonnés) via ``certifier_book`` + dédup par (coin, exchange_ts). PAPER /
lecture seule. FAIL-SOFT : jamais d'échec bloquant.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.datasets.coffre_certifie import certifier_book, QUARANTAINE  # noqa: E402
from hl_observer.collection.collecte_fiable import ajouter_atomique  # noqa: E402
from telecharger_fills_lanes_github import _gh_reel, gh_disponible, telecharger_runs  # noqa: E402

WORKFLOW = "copy-vault-l2-lanes.yml"
CIBLE = Path("runtime") / "data" / "copy_vault_l2_tape.jsonl"
MOTIF = "copy_vault_l2_lane.jsonl"
CIBLE_BBO = Path("runtime") / "data" / "copy_vault_bbo_tape.jsonl"
MOTIF_BBO = "copy_vault_bbo_lane.jsonl"
LAG_MAX_MS = 30_000


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
    """Les objets JSON d'un fichier, un par un, sans tout charger."""
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


def _entier(valeur: Any) -> int:
    try:
        return int(valeur or 0)
    except (TypeError, ValueError):
        return 0


def _carnet_certifie(row: dict, now_ms: int):
    recv = row.get("received_at_ms")
    return certifier_book(row, source=str(row.get("source") or "HYPERLIQUID_L2_WS"),
                          now_ms=int(recv) if isinstance(recv, int) and recv > 0 else now_ms)


def fusionner_carnets(root: Path, artefacts: Path, *, now_ms: int | None = None) -> dict:
    """Ajoute au ruban local les carnets L2 des lanes, valides et absents (cle = coin, exchange_ts_ms).

    Un carnet local n'est jamais reecrit ni retire ; seuls ses carnets VALIDES comptent comme deja presents (comme
    l'ancienne fusion, qui gardait un carnet de lane quand le carnet local du meme instant etait invalide).
    ``now_ms`` injectable pour les tests (sinon l'instant courant).
    """
    import time as _t
    now_ms = int(now_ms if now_ms is not None else _t.time() * 1000)
    cible = root / CIBLE
    connues: set[tuple[Any, Any]] = set()
    locales = 0
    for row in _iter_jsonl(cible):
        locales += 1
        norm, decision, _r = _carnet_certifie(row, now_ms)
        if decision != QUARANTAINE:
            connues.add((norm.get("coin"), norm.get("exchange_ts_ms")))
    lanes = sorted(p for p in artefacts.rglob(MOTIF) if p.resolve() != cible.resolve())
    nouvelles: list[dict] = []
    rejets = entrees = 0
    for src in lanes:
        for row in _iter_jsonl(src):
            entrees += 1
            norm, decision, _r = _carnet_certifie(row, now_ms)
            if decision == QUARANTAINE:
                rejets += 1
                continue
            cle = (norm.get("coin"), norm.get("exchange_ts_ms"))
            if cle in connues:
                continue
            connues.add(cle)
            nouvelles.append(norm)
    nouvelles.sort(key=lambda r: (_entier(r.get("received_at_ms")), str(r.get("coin"))))
    if nouvelles:
        ajouter_atomique(cible, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in nouvelles), fsync=True)
    return {"mode": "AJOUT_SEUL", "lanes_trouvees": [str(p) for p in lanes], "entrees": entrees,
            "locales": locales, "rejets_qualite": rejets, "ajoutees": len(nouvelles),
            "doublons_retires": max(0, entrees - len(nouvelles) - rejets), "total_final": len(connues)}


def _bbo_valide(r: dict, now_ms: int) -> bool:
    if not isinstance(r, dict) or r.get("schema_version") != "hypersmart.copy_vault_bbo.v1":
        return False
    try:
        recv = int(r["received_at_ms"]); exch = int(r["exchange_ts_ms"])
        bpx = float(r["bid_px"]); bsz = float(r["bid_sz"])
        apx = float(r["ask_px"]); asz = float(r["ask_sz"])
    except (KeyError, TypeError, ValueError):
        return False
    return (recv >= exch > 0 and recv - exch <= LAG_MAX_MS
            and bpx > 0 and apx > bpx and bsz > 0 and asz > 0)


def fusionner_bbo(root: Path, artefacts: Path, *, now_ms: int | None = None) -> dict:
    """Ajoute au ruban BBO local les BBO des lanes (schema v1), valides et absents (cle = coin, exchange_ts_ms).

    Meme regle que les carnets : AJOUT SEUL, le ruban local n'est que lu (voir la note au-dessus)."""
    import time as _t
    now_ms = int(now_ms if now_ms is not None else _t.time() * 1000)
    cible = root / CIBLE_BBO
    connues: set[tuple] = set()
    locales = 0
    for row in _iter_jsonl(cible):
        locales += 1
        if _bbo_valide(row, now_ms):
            connues.add((row.get("coin"), row.get("exchange_ts_ms")))
    nouvelles: list[dict] = []
    rejets = entrees = 0
    for src in sorted(p for p in artefacts.rglob(MOTIF_BBO) if p.resolve() != cible.resolve()):
        for row in _iter_jsonl(src):
            entrees += 1
            if not _bbo_valide(row, now_ms):
                rejets += 1
                continue
            cle = (row.get("coin"), row.get("exchange_ts_ms"))
            if cle in connues:
                continue
            connues.add(cle)
            nouvelles.append(row)
    nouvelles.sort(key=lambda r: (_entier(r.get("received_at_ms")), str(r.get("coin"))))
    if nouvelles:
        ajouter_atomique(cible, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in nouvelles), fsync=True)
    return {"mode": "AJOUT_SEUL", "entrees": entrees, "locales": locales, "rejets_qualite": rejets,
            "ajoutees": len(nouvelles), "doublons_retires": max(0, entrees - len(nouvelles) - rejets),
            "total_final": len(connues)}


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
    tmp = Path(tempfile.mkdtemp(prefix="alina_l2_lanes_"))
    try:
        telecharges = telecharger_runs(gh, root, run_ids, tmp)
        if telecharges == 0:
            return {"statut": "telechargement_vide", "runs": 0, "fusion": None}
        return {"statut": "OK", "runs": telecharges,
                "fusion": fusionner_carnets(root, tmp), "fusion_bbo": fusionner_bbo(root, tmp)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Telecharge+fusionne les carnets L2 des lanes GitHub (AlinaSync).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--runs", type=int, default=3)
    args = p.parse_args(argv)
    res = telecharger_et_fusionner(Path(args.root), limite_runs=max(1, args.runs))
    statut = res["statut"]
    if statut == "gh_indisponible":
        print("[l2-lanes] gh indisponible/non authentifie -> carnets non rapatries (non bloquant).", flush=True)
        return 0
    if statut == "aucun_run":
        print("[l2-lanes] aucun run reussi du workflow copy-vault-l2-lanes -> rien a fusionner.", flush=True)
        return 0
    if statut == "telechargement_vide":
        print("[l2-lanes] aucun artefact telecharge (expires ?) -> rien a fusionner.", flush=True)
        return 0
    f = res["fusion"]
    fb = res.get("fusion_bbo") or {}
    print(f"[l2-lanes] {res['runs']} run(s) rapatrie(s) ; L2 total {f['total_final']} carnets "
          f"(doublons {f['doublons_retires']}, rejets {f['rejets_qualite']}) ; "
          f"BBO total {fb.get('total_final', 0)} (repli).", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
