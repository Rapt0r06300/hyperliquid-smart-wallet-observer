"""[COPY-VAULT #77] orphan-copy sweeper : vault flat mais expo paper restante -> orphelin détecté."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.orphan_copy_sweeper import detecter   # noqa: E402


def test_orphelin_detecte():
    r = detecter(0.0, 0.5)                                # vault flat, on tient 0.5
    assert r["orphelin"] is True and r["a_deboucler"] == 0.5 and r["sens_debouclage"] == "VENTE"


def test_coherent_pas_orphelin():
    assert detecter(0.5, 0.5)["orphelin"] is False


def test_position_inconnue_prudence():
    assert detecter(None, 0.5)["orphelin"] is True        # vault inconnu -> vérifier/déboucler
    assert detecter(0.0, None)["orphelin"] is True
