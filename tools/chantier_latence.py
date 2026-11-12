#!/usr/bin/env python3
"""CHANTIER LATENCE — mesure l'avantage de copie à 5 s / 15 s / 30 s / 60 s / 120 s de délai de réaction.

Le délai entre le fill du leader et notre entrée est le suspect n°1 de la perte (−18 bps/décision à 60 s,
7,6 bps de dérive partis avant l'observation). Cet outil rejoue EXACTEMENT les mêmes signaux avec le vrai
moteur d'exécution (carnets L2 causaux, identité de connexion, frais canoniques, spread observé), en ne
faisant varier QUE le délai de copie, et agrège le PnL net réel par délai.

Il charge EXACTEMENT comme le labo : depuis le dernier espace de travail matérialisé
(``runtime/reports/copy_vault_quant_lab/*/workspace``, produit par un passage du labo). Donc : lancer
d'abord ``LANCER_LAB_QUANT_COPY_VAULT.cmd`` (qui matérialise le coffre), puis cet outil. Lecture seule.

Lecture du résultat : si le net devient positif à faible délai, copier plus vite est la voie ; s'il reste
négatif même à 5 s, la dérive ne bat pas le coût (chercher maker / conditionnement / réplication lente).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))


def _dernier_workspace(root: Path) -> Path | None:
    base = root / "runtime" / "reports" / "copy_vault_quant_lab"
    try:
        runs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    except OSError:
        return None
    for run in runs:
        ws = run / "workspace"
        if (ws / "SAFE_INPUT_MANIFEST.json").is_file() or (ws / "runtime" / "data").is_dir():
            return ws
    return None


def charger_metaordres_et_carnets(workspace: Path):
    """(métaordres, carnets_par_coin) chargés comme le labo, depuis un espace de travail matérialisé."""
    import importlib.util

    from hl_observer.backtesting import copy_vault_executable as cv

    spec = importlib.util.spec_from_file_location("pipeline_latence", RACINE / "tools" / "pipeline_copie_reel.py")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    entries, _audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(workspace)
    metaorders, _meta_audit = cv.cluster_metaorders(entries)
    books, books_audit = cv.load_observed_books(workspace, coins={str(m["coin"]) for m in metaorders})
    return metaorders, books, books_audit


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--horizon-ms", type=int, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)
    workspace = _dernier_workspace(root)
    if workspace is None:
        print("[latence] aucun espace de travail du labo — lancez d'abord LANCER_LAB_QUANT_COPY_VAULT.cmd.")
        return 2
    from hl_observer.backtesting.copy_vault_latency_study import HORIZON_DEFAUT_MS, etude_latence

    metaorders, books, _audit = charger_metaordres_et_carnets(workspace)
    horizon = int(args.horizon_ms) if args.horizon_ms else HORIZON_DEFAUT_MS
    res = etude_latence(metaorders, books, horizon_ms=horizon)
    res["workspace"] = str(workspace)
    res["metaordres"] = len(metaorders)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print(f"CHANTIER LATENCE  ({len(metaorders):,} signaux · horizon {horizon // 1000} s)".replace(",", " "))
    print("=" * 60)
    for d in res["par_delai"]:
        net = "—" if d["net_bps_par_decision"] is None else f"{d['net_bps_par_decision']:+.2f} bps"
        print(f"  délai {d['copy_delay_ms'] // 1000:>3} s : {d['signaux_executes']:>6} exécutés · net {net}")
        if d["signaux_executes"] == 0 and d["refus_par_motif"]:
            motif = next(iter(d["refus_par_motif"]))
            print(f"            (bloqué : {motif})")
    print("-" * 60)
    print(f"  LECTURE : {res['lecture']}")
    if res["gain_bps_en_copiant_plus_vite"] is not None:
        print(f"  gain en copiant plus vite : {res['gain_bps_en_copiant_plus_vite']:+.2f} bps/décision")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
