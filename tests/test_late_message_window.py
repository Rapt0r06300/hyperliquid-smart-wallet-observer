"""[pépite 271] late-message window : hors ordre dans la fenêtre → réordonné ; trop tard → loggé, pas injecté."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.late_message_window import classer   # noqa: E402


def test_dans_ordre():
    assert classer(1050.0, 1000.0)["action"] == "OK"


def test_reordonne_dans_fenetre():
    r = classer(995.0, 1000.0, fenetre_ms=20.0)   # retard 5ms <= 20
    assert r["action"] == "REORDONNE" and r["retard_ms"] == 5.0


def test_trop_tard_rejete():
    r = classer(900.0, 1000.0, fenetre_ms=20.0)   # retard 100ms > 20
    assert r["action"] == "REJETE_TROP_TARD"
    assert classer(None, 1000.0)["action"] == "REJETE_TROP_TARD"
