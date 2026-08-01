"""[COPY-VAULT lot2 #43] OPEN/ADD exige même version : equity de T1 avec position de T2 -> refus."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.coherent_snapshot_open import open_autorise   # noqa: E402


def test_meme_version_autorise():
    r = open_autorise(version_equity=7, version_positions=7)
    assert r["autorise"] is True and r["version"] == 7


def test_versions_differentes_refuse():
    r = open_autorise(version_equity=7, version_positions=8)
    assert r["autorise"] is False and r["raison"] == "SNAPSHOT_INCOHERENT_VERSIONS_DIFFERENTES"


def test_version_manquante():
    assert open_autorise(version_equity=None, version_positions=7)["autorise"] is False
