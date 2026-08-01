"""[pépite 268] crossed-book quarantine : best_bid > best_ask hors état valide → inexploitable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.feed_integrity.crossed_book_quarantine import verifier   # noqa: E402


def test_carnet_normal_exploitable():
    r = verifier(100.0, 100.2)
    assert r["etat"] == "EXPLOITABLE" and r["croise"] is False and r["spread"] == 0.2


def test_croise_quarantaine():
    assert verifier(100.5, 100.0)["etat"] == "QUARANTAINE"
    # sauf état explicitement déclaré valide
    assert verifier(100.5, 100.0, etat_valide_explicite=True)["etat"] == "EXPLOITABLE"


def test_prix_non_numerique():
    assert verifier(float("nan"), 100.0)["etat"] == "QUARANTAINE"
    assert verifier(None, 100.0)["etat"] == "QUARANTAINE"
