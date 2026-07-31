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
        assert b in txt, "dimension CI manquante dans ci.yml: %s" % b
    assert txt.count("timeout-minutes") >= 4          # un timeout par job (aucun job sans borne)


def test_fix55_job_runtime_replay_reference_des_preuves_reelles():
    txt = _texte("ci.yml")
    preuves = ["test_paper_pipeline_e2e.py", "test_producer_consumer.py",
               "test_market_truth_replay_stage.py", "test_forward_causal_parity_bloc17.py"]
    for f in preuves:
        assert f in txt, "le job runtime-replay ne cite pas %s" % f
        assert (RACINE / "tests" / f).exists(), "job runtime-replay fantôme : %s absent du dépôt" % f


def test_fix55_factory_observable_linux_et_windows():
    txt = _texte("alpha-factory.yml")
    for b in ["ubuntu-latest", "windows-latest", "timeout-minutes", "--junitxml",
              "actions/upload-artifact", "test_run_factory.py", "test_factory_coverage.py"]:
        assert b in txt, "dimension Factory manquante dans alpha-factory.yml: %s" % b
    assert "push:" in txt and "branches: [main]" in txt      # Factory aussi observable au HEAD
