"""[pépite 279] dependency/API version manifest : chaque capture stocke les versions SDK/parser/schema."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.capture.dependency_api_version_manifest import construire   # noqa: E402


def test_manifest_complet():
    v = {"sdk_version": "1.2.3", "parser_version": "p7", "schema_version": "s4"}
    r = construire(v)
    assert r["complet"] is True and r["manifest"]["parser_version"] == "p7"


def test_version_requise_absente():
    v = {"sdk_version": "1.2.3", "parser_version": "p7"}   # schema_version manquant
    r = construire(v)
    assert r["complet"] is False and r["manquants"] == ["schema_version"]


def test_versions_invalide():
    assert construire(None)["complet"] is False
