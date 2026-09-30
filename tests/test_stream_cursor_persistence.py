"""[COPY-VAULT #59] stream cursor persistence : curseur monotone, un événement consommé ne l'est pas deux fois."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.stream_cursor_persistence import CurseurStream   # noqa: E402


def test_avance_monotone():
    c = CurseurStream()
    assert c.avancer(5)["avance"] is True and c.dernier_traite() == 5
    assert c.avancer(6)["avance"] is True


def test_rejeu_refuse():
    c = CurseurStream(depart=10)
    r = c.avancer(10)                                      # seq deja traite
    assert r["avance"] is False and r["raison"] == "REJEU_OU_RETARD"
    assert c.avancer(8)["avance"] is False                # en retard


def test_deja_traite():
    c = CurseurStream(depart=10)
    assert c.deja_traite(9) is True and c.deja_traite(11) is False
    assert c.deja_traite(None) is True                    # invalide = prudence
