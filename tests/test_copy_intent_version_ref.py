"""[COPY-VAULT lot2 #44] CopyIntent référence source_state_version : décision reproductible."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.copy_intent_version_ref import creer_intent   # noqa: E402


def test_intent_avec_version():
    r = creer_intent(action="open", coin="btc", taille=0.5, source_state_version=42)
    assert r["valide"] is True and r["source_state_version"] == 42 and r["reproductible"] is True


def test_version_manquante_refuse():
    r = creer_intent(action="OPEN", coin="BTC", taille=0.5, source_state_version=None)
    assert r["valide"] is False and r["raison"] == "SOURCE_STATE_VERSION_MANQUANTE"


def test_champs_invalides():
    assert creer_intent(action="OPEN", coin="", taille=0.5, source_state_version=1)["valide"] is False
