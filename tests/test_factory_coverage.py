"""ALPHA P58 — couverture de la Factory : chaque module de recherche ALPHA doit avoir un test (ou etre BLOCKED).

Echoue si un module de la famille Alpha Factory est codé mais jamais importé par un test. « Plus jamais de
module oublié. » Ne scanne QUE les modules de la factory (pas tout le legacy research/).
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

# Modules de la famille Alpha Factory (SHADOW/RESEARCH). Tout ajout ici exige un test.
FACTORY_MODULES = [
    "ofi_microprice", "mlofi", "wallet_copy_edge", "wallet_population", "wallet_binance_anticipation",
    "order_intent", "alpha_factory", "run_factory", "execution_maker", "alpha_inputs", "feature_increment",
    "cost_model", "validation_gates", "basis_vs_latency", "recette_economique", "search_space",
    "alpha_decay", "research_backlog",
    "deconfliction", "meta_gate", "wallet_info_ratio", "capital_efficiency", "daily_report", "drift_detector",
    "fee_regime", "liquidity_consumption", "capacity_curve", "exit_factory", "maker_toxicity",
    "book_resiliency", "spread_transition", "reproducibility",
    "price_discovery", "cross_asset_leadlag", "universal_micro", "nonlinear_challenger", "metaorder_hazard",
    "liquidation_flow", "cascade_warning", "clock_regimes", "wallet_fingerprint", "abnormal_regime",
    "hf_recorder", "multi_venue", "queue_model", "trigger_map", "hidden_vs_twap", "lineage",
    "forward_frozen", "purged_cv", "sizing", "portfolio", "feature_cache", "replay_consistency",
    "factory_families", "parallel_factory", "runtime_loop", "acceptance", "deflated_sharpe",
    "jsonl_stream",
]


def _blob_tests() -> str:
    tests_dir = Path(__file__).resolve().parent
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in tests_dir.glob("test_*.py"))


def test_chaque_module_factory_existe():
    research = RACINE / "src" / "hl_observer" / "research"
    manquants = [m for m in FACTORY_MODULES if not (research / f"{m}.py").exists()]
    assert not manquants, f"modules factory absents du code: {manquants}"


def test_chaque_module_factory_est_teste():
    blob = _blob_tests()
    non_testes = [m for m in FACTORY_MODULES if m not in blob]
    assert not non_testes, f"modules factory sans test (import absent): {non_testes}"


def test_fix02_chaine_reelle_famille_vers_trial(tmp_path):
    """FIX-02 : chaque famille du registre doit REELLEMENT produire un trial (adaptateur appele) ou un BLOCKED
    explicite. Pas seulement 'le nom du module apparait dans un test'."""
    from hl_observer.research import factory_families as FAM
    from hl_observer.research import run_factory as RF
    out = RF.run_all(data_dir=str(tmp_path), registry_path=str(tmp_path / "r.jsonl"))
    # chaine famille -> adapter -> experience appelee -> trial produit : une ligne PAR famille
    assert set(out["familles_couvertes"]) == set(FAM.FAMILLES)
    verdicts_ok = {"KILL", "KILL_FOLLOWER", "KILL_CONCENTRE", "CANDIDAT", "FORWARD_REQUIS", "MORE_DATA",
                   "OOS_POSITIF_A_FORWARD", "ANTICIPATEUR_A_FORWARD", "BLOCKED_EXTERNAL"}
    for r in out["rows"]:
        # jamais ERROR, jamais un statut inconnu, jamais une famille qui ne produit rien
        assert r["verdict"] in verdicts_ok, f"{r['_famille']} a produit un verdict inattendu: {r['verdict']}"


def test_fix02_famille_active_sans_adapter_serait_detectee(tmp_path):
    """Une famille ACTIVE/SHADOW sans adaptateur sortirait BLOCKED 'adaptateur absent' (jamais silencieusement OK)."""
    from hl_observer.research import factory_families as FAM
    from hl_observer.research import run_factory as RF
    a_couvrir = set(FAM.familles_a_couvrir())
    assert a_couvrir.issubset(set(RF.ADAPTERS) | set(RF.RAISONS_BLOCKED))
