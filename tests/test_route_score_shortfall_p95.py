"""[pépite 234] route score par shortfall p95 : la queue de distribution départage deux venues à mêmes frais."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.route_score_shortfall_p95 import score_p95, meilleure   # noqa: E402


def test_p95():
    xs = [float(i) for i in range(1, 41)]                 # 1..40
    r = score_p95(xs, min_echantillons=20)
    assert r["p95_bps"] >= r["p50_bps"] and r["n"] == 40


def test_echantillon_insuffisant():
    assert score_p95([1.0, 2.0], min_echantillons=20)["p95_bps"] == "UNMEASURABLE"


def test_meilleure_route():
    assert meilleure(route_a_p95=5.0, route_b_p95=8.0)["meilleure"] == "A"
