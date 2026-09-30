from __future__ import annotations

from pathlib import Path

from hl_observer.audit.pre_run_001_100 import REGISTRY, inspect_coverage

ROOT = Path(__file__).resolve().parents[1]


def test_registry_couvre_exactement_001_a_100_sans_trou_ni_doublon():
    assert tuple(sorted(REGISTRY)) == tuple(range(1, 101))
    assert len(REGISTRY) == 100


def test_toutes_les_preuves_code_et_tests_sont_presentes_au_head():
    report = inspect_coverage(ROOT)
    assert report["n_items"] == 100
    assert report["missing_ids"] == [], report["missing_ids"]
    assert report["all_code_present"] is True
    # Présence != exécution : ce registre ne fabrique jamais un DONE.
    assert report["verified"] is False
    assert "CI tests execute" in report["verification_rule"]


def test_protections_historiquement_legacy_sont_dans_src_runtime():
    for optimization_id in (9, 10, 36, 71, 78, 79, 80, *range(81, 92)):
        evidence = REGISTRY[optimization_id]
        assert any(path.startswith("src/hl_observer/runtime/") for path in evidence.source_paths), optimization_id


def test_optimisations_72_77_pointent_vers_lorchestrateur_canonique_pas_le_legacy():
    for optimization_id in range(72, 78):
        evidence = REGISTRY[optimization_id]
        assert "src/hl_observer/ops/historical_analysis_suite.py" in evidence.source_paths
        assert all("recherche_continue" not in path for path in evidence.source_paths)


def test_92_100_restent_paper_only_et_ont_des_tests_de_regression():
    for optimization_id in range(92, 101):
        evidence = REGISTRY[optimization_id]
        assert evidence.paper_only is True
        assert evidence.source_paths
        assert evidence.test_paths


def test_aucune_optimisation_ne_se_declare_verifiee_par_simple_presence():
    report = inspect_coverage(ROOT)
    for item in report["items"]:
        assert item["status"] in {"CODE_PRESENT", "EVIDENCE_MISSING"}
        assert item["status"] != "VERIFIED"


def test_modules_canoniques_81_91_ne_contiennent_aucun_hot_path_de_trading():
    source = (ROOT / "src" / "hl_observer" / "runtime" / "research_guardrails.py").read_text(encoding="utf-8")
    for token in (
        '"/exchange"',
        "'/exchange'",
        "requests.post",
        "websockets.connect",
        "place_order",
        "market_order",
        "Account.from_key",
    ):
        assert token not in source
