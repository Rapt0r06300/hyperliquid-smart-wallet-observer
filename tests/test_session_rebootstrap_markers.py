"""[COPY-VAULT lot2 #60] session/rebootstrap markers : savoir à quel état cohérent appartient une observation."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.session_rebootstrap_markers import MarqueursLedger   # noqa: E402


def test_attribution_de_session():
    m = MarqueursLedger()
    m.marquer(seq=0, type_marqueur="SESSION")
    m.marquer(seq=100, type_marqueur="REBOOTSTRAP")
    assert m.session_de(50)["session"] == 1              # entre 0 et 100
    assert m.session_de(150)["session"] == 2             # après rebootstrap


def test_avant_tout_marqueur_non_coherente():
    m = MarqueursLedger()
    m.marquer(seq=10)
    r = m.session_de(5)                                   # avant le 1er marqueur
    assert r["session"] == 0 and r["coherente"] is False


def test_seq_invalide():
    assert MarqueursLedger().session_de(None)["session"] is None
