"""Honest technical progress gate for preserved requirements 321..775.

Literal historical labels 321..775 remain unrecoverable. Five facets are mapped
to each of 91 preserved thematic requirements. A requirement only counts when a
category-specific executable evaluator proves it. Generic file presence never
validates a future category.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hl_observer.ops.pre_run_copy_321_395 import evaluate_copy_requirements

SOURCE_PATH = "docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md"
STATUS_PATH = "docs/PRE_RUN_775_CANONICAL_STATUS.json"
DERIVED_START = 321
DERIVED_END = 775
DERIVED_COUNT = DERIVED_END - DERIVED_START + 1
BASE_COUNT = 91
FACETS = ("CONTRACT", "POSITIVE_PATH", "NEGATIVE_FAIL_CLOSED", "DETERMINISM_CAUSALITY", "EVIDENCE_PROVENANCE")

@dataclass(frozen=True)
class BaseRequirement:
    ordinal: int
    category: str
    key: str
    description: str

_GROUPS = (
    ("COPY_VAULT", (("userfills_pagination","userFillsByTime et pagination bornée"),("position_lifecycle","lifecycle OPEN/ADD/REDUCE/CLOSE"),("cashflow_not_pnl","dépôts/retraits distincts du PnL"),("stable_identity","identité wallet/vault stable"),("copyability_freshness","copyability et fraîcheur du leader"),("leader_follower_execution","latence leader→follower et slippage follower"),("capacity","capacité exécutable"),("consistency_one_big_win","consistency et one-big-win"),("drawdown_regime","drawdown et régimes"),("twap_metaorders","TWAP et métaordres"),("vault_conflicts","conflits entre vaults"),("unseen_vault_holdout","holdout de vaults jamais vus"),("oos_forward","OOS et forward"),("costs_sample_size","coûts réels et taille d'échantillon"),("net_pnl_placebo","PnL net et placebo"))),
    ("LEAD_LAG", (("certified_timestamps","timestamps certifiables et rejet des horloges non certifiables"),("causality_real_lag","causalité et lag réel"),("multi_horizon","multi-horizon"),("regimes","régimes"),("clock_second_minute","début de seconde et horizon minute"),("clock_5m_15m","horizons 5 minutes et 15 minutes"),("ofi_microprice","OFI et microprice"),("queue_depletion","queue depletion"),("adds_cancels","ajouts et annulations"),("depth","profondeur"),("latency","latence"),("universe","univers"),("cost_stress","stress de coûts"),("placebos","placebos"))),
    ("CROSS_VENUE", (("sync_clock_skew","synchronisation des venues et clock skew"),("bbo_freshness","fraîcheur BBO"),("depth_vwap","profondeur et VWAP exécutable"),("instrument_mapping","mapping exact des instruments"),("entry_two_legs","entrée jambe A et jambe B"),("exit_two_legs","sortie jambe A et jambe B"),("four_fills","cycle complet à quatre fills"),("fees","frais"),("interleg_latency","latence inter-jambes"),("naked_leg_risk","risque de jambe nue"),("partial_fills","fills partiels"),("missed_leg","jambe manquée"),("convergence","convergence"),("max_holding","durée maximale de détention"),("venue_outage","panne de venue"),("spread_depth_nonexec","élargissement spread, disparition profondeur et rejet non-exécutable/faux mapping"))),
    ("ANTI_OVERFIT", (("train_validation","train et validation séparés"),("oos","out-of-sample"),("forward","forward"),("purge_embargo","purge et embargo"),("walk_forward","walk-forward"),("cpcv","CPCV"),("pbo","PBO"),("placebos","placebos"),("neighbor_sensitivity","sensibilité aux voisins"),("cost_latency_stress","stress frais/slippage/latence"),("alternate_universes","univers alternatifs"),("holdout_veto","veto holdout et absence de retuning après observation"))),
    ("MAXDATA_AUTONOMY", (("target_4usd","objectif 4 USD par famille"),("completed_suites_truth","COMPLETED_SUITES uniquement pour les succès réels"),("state_sha","état lié au SHA exact"),("state_dataset","état lié au snapshot dataset"),("state_suite_config_runtime","état lié suite/config/runtime proof"),("cache_checkpoint","cache et checkpoint anti-recalcul"),("escalate_stop","escalade et arrêt contrôlés"),("continue_below_target","continuer tant qu'une famille est sous cible"),("memory_partition","mémoire séparée SHA/famille/snapshot/config"),("stale_cannot_overwrite","un état stale/incomplet d'un autre SHA ne remplace pas la certification courante"))),
    ("DETERMINISM", (("no_hidden_global_mutation","aucun monkeypatch/global mutation caché"),("pure_validation_io","validation pure, routage déterministe et I/O explicites"),("reproducible_replay","replay/forward/dataset reproductibles"))),
    ("SELF_HOSTED_SECURITY", (("runner_not_installed","PREPARER_PC_ALINA non lancé et runner non installé par défaut"),("explicit_go","GO_SELF_HOSTED=TRUE explicite"),("main_sha_owner_no_pr","main uniquement, SHA exact, owner, pas de PR"),("minimal_permissions","permissions minimales contents:read et persist-credentials false"),("controlled_command_token_paper","commande contrôlée, token dataset read-only, paper-only, real execution false"),("sanitized_artifacts","artifacts nettoyés et secrets protégés"),("pinned_actions_untrusted_data","actions épinglées, code avant gate, dataset non fiable"),("input_attack_surface","path traversal, zip-slip, symlink, exécutable dataset, shell injection et entrées bornées"))),
    ("CI", (("relevant_suites_green","suites CI pertinentes vertes"),("no_test_deletion_to_hide_red","aucun rouge masqué par suppression de tests"),("cross_platform_labs","Linux, Windows, PowerShell 5.1, HyperLab, Alpha et labo replay-forward"),("security_selfhosted_tests","tests sécurité et self-hosted"))),
    ("WINDOWS_PORTABILITY", (("embedded_runtime","Python, MinGit et wheelhouse/offline embarqués"),("hermetic","tests hermétiques sans user-site ni Python système"),("paths_new_pc","espaces, autre disque, nouveau PC et imports circulaires"),("runtime_sqlite_copy","runtime et SQLite exacts après copie et archive reproductible"))),
    ("OBSERVABILITY", (("cockpit_runtime","cockpit: progression, ressources et runtime"),("github_online_truth","vérité GitHub en ligne, pas seulement service Running"))),
    ("DOCS", (("readme_truth","README: scope courant, objectif +4, données/replay/safety et runner non installé"),)),
    ("REHEARSALS_GO", (("ordered_rehearsals","répétitions pré-full ~180GB avec crash/restart/RAM/disque/consommation runtime"),("final_go_gate","GO final: main propre, CI verte, ledger ~180GB, PnL réconcilié, 3 familles certifiables, anti-overfit/placebos/sanitisation/reproductibilité/docs"))),
)

PRIOR_BLOCK_ASSETS = (".github/workflows/pre-run-001-100.yml",".github/workflows/pre-run-101-200.yml",".github/workflows/pre-run-201-300.yml",".github/workflows/pre-run-pnl-301-313.yml",".github/workflows/pre-run-pnl-314-320.yml","tests/test_pre_run_optimizations_001_100.py","tests/test_pre_run_guard_001_100.py","tests/test_pre_run_optimizations_101_200.py","tests/test_pre_run_guard_101_200.py","tests/test_pre_run_201_220_rigor.py","tests/test_pre_run_221_260_rigor.py","tests/test_pre_run_261_300_rigor.py","tests/test_pre_run_pnl_301_313.py","tests/test_pre_run_pnl_314_320.py")

def base_requirements() -> tuple[BaseRequirement, ...]:
    out=[]; ordinal=1
    for category,entries in _GROUPS:
        for key,description in entries:
            out.append(BaseRequirement(ordinal,category,key,description)); ordinal+=1
    if len(out)!=BASE_COUNT: raise AssertionError(f"registry must have {BASE_COUNT} requirements, got {len(out)}")
    return tuple(out)

def proof_id(base_ordinal:int, facet_index:int)->int:
    return DERIVED_START+(base_ordinal-1)*len(FACETS)+facet_index

def _sha256(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _existing(root:Path,paths:Iterable[str])->list[str]: return [p for p in paths if (root/p).is_file()]

def _source_contract(root:Path):
    source=root/SOURCE_PATH; status_file=root/STATUS_PATH
    if not source.is_file() or not status_file.is_file(): return False,{"reason":"SOURCE_OR_STATUS_MISSING"}
    try: status=json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: return False,{"reason":f"STATUS_UNREADABLE:{type(exc).__name__}"}
    actual=_sha256(source); expected=str(status.get("thematic_requirements_sha256") or "")
    honest=status.get("literal_source_unrecoverable") is True and status.get("exact_literal_reconstruction_claimed") is False and status.get("thematic_requirements_path")==SOURCE_PATH
    return actual==expected and honest,{"source_sha256":actual,"expected_sha256":expected,"literal_source_unrecoverable":status.get("literal_source_unrecoverable"),"exact_literal_reconstruction_claimed":status.get("exact_literal_reconstruction_claimed")}

def evaluate(root:Path)->dict[str,object]:
    root=root.resolve(); source_ok,source_meta=_source_contract(root); prior_existing=_existing(root,PRIOR_BLOCK_ASSETS); prior_ok=len(prior_existing)==len(PRIOR_BLOCK_ASSETS)
    copy=evaluate_copy_requirements(root); copy_by_key={row["key"]:row for row in copy["requirements"]}; proofs=[]; base_done=0
    for req in base_requirements():
        facet_results=[]; copy_row=copy_by_key.get(req.key) if req.category=="COPY_VAULT" else None
        for facet_index,facet in enumerate(FACETS):
            pid=proof_id(req.ordinal,facet_index)
            if copy_row is not None:
                ok=bool(copy_row["facets"][facet]); evidence=list(copy_row["evidence"]); hashes=dict(copy_row["evidence_sha256"]); blocker=None if ok else "COPY_REQUIREMENT_FAILED"
            else:
                ok=False; evidence=[]; hashes={}; blocker="CATEGORY_NOT_YET_SPECIFICALLY_VERIFIED"
            facet_results.append(ok); proofs.append({"id":pid,"base_ordinal":req.ordinal,"category":req.category,"key":req.key,"description":req.description,"facet":facet,"ok":ok,"historical_literal":False,"provenance":"DERIVED_TECHNICAL_REQUIREMENT","descriptor":f"DERIVED:{pid}:{req.category}:{req.key}:{facet}","evidence":evidence,"evidence_sha256":hashes,"blocker":blocker})
        if all(facet_results): base_done+=1
    derived_done=sum(1 for p in proofs if p["ok"]); ids=[int(p["id"]) for p in proofs]
    structure_ok=len(proofs)==DERIVED_COUNT and ids==list(range(DERIVED_START,DERIVED_END+1)) and len({p["descriptor"] for p in proofs})==DERIVED_COUNT and all(p["historical_literal"] is False for p in proofs)
    progress_ok=bool(prior_ok and source_ok and structure_ok and copy["ok"] is True and derived_done>=75)
    complete=bool(progress_ok and derived_done==DERIVED_COUNT and base_done==BASE_COUNT); technical_done=320+derived_done if prior_ok else derived_done
    return {"roadmap_id":"HYPERSMART_PNL_CANONICAL_775","ok":progress_ok,"complete":complete,"status":"DONE_TECHNICAL_775_SOURCE_LOSS_HONEST" if complete else "IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST","historical_literal_recovery":"TERMINAL_SOURCE_LOSS_HONEST","exact_literal_reconstruction_claimed":False,"technical_completion_claimed":complete,"prior_1_320_assets_ok":prior_ok,"prior_1_320_asset_count":len(prior_existing),"source_contract_ok":source_ok,"source_contract":source_meta,"evaluated_categories":["COPY_VAULT"],"category_progress":{"COPY_VAULT":{"requirements_done":copy["requirements_done"],"requirements_total":copy["requirements_total"],"facets_done":copy["facets_done"],"facets_total":copy["facets_total"],"ok":copy["ok"]}},"base_requirements_total":BASE_COUNT,"base_requirements_done":base_done,"derived_proofs_start":DERIVED_START,"derived_proofs_end":DERIVED_END,"derived_proofs_total":DERIVED_COUNT,"derived_proofs_done":derived_done,"technical_total":775,"technical_done":technical_done,"next_derived_id":next((int(p["id"]) for p in proofs if not p["ok"]),None),"proof_facets":list(FACETS),"proofs":proofs}

def main(argv=None)->int:
    parser=argparse.ArgumentParser(description="Gate de progression technique spécifique 321..775"); parser.add_argument("--root",default="."); parser.add_argument("--output"); args=parser.parse_args(argv)
    result=evaluate(Path(args.root)); payload=json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n"
    if args.output:
        output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True); output.write_text(payload,encoding="utf-8")
    print(payload); return 0 if result["ok"] else 1

if __name__=="__main__": raise SystemExit(main())
__all__=["BASE_COUNT","DERIVED_COUNT","DERIVED_END","DERIVED_START","FACETS","BaseRequirement","base_requirements","evaluate","proof_id"]
