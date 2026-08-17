"""Registre exécutable des points HyperSmart AUD-101 -> AUD-200.

La source textuelle historique est ``TACHES_HYPERSMART_V6_COMPLET.md``.
La présence des fichiers vaut seulement CODE_PRESENT ; seule la CI dédiée
sur le même SHA peut conclure VERIFIED/DONE. Aucun réseau ni ordre ici.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "hypersmart.pre_run_101_200.v1"
FIRST_ID = 101
LAST_ID = 200
HISTORICAL_REGISTRY = "TACHES_HYPERSMART_V6_COMPLET.md"

OPS_SOURCES = ("src/hl_observer/ops/lab_rapport.py", "src/hl_observer/paper_trading/paper_engine.py", "ANALYSER_BACKTESTS_REPLAYS.cmd")
OPS_TESTS = ("tests/test_rapport_hierarchie_preuve.py", "tests/test_recette_windows_e2e.py", "tests/test_paper_engine_ledger_wiring.py")
ROBUSTNESS_SOURCES = ("src/hl_observer/ops/lab_rapport.py", "src/hl_observer/runtime/protections.py", "src/hl_observer/research/scenario_rigor.py", "src/hl_observer/research/qa_rigor.py", "src/hl_observer/research/validation_stats.py")
ROBUSTNESS_TESTS = ("tests/test_rapport_hierarchie_preuve.py", "tests/test_runtime_protections_streaming.py", "tests/test_scenario_rigor.py", "tests/test_qa_rigor.py", "tests/test_validation_stats.py")
PROVENANCE_SOURCES = ("src/hl_observer/research/experiment_infra.py", "src/hl_observer/research/experiment_design.py", "src/hl_observer/research/scenario_rigor.py", "src/hl_observer/research/qa_rigor.py", "src/hl_observer/research/validation_stats.py", ".github/workflows/portable-release-windows.yml")
PROVENANCE_TESTS = ("tests/test_experiment_infra.py", "tests/test_experiment_design.py", "tests/test_scenario_rigor.py", "tests/test_qa_rigor.py", "tests/test_validation_stats.py", "tests/test_portable_release_ci.py")

@dataclass(frozen=True)
class RoadmapItem:
    item_id: int
    title: str
    sources: tuple[str, ...]
    tests: tuple[str, ...]

TITLES: dict[int, str] = {
101:'Hierarchie des preuves et contexte de rapport',102:'Recette Windows E2E ANALYSER_BACKTESTS_REPLAYS',103:'Diagnostic causal zero position',104:'Diagnostic ready_strategies',105:'Raison exacte sizing zero',106:'Resultat experimental_paper_v2 isole',107:'Distinguer absence producteur et marche calme',108:'Funnel events emis/consommes/positions',109:'Drops producteur/consommateur, parse et staleness',110:'Strategies canoniques vers PaperIntent normalise',111:'Validation stricte intent/signal',112:'Fill tracable vers intent initial',113:'Reconciliation signal-intent-gate-fill-PnL',114:'Alerte all_signals_zero',115:'Cause no-trade hierarchique',116:'Diagnostic role adresse',117:'Pagination fills/historique deterministe',118:'Dedup snapshots/reconnect/out-of-order',119:'Metriques rate-limit/backoff/staleness/retry',120:'Separation exploratoire et canonique',121:'Guard moteur economique canonique realiste',122:'Budget unique 1000 USD',123:'Categorisation finale zero position',124:'E2E Windows premiere position PAPER provoquee',125:'Dashboard sans agregation ambigue modes/cohortes',126:'SLA officiel moteur PAPER',127:'Audit execution presque reelle lie au commit',128:'Rapport ops intents/fills/rejects PAPER',129:'Scenario controle LONG et SHORT PAPER',130:'Distinguer tests unitaires et integration',131:'Alignement temporel OOS trace et non manuel',132:'Causal clock alignment reception/decision/fill',133:'Impact late/duplicate/out-of-order sur PnL',134:'Budget de confiance par famille',135:'Preregistration hyperparametres avant holdout',136:'Freeze candidat officiel avant held-out',137:'Modification post-freeze invalide held-out',138:'Memoire inter-run surprises/faux positifs/instabilite',139:'Chargement memoire precedente avant hypotheses',140:'Contrefactuels sans filtre/rejet/latence',141:'Cout opportunite gates conservateurs',142:'Top faux negatifs',143:'Top faux positifs',144:'Frontiere de couts par famille',145:'Break-even cost par trade/regime',146:'Pareto PnL/drawdown/fill-rate/capacite',147:'Rejet automatique candidats domines',148:'Instabilite sous perturbation epsilon',149:'Carte de sensibilite avant holdout',150:'Comportement attendu en production',151:'Latences data/compute/execution separees',152:'Distribution cumulative latence famille/venue',153:'Burst traffic/queue/reconnect/backlog',154:'Injection pauses/reconnects enregistres',155:'Preuve invalide si queue/deque non bornee',156:'Plafonds memoire en long-run',157:'Fault injection tronque/malforme/duplique/reordonne',158:'Echec attendu disque plein/no-space',159:'Crash/resume mid-candidate/mid-verification',160:'Identite resultat apres crash/resume ou differences causales',161:'Provenance source_file/row/raw_hash/transform_version',162:'Decision economique interdite sans provenance',163:'Lineage raw records vers feature',164:'Decision lineage features vers score/decision',165:'Snapshot immutable config/code par run',166:'Config hash dans artefacts canoniques',167:'Code hash/Git SHA dans artefacts canoniques',168:'Hash environnement/dependances',169:'Script minimal reproduction candidat promu',170:'CI reproduction dossier temporaire isole',171:'DAG experiences parents/transformations/hypotheses',172:'Interdire promotion enfant orphelin',173:'Raison de chaque changement hyperparametre',174:'Sensibilite marginale par parametre',175:'Ablation sans parametre/gate',176:'Promotion exige ablation marginale',177:'Interactions paires de gates',178:'Detection gates redondants',179:'Detection gates contradictoires',180:'Rapport reachability gates importants',181:'Validation regimes non vus en train',182:'Validation periodes/mois non vus',183:'Validation symboles non vus si pertinent',184:'Validation clusters wallets non vus',185:'Transfert Hyperliquid segment A vers B',186:'Transfert calme vers volatile et inverse',187:'Metriques OOS proche/lointain',188:'Regularisation simplicite/penalite complexite',189:'Preferer modele simple equivalent',190:'Nombre effectif de parametres',191:'Dependance a l ordre des tests',192:'Campagne CI ordre aleatoire deterministe',193:'Stress race conditions locks/parallele',194:'Un seul writer ledger entre deux runners',195:'Recuperation lock apres crash',196:'Audit/listing tests flaky',197:'Flaky bloque promotion',198:'SBOM dans release portable',199:'Versions dependances exactes verifiees offline',200:'Provenance SHA256 binaires/outils telecharges'}

def _evidence_for(item_id: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if item_id <= 130: return OPS_SOURCES, OPS_TESTS
    if item_id <= 160: return ROBUSTNESS_SOURCES, ROBUSTNESS_TESTS
    return PROVENANCE_SOURCES, PROVENANCE_TESTS

ITEMS = {i: RoadmapItem(i, title, *_evidence_for(i)) for i, title in TITLES.items()}

def ids() -> tuple[int, ...]:
    return tuple(sorted(ITEMS))

def inspect_coverage(root: Path | str) -> dict[str, Any]:
    base = Path(root); expected = tuple(range(FIRST_ID, LAST_ID + 1)); actual = ids(); details=[]; missing_ids=[]
    for item_id in expected:
        item = ITEMS.get(item_id)
        if item is None:
            missing_ids.append(item_id); continue
        missing_sources=[p for p in item.sources if not (base/p).is_file()]
        missing_tests=[p for p in item.tests if not (base/p).is_file()]
        details.append({'item_id':item_id,'title':item.title,'sources':list(item.sources),'tests':list(item.tests),'missing_sources':missing_sources,'missing_tests':missing_tests,'code_present':not missing_sources and not missing_tests,'verified':False})
    n_present=sum(1 for d in details if d['code_present']); exact_ids=actual==expected; duplicate_free=len(actual)==len(set(actual)); registry_present=(base/HISTORICAL_REGISTRY).is_file()
    return {'schema_version':SCHEMA_VERSION,'first_id':FIRST_ID,'last_id':LAST_ID,'n_items':len(expected),'exact_ids':exact_ids,'duplicate_free':duplicate_free,'historical_registry_present':registry_present,'n_code_present':n_present,'n_missing':len(expected)-n_present,'missing_ids':missing_ids,'all_code_present':exact_ids and duplicate_free and not missing_ids and n_present==len(expected) and registry_present,'verified_by_presence':False,'details':details}
