from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "donnees-hypersmart.yml"


def test_tous_les_tests_dataset_sont_listes_dans_la_ci_linux_et_windows() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8", errors="replace")
    test_files = sorted((ROOT / "tests").glob("test_dataset_*.py"))
    assert test_files, "Aucun test dataset trouvé"

    missing: list[str] = []
    for path in test_files:
        relative = path.relative_to(ROOT).as_posix()
        # Chaque chemin doit apparaître deux fois : job Linux + job Windows.
        if workflow.count(relative) < 2:
            missing.append(relative)

    assert not missing, (
        "Tests dataset absents d'au moins un job de donnees-hypersmart : "
        + ", ".join(missing)
    )


def test_workflow_dataset_se_declenche_sur_les_nouveaux_tests_et_launchers() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8", errors="replace")
    assert "tests/test_dataset_*.py" in workflow
    assert "PREPARER_EXPERIENCE_FULL_COLD.cmd" in workflow
    assert "LANCER_LABO_180GO.cmd" in workflow
    assert "ANALYSER_DONNEES_HYPERSMART.cmd" in workflow
