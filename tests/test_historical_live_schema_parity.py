"""[pépite 259] historical/live schema parity : même objet canonique et mêmes unités hist vs forward."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.data_contract.historical_live_schema_parity import comparer   # noqa: E402


def test_parite_ok():
    s = {"price": {"type": "decimal", "unite": "usd"}, "ts": {"type": "int", "unite": "ms"}}
    assert comparer(s, {k: dict(v) for k, v in s.items()})["parite"] is True


def test_unite_differente():
    hist = {"price": {"type": "decimal", "unite": "ticks"}}
    live = {"price": {"type": "decimal", "unite": "usd"}}
    r = comparer(hist, live)
    assert r["parite"] is False and r["divergences"][0]["raison"] == "UNITE_DIFFERENTE"


def test_champ_manquant_live():
    hist = {"price": {"type": "decimal", "unite": "usd"}, "funding": {"type": "decimal", "unite": "bps"}}
    live = {"price": {"type": "decimal", "unite": "usd"}}
    assert any(d["raison"] == "CHAMP_MANQUANT_LIVE" for d in comparer(hist, live)["divergences"])
