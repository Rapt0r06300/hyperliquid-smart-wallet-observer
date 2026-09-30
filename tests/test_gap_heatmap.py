"""[pépite 262] gap heatmap : durée et distribution des trous par venue/coin/channel."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.dataset.gap_heatmap import heatmap   # noqa: E402


def test_distribution():
    r = heatmap({("HL", "BTC", "L2"): [5.0, 5.0, 5.0, 100.0]})
    cell = r["heatmap"][("HL", "BTC", "L2")]
    assert cell["count"] == 4 and cell["total"] == 115.0 and cell["max"] == 100.0


def test_percentiles():
    r = heatmap({"k": [10.0, 20.0, 30.0, 40.0, 50.0]})
    cell = r["heatmap"]["k"]
    assert cell["p50"] == 30.0 and cell["p95"] == 50.0


def test_durees_invalides_ignorees():
    cell = heatmap({"k": [float("inf"), -5.0, 7.0]})["heatmap"]["k"]
    assert cell["count"] == 1 and cell["total"] == 7.0
