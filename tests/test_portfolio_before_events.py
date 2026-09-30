"""[lot2 #93] portfolio mis à jour AVANT diffusion : aucune décision ne voit une ancienne equity."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.portfolio_before_events import ordre_traitement, valider_sequence, MAJ_PORTFOLIO, DIFFUSER_EVENT   # noqa: E402


def test_ordre_canonique():
    assert ordre_traitement() == [MAJ_PORTFOLIO, DIFFUSER_EVENT]


def test_diffusion_avant_maj_violation():
    r = valider_sequence([DIFFUSER_EVENT, MAJ_PORTFOLIO])
    assert r["ok"] is False and r["raison"] == "DIFFUSION_AVANT_MAJ_EQUITY_PERIMEE"


def test_maj_avant_diffusion_ok():
    assert valider_sequence([MAJ_PORTFOLIO, DIFFUSER_EVENT])["ok"] is True
    assert valider_sequence([DIFFUSER_EVENT])["ok"] is False   # MAJ absente
