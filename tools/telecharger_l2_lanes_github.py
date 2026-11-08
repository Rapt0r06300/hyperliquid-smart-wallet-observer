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


def fusionner_carnets(root: Path, artefacts: Path, *, now_ms: int | None = None) -> dict:
    """Fusionne les carnets L2 locaux + ceux des lanes, validés et dédupliqués.

    Clé de dédup = (coin, exchange_ts_ms). On garde un carnet par instant d'echange.
    ``now_ms`` injectable pour les tests (sinon l'instant courant).
    """
    import time as _t
    now_ms = int(now_ms if now_ms is not None else _t.time() * 1000)
    cible = root / CIBLE
    sources: list[Path] = []
    if cible.exists():
        sources.append(cible)
    lanes = sorted(p for p in artefacts.rglob(MOTIF) if p.resolve() != cible.resolve())
    sources.extend(lanes)

    par_cle: dict[tuple[Any, Any], dict] = {}
    rejets = 0
    entrees = 0
    for src in sources:
        for row in _lire_jsonl(src):
            entrees += 1
            # valide/normalise le carnet ; borne la fraicheur sur les champs STOCKES
            recv = row.get("received_at_ms")
            norm, decision, _r = certifier_book(
                row, source=str(row.get("source") or "HYPERLIQUID_L2_WS"),
                now_ms=int(recv) if isinstance(recv, int) and recv > 0 else now_ms,
            )
            if decision == QUARANTAINE:
                rejets += 1
                continue
            cle = (norm.get("coin"), norm.get("exchange_ts_ms"))
            par_cle.setdefault(cle, norm)  # garde le premier vu pour cet instant

    fusionnes = sorted(par_cle.values(),
                       key=lambda r: (int(r.get("received_at_ms") or 0), str(r.get("coin"))))
    doublons = entrees - len(fusionnes) - rejets

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
    return {"lanes_trouvees": [str(p) for p in lanes], "entrees": entrees,
            "rejets_qualite": rejets, "doublons_retires": max(0, doublons),
            "total_final": len(fusionnes)}


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
    """Fusionne les BBO locaux + ceux des lanes (schema v1), dédup (coin, exchange_ts)."""
    import time as _t
    now_ms = int(now_ms if now_ms is not None else _t.time() * 1000)
    cible = root / CIBLE_BBO
    sources: list[Path] = []
    if cible.exists():
        sources.append(cible)
    sources.extend(sorted(p for p in artefacts.rglob(MOTIF_BBO) if p.resolve() != cible.resolve()))
    par_cle: dict[tuple, dict] = {}
    rejets = entrees = 0
    for src in sources:
        for row in _lire_jsonl(src):
            entrees += 1
            if not _bbo_valide(row, now_ms):
                rejets += 1
                continue
            par_cle.setdefault((row.get("coin"), row.get("exchange_ts_ms")), row)
    fusionnes = sorted(par_cle.values(), key=lambda r: (int(r.get("received_at_ms") or 0), str(r.get("coin"))))
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
    return {"entrees": entrees, "rejets_qualite": rejets,
            "doublons_retires": max(0, entrees - len(fusionnes) - rejets),
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
