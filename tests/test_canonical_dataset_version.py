"""[pépite 263] canonical dataset version : changement de parser/schema → nouvelle version, jamais écrasement."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.canonical_dataset_version import version_canonique, decider   # noqa: E402


def test_version_deterministe():
    assert version_canonique("p1", "s1") == version_canonique("p1", "s1")
    assert version_canonique("p1", "s1") != version_canonique("p2", "s1")


def test_pipeline_inchange():
    enr = {"parser_version": "p1", "schema_version": "s1"}
    assert decider(enr, "p1", "s1")["action"] == "INCHANGE"


def test_changement_impose_nouvelle_version():
    enr = {"parser_version": "p1", "schema_version": "s1"}
    r = decider(enr, "p2", "s1")
    assert r["action"] == "NOUVELLE_VERSION" and r["ecrasement_interdit"] is True
