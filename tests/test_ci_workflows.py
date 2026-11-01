"""FIX-55 — la CI GitHub est réellement OBSERVABLE au HEAD et couvre toutes les dimensions requises :
Linux shards / Windows / safety / Factory / runtime-replay / JUnit / artefacts / timeouts.

Garde-fou : si une dimension disparaît d'un workflow, ce test échoue (plus de CI muette). Assertions par TEXTE
(sans dépendance YAML) pour rester vert même dans un shard CI minimal.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
WF = RACINE / ".github" / "workflows"


def _texte(nom: str) -> str:
    return (WF / nom).read_text(encoding="utf-8")


def test_fix55_ci_couvre_toutes_les_dimensions_observables():
    txt = _texte("ci.yml")
    besoins = [
        "securite:", "tests-linux:", "tests-windows:", "runtime-replay:",   # jobs nommés/observables
        "shard: [1, 2, 3, 4, 5, 6]",     # Linux shards (partition complète)
        "windows-latest",                 # Windows = vrai OS cible
        "safety-audit",                   # audits de sécurité (aucun ordre réel)
        "--junitxml",                     # rapports JUnit
        "actions/upload-artifact",        # artefacts
        "timeout-minutes",                # bornes de temps
        "push:", "branches: [main]",      # déclenché sur push main => observable au HEAD
    ]
    for b in besoins:
        assert b in txt, f"dimension CI manquante dans ci.yml: {b}"
    assert txt.count("timeout-minutes") >= 4          # un timeout par job (aucun job sans borne)


def test_fix55_job_runtime_replay_reference_des_preuves_reelles():
    txt = _texte("ci.yml")
    preuves = ["test_paper_pipeline_e2e.py", "test_producer_consumer.py",
               "test_market_truth_replay_stage.py", "test_forward_causal_parity_bloc17.py"]
    for f in preuves:
        assert f in txt, f"le job runtime-replay ne cite pas {f}"
        assert (RACINE / "tests" / f).exists(), f"job runtime-replay fantôme : {f} absent du dépôt"


def test_fix55_factory_observable_linux_et_windows():
    txt = _texte("alpha-factory.yml")
    for b in ["ubuntu-latest", "windows-latest", "timeout-minutes", "--junitxml",
              "actions/upload-artifact", "test_run_factory.py", "test_factory_coverage.py"]:
        assert b in txt, f"dimension Factory manquante dans alpha-factory.yml: {b}"
    assert "push:" in txt and "branches: [main]" in txt      # Factory aussi observable au HEAD


def test_ci_jobs_runtime_utilisent_un_python_isole():
    txt = _texte("ci.yml")
    for job in ["securite:", "tests-linux:", "tests-windows:", "runtime-replay:"]:
        bloc = txt.split(f"  {job}", 1)[1]
        assert "python -m venv .ci-venv" in bloc, f"venv manquant dans {job}"
        assert "GITHUB_PATH" in bloc, f"PATH CI non isole dans {job}"


def test_copy_vault_hosted_jobs_ne_telechargent_pas_le_reservoir_brut():
    """Les jobs code-only gardent le dépôt utile sans hydrater 1.8M shards bruts."""
    for nom in ("hyperlab-ci.yml", "labo-continu-ci.yml"):
        txt = _texte(nom)
        assert "filter: blob:none" in txt, f"clone blobless manquant dans {nom}"
        assert "sparse-checkout-cone-mode: false" in txt, f"mode sparse explicite manquant dans {nom}"
        assert "!/datasets/" in txt, f"réservoir datasets non exclu dans {nom}"
        assert "/*" in txt, f"racine du dépôt non conservée dans {nom}"


def test_local_l2_hosted_job_installs_import_dependencies():
    txt = _texte("local-l2-certification-tests.yml")
    assert "python -m pip install --disable-pip-version-check pytest PyYAML" in txt


def test_local_l2_hosted_job_avoids_raw_dataset_checkout():
    txt = _texte("local-l2-certification-tests.yml")
    for required in (
        "filter: blob:none",
        "sparse-checkout-cone-mode: false",
        "            /src/",
        "            /tools/",
        "            /tests/",
        "            /pyproject.toml",
    ):
        assert required in txt


def test_continuous_lab_runs_the_fail_closed_copy_vault_closure_gate():
    txt = _texte("labo-continu-ci.yml")
    assert "tests/test_copy_vault_closure_gate.py" in txt
