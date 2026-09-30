"""[pépite 203] delta-fill canonical : cumulatif -> new_fill = cum_new - cum_prev, recul = anomalie."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.delta_fill_canonical import delta_fill   # noqa: E402


def test_delta_incremental():
    r = delta_fill(3.0, 2.0)
    assert r["new_fill"] == 1.0 and r["anomalie"] is False


def test_cumul_en_recul_anomalie():
    r = delta_fill(1.5, 2.0)
    assert r["new_fill"] == "UNMEASURABLE" and r["anomalie"] is True


def test_cumul_invalide():
    assert delta_fill(None, 2.0)["new_fill"] == "UNMEASURABLE"
