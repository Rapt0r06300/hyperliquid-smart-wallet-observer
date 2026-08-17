from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "donnees-hypersmart.yml"


def test_tous_les_tests_dataset_sont_decouverts_dynamiquement_sur_linux_et_windows() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8", errors="replace")
    test_files = sorted((ROOT / "tests").glob("test_dataset_*.py"))
    assert test_files, "Aucun test dataset trouvé"

    # Le workflow ne doit plus maintenir deux listes manuelles qui dérivent.
    # Linux et Windows découvrent tous les tests test_dataset_*.py à chaque run.
    assert "find tests -maxdepth 1 -type f -name 'test_dataset_*.py'" in workflow
    assert "Get-ChildItem -LiteralPath tests -Filter 'test_dataset_*.py' -File" in workflow
    assert "DATASET_TESTS" in workflow
    assert "$datasetTests" in workflow
    assert "pytest -q \"${DATASET_TESTS[@]}\"" in workflow
    assert "pytest -q @datasetTests" in workflow

    # Gardes fail-closed : un glob vide ne doit jamais produire un faux succès.
    assert "Aucun test dataset découvert sur Linux" in workflow
    assert "Aucun test dataset découvert sur Windows" in workflow


def test_workflow_dataset_se_declenche_sur_les_nouveaux_tests_et_launchers() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8", errors="replace")
    assert "tests/test_dataset_*.py" in workflow
    assert "PREPARER_EXPERIENCE_FULL_COLD.cmd" in workflow
    assert "LANCER_LABO_180GO.cmd" in workflow
    assert "ANALYSER_DONNEES_HYPERSMART.cmd" in workflow
