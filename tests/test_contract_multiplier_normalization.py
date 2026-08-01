"""[pépite 229] contract multiplier normalization : exposition = qty x contract_size, pas qty brute."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.contract_multiplier_normalization import exposition, apparie   # noqa: E402


def test_exposition():
    assert exposition(2.0, contract_size=100.0) == 200.0


def test_appariement_par_exposition():
    # 200 contrats x1 = 2 contrats x100 -> memes expositions malgre quantites brutes differentes
    r = apparie(qty_a=200.0, contract_size_a=1.0, qty_b=2.0, contract_size_b=100.0)
    assert r["apparie"] is True


def test_expositions_differentes():
    r = apparie(qty_a=1.0, contract_size_a=1.0, qty_b=1.0, contract_size_b=100.0)
    assert r["apparie"] is False
