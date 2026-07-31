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
