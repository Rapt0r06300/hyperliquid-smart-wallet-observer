"""[COPY-VAULT #71] ambiguous-action deny : action indéterminable -> aucune nouvelle exposition."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.ambiguous_action_deny import decision   # noqa: E402


def test_action_claire_et_confiante_ouvre():
    r = decision("OPEN", confiance=0.9)
    assert r["nouvelle_exposition"] is True


def test_ambigu_pas_de_nouvelle_exposition():
    r = decision("???", confiance=0.9)
    assert r["nouvelle_exposition"] is False and r["raison"] == "ACTION_AMBIGUE"
    assert r["autorise_reduction"] is True                # réduction toujours tolérée


def test_confiance_insuffisante_refuse_ouverture():
    r = decision("OPEN", confiance=0.4)
    assert r["nouvelle_exposition"] is False and r["raison"] == "CONFIANCE_INSUFFISANTE"
