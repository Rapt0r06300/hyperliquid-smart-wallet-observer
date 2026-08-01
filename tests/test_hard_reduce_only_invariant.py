"""[COPY-VAULT #66] hard reduce-only invariant : une réduction ne peut jamais augmenter l'exposition."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.hard_reduce_only_invariant import appliquer_reduction   # noqa: E402


def test_reduction_diminue_exposition():
    r = appliquer_reduction(2.0, 0.5)
    assert r["position"] == 1.5 and r["invariant_ok"] is True and abs(r["position"]) <= 2.0


def test_jamais_au_dela_de_zero_ni_flip():
    r = appliquer_reduction(2.0, 5.0)                         # réduire plus que détenu
    assert r["position"] == 0.0                               # borné a 0, pas de flip vers -3


def test_short_reduit_vers_zero():
    r = appliquer_reduction(-2.0, 1.0)
    assert r["position"] == -1.0 and abs(r["position"]) <= 2.0
