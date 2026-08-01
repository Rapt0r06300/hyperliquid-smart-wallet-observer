"""[pépite 235] route score par timeout p99 : intégrer les délais extrêmes, pas seulement la médiane."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.route_score_timeout_p99 import score_p99   # noqa: E402


def test_p99():
    xs = [10.0] * 30 + [5000.0]                           # median ~10, p99 capte le pic
    r = score_p99(xs, min_echantillons=20)
    assert r["p99_ms"] > r["p50_ms"]


def test_echantillon_insuffisant():
    assert score_p99([10.0], min_echantillons=20)["p99_ms"] == "UNMEASURABLE"


def test_negatifs_ignores():
    r = score_p99([-1.0] + [10.0] * 25, min_echantillons=20)
    assert r["n"] == 25
