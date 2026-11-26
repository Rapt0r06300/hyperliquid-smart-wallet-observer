#!/usr/bin/env python3
"""CHANTIER LATENCE — diagnostic exploratoire du délai de copie à 5/15/30/60/120 secondes.

Cet outil rejoue les mêmes candidats avec le vrai
moteur d'exécution (carnets L2 causaux, identité de connexion, frais canoniques, spread observé), en ne
faisant varier QUE le délai de copie, et agrège le PnL net réel par délai.

Il charge EXACTEMENT comme le labo : depuis le dernier espace de travail matérialisé
(``runtime/reports/copy_vault_quant_lab/*/workspace``, produit par un passage du labo), puis borne le
rejeu au dernier jour UTC complet et aux carnets nécessaires avant/après cette journée. Les rubans
JSONL sont lus en flux pour appliquer la fenêtre; le scan peut donc encore lire beaucoup d'octets,
mais les lignes hors fenêtre ne sont pas conservées en mémoire. Lancez d'abord
``LANCER_LAB_QUANT_COPY_VAULT.cmd``. Lecture seule; aucun résultat ne devient une preuve OOS.

Lecture du résultat : la couverture et le net sont affichés séparément. L'effet de vitesse compare
uniquement les mêmes signaux exécutables aux deux délais extrêmes. Le balayage est exploratoire,
pas une validation OOS et ne suffit pas à promouvoir une stratégie.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
JOUR_MS = 24 * 60 * 60 * 1000
MARGE_REFERENCE_L2_MS = 120_000
DELAIS_COPIE_MS = (5_000, 15_000, 30_000, 60_000, 120_000)
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


def _entier_positif(manifest: dict[str, Any], cle: str) -> int:
    valeur = manifest.get(cle)
    if type(valeur) is not int or valeur <= 0:
        raise ValueError(f"champ de manifeste absent/invalide : {cle}")
    return valeur


def _resume_manifest_safe(workspace: Path) -> dict[str, Any]:
    """Valide le minimum nécessaire à une étude locale exploratoire; jamais une certification."""
    chemin = workspace / "SAFE_INPUT_MANIFEST.json"
    contenu = chemin.read_bytes()
    manifeste = json.loads(contenu)
    if not isinstance(manifeste, dict):
        raise ValueError("SAFE_INPUT_MANIFEST doit être un objet JSON")

    attendus = _entier_positif(manifeste, "expected_safe_shards")
    verifies = _entier_positif(manifeste, "verified_safe_shards")
    inventaire = _entier_positif(manifeste, "source_asset_inventory_count")
    unique_fills = _entier_positif(manifeste, "unique_fills")
    unique_books = _entier_positif(manifeste, "unique_books")
    plages = {
        cle: _entier_positif(manifeste, cle)
        for cle in ("fill_start_ms", "fill_end_ms", "book_start_ms", "book_end_ms")
    }
    if plages["fill_start_ms"] > plages["fill_end_ms"]:
        raise ValueError("plage temporelle des fills inversée")
    if plages["book_start_ms"] > plages["book_end_ms"]:
        raise ValueError("plage temporelle L2 inversée")

    tapes = {
        "fills_live": workspace / "runtime" / "data" / "vault_fills_live.jsonl",
        "l2": workspace / "runtime" / "data" / "copy_vault_l2_tape.jsonl",
    }
    tailles = {}
    for nom, tape in tapes.items():
        try:
            tailles[nom] = tape.stat().st_size
        except OSError as exc:
            raise ValueError(f"ruban requis indisponible ({nom}) : {exc}") from exc
        if tailles[nom] <= 0:
            raise ValueError(f"ruban requis vide ({nom})")

    exigences = {
        "safe_catalog_status": manifeste.get("safe_catalog_status") == "SAFE_COMPLETE",
        "safe_replay_inputs_available": manifeste.get("safe_replay_inputs_available") is True,
        "replay_inputs_available": manifeste.get("replay_inputs_available") is True,
        "paper_read_only": manifeste.get("paper_read_only") is True,
        "real_execution_disabled": manifeste.get("real_execution") is False,
        "safe_shards_match": verifies == attendus,
        "inventory_matches_verified": inventaire == verifies,
        "no_missing_shards": type(manifeste.get("missing_count")) is int
        and manifeste["missing_count"] == 0,
        "no_rejected_assets": type(manifeste.get("rejected_count")) is int
        and manifeste["rejected_count"] == 0,
        "source_inventory_complete": manifeste.get("source_asset_inventory_complete") is True,
    }
    if not all(exigences.values()):
        causes = ", ".join(nom for nom, ok in exigences.items() if not ok)
        raise ValueError(f"manifeste refusé pour l'exploration bornée : {causes}")

    complet = (
        manifeste.get("status") == "SAFE_COMPLETE"
        and
        manifeste.get("data_complete") is True
        and manifeste.get("continuity_evidence_status") == "PROVEN"
        and type(manifeste.get("payload_rejected_records")) is int
        and manifeste["payload_rejected_records"] == 0
    )
    return {
        "manifest_sha256": hashlib.sha256(contenu).hexdigest(),
        "manifest_status": manifeste.get("status"),
        "manifest_reason": manifeste.get("reason"),
        "corpus_readiness": "COMPLETE_INPUTS" if complet else "PARTIAL_EXPLORATORY_INPUTS",
        "continuity_evidence_status": manifeste.get("continuity_evidence_status"),
        "data_complete": manifeste.get("data_complete") is True,
        "payload_rejected_records": manifeste.get("payload_rejected_records"),
        "verified_safe_shards": verifies,
        "expected_safe_shards": attendus,
        "unique_fills": unique_fills,
        "unique_books": unique_books,
        "fill_start_ms": plages["fill_start_ms"],
        "fill_end_ms": plages["fill_end_ms"],
        "book_start_ms": plages["book_start_ms"],
        "book_end_ms": plages["book_end_ms"],
        "tape_bytes": tailles,
        "paper_read_only": True,
        "real_execution": False,
        "economic_evidence_status": "EXPLORATORY_NON_OOS",
        "promotion_allowed": False,
    }


def _bornes_validees(
    resume: dict[str, Any], fenetre_ms: tuple[int, int], *, horizon_ms: int
) -> tuple[int, int]:
    if type(horizon_ms) is not int or horizon_ms <= 0:
        raise ValueError("l'horizon doit être un entier positif")
    debut, fin = fenetre_ms
    if type(debut) is not int or type(fin) is not int or debut <= 0 or fin < debut:
        raise ValueError("bornes UTC invalides : début/fin en millisecondes requis")
    if fin - debut + 1 > JOUR_MS:
        raise ValueError("la fenêtre d'étude est limitée à 24 heures")
    if debut < resume["fill_start_ms"] or fin > resume["fill_end_ms"]:
        raise ValueError("la fenêtre demandée dépasse la couverture attestée des fills")
    if debut - MARGE_REFERENCE_L2_MS < resume["book_start_ms"]:
        raise ValueError("le L2 ne couvre pas la marge de référence avant la fenêtre")
    fin_carnets = fin + horizon_ms + max(DELAIS_COPIE_MS)
    if fin_carnets > resume["book_end_ms"]:
        raise ValueError("le L2 ne couvre pas l'horizon et le délai après la fenêtre")
    return debut, fin


def derniere_journee_utc_complete(
    resume: dict[str, Any], *, horizon_ms: int
) -> tuple[int, int]:
    """Choisit le dernier jour UTC plein couvert, avec marge L2 d'entrée et de sortie."""
    fin_utilisable = min(
        resume["fill_end_ms"],
        resume["book_end_ms"] - horizon_ms - max(DELAIS_COPIE_MS),
    )
    borne_utc = (fin_utilisable // JOUR_MS) * JOUR_MS
    fenetre = (borne_utc - JOUR_MS, borne_utc - 1)
    if fenetre[0] <= 0:
        raise ValueError("le manifeste ne contient pas un jour UTC complet exploitable")
    return _bornes_validees(resume, fenetre, horizon_ms=horizon_ms)


def bornes_carnets_pour_fenetre(
    fenetre_ms: tuple[int, int], *, horizon_ms: int
) -> tuple[int, int]:
    if type(horizon_ms) is not int or horizon_ms <= 0:
        raise ValueError("l'horizon doit être un entier positif")
    debut, fin = fenetre_ms
    if type(debut) is not int or type(fin) is not int or debut <= 0 or fin < debut:
        raise ValueError("bornes UTC invalides pour les carnets L2")
    return debut - MARGE_REFERENCE_L2_MS, fin + horizon_ms + max(DELAIS_COPIE_MS)


def charger_metaordres_et_carnets(
    workspace: Path, *, fenetre_ms: tuple[int, int], horizon_ms: int
):
    """(métaordres, carnets_par_coin) chargés comme le labo, depuis un espace de travail matérialisé."""
    import importlib.util

    from hl_observer.backtesting import copy_vault_executable as cv

    spec = importlib.util.spec_from_file_location("pipeline_latence", RACINE / "tools" / "pipeline_copie_reel.py")
    pipeline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline)
    entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(
        workspace, fenetre=fenetre_ms
    )
    if entries_audit.get("decoupe_sure") is not True:
        raise ValueError("fenêtrage refusé : un fill retenu manque sa startPosition")
    if entries_audit.get("episode_source") == "legacy_vault_episodes_fallback":
        raise ValueError("fenêtrage refusé : source d'épisodes legacy non bornée")
    metaorders, _meta_audit = cv.cluster_metaorders(entries)
    l2_debut, l2_fin = bornes_carnets_pour_fenetre(fenetre_ms, horizon_ms=horizon_ms)
    if metaorders:
        books, books_audit = cv.load_observed_books(
            workspace,
            coins={str(m["coin"]) for m in metaorders},
            depuis_ms=l2_debut,
            as_of_ms=l2_fin,
        )
    else:
        # Ne pas scanner des gigaoctets de carnet si la fenêtre n'a aucun signal candidat.
        books = {}
        books_audit = {
            "exists": None,
            "rows_read": 0,
            "valid_rows": 0,
            "skipped": True,
            "skip_reason": "NO_METAORDERS_IN_WINDOW",
        }
    return metaorders, books, {
        "entries": entries_audit,
        "books": books_audit,
        "l2_window_ms": [l2_debut, l2_fin],
    }


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--horizon-ms", type=int, default=None)
    p.add_argument(
        "--start-ms", type=int, default=None,
        help="début UTC inclusif en millisecondes Unix; avec --end-ms (fenêtre max 24 h)",
    )
    p.add_argument(
        "--end-ms", type=int, default=None,
        help="fin UTC inclusive en millisecondes Unix; avec --start-ms",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)
    workspace = _dernier_workspace(root)
    if workspace is None:
        print("[latence] aucun espace de travail du labo — lancez d'abord LANCER_LAB_QUANT_COPY_VAULT.cmd.")
        return 2
    from hl_observer.backtesting.copy_vault_latency_study import HORIZON_DEFAUT_MS, etude_latence

    horizon = HORIZON_DEFAUT_MS if args.horizon_ms is None else args.horizon_ms
    if type(horizon) is not int or horizon <= 0:
        print("[latence] --horizon-ms doit être un entier positif.", file=sys.stderr)
        return 2
    if (args.start_ms is None) != (args.end_ms is None):
        print("[latence] --start-ms et --end-ms doivent être fournis ensemble.", file=sys.stderr)
        return 2
    try:
        resume = _resume_manifest_safe(workspace)
        if args.start_ms is None:
            fenetre = derniere_journee_utc_complete(resume, horizon_ms=horizon)
        else:
            fenetre = _bornes_validees(
                resume, (args.start_ms, args.end_ms), horizon_ms=horizon
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[latence] entrées refusées : {exc}", file=sys.stderr)
        return 2

    try:
        metaorders, books, input_audit = charger_metaordres_et_carnets(
            workspace, fenetre_ms=fenetre, horizon_ms=horizon
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[latence] chargement borné refusé : {exc}", file=sys.stderr)
        return 2
    res = etude_latence(metaorders, books, horizon_ms=horizon)
    res["workspace"] = str(workspace)
    res["metaordres"] = len(metaorders)
    res["cohort_window_ms"] = list(fenetre)
    res["workspace_manifest"] = resume
    res["input_audit"] = input_audit
    res["economic_evidence_status"] = "EXPLORATORY_NON_OOS"
    res["promotion_allowed"] = False
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print(f"CHANTIER LATENCE  ({len(metaorders):,} signaux · horizon {horizon // 1000} s)".replace(",", " "))
    print("=" * 60)
    print(
        f"  fenêtre UTC incluse : {fenetre[0]} → {fenetre[1]} ms · "
        f"manifeste {resume['manifest_sha256'][:12]} · {resume['corpus_readiness']}"
    )
    entree_audit = input_audit["entries"]
    l2_audit = input_audit["books"]
    print(
        f"  données : {entree_audit.get('deduped_fills', 0)} fills retenus, "
        f"{entree_audit.get('live_fill_rows', 0)} lignes live parcourues; "
        f"{l2_audit.get('valid_rows', 0)} L2 valides / {l2_audit.get('rows_read', 0)} lignes lues"
    )
    print("  portée : exploration seulement; OOS/progression économique non prouvés")
    for d in res["par_delai"]:
        net = "—" if d["net_bps_par_decision"] is None else f"{d['net_bps_par_decision']:+.2f} bps"
        taux = "—" if d["couverture_execution_pct"] is None else f"{d['couverture_execution_pct']:.1f}%"
        print(
            f"  délai {d['copy_delay_ms'] / 1000:>6g} s : "
            f"{d['signaux_executes']:>6}/{d['signaux_candidats']:<6} exécutés "
            f"({taux} couverture) · net {net}"
        )
        if d["signaux_executes"] == 0 and d["refus_par_motif"]:
            motif = next(iter(d["refus_par_motif"]))
            print(f"            (bloqué : {motif})")
    print("-" * 60)
    print(f"  LECTURE : {res['lecture']}")
    if res["gain_bps_en_copiant_plus_vite"] is not None:
        print(
            f"  effet rapide-lent sur les {res['signaux_apparies_delai_extremes']} signaux communs : "
            f"{res['gain_bps_en_copiant_plus_vite']:+.2f} bps/décision"
        )
    print(f"  portée : {res['scope_resultat']} — {res['validation_requise']} requis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
