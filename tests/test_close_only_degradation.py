"""[COPY-VAULT #70] close-only degradation : données leader incomplètes -> OPEN/ADD interdits, REDUCE/CLOSE OK."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault import close_only_degradation as COD   # noqa: E402


def test_donnees_completes_tout_ok():
    assert COD.action_autorisee(COD.OPEN, donnees_completes=True)["autorise"] is True


def test_incompletes_open_interdit_close_ok():
    assert COD.action_autorisee(COD.OPEN, donnees_completes=False)["autorise"] is False
    assert COD.action_autorisee(COD.ADD, donnees_completes=False)["autorise"] is False
    assert COD.action_autorisee(COD.CLOSE, donnees_completes=False)["autorise"] is True
    assert COD.action_autorisee(COD.REDUCE, donnees_completes=False)["autorise"] is True


def test_action_inconnue_incompletes_refuse():
    assert COD.action_autorisee("???", donnees_completes=False)["autorise"] is False
