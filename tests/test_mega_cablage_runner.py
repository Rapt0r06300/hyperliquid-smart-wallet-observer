"""[CABLAGE runner] runner + __main__ : one-shot, boucle continue, refus hors dry-run (paper only)."""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.runner import run_mega_cablage, boucle_continue   # noqa: E402
from hl_observer.mega_cablage.__main__ import main   # noqa: E402

T = 1_700_000_000_000
OPEN = {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.5, "signe": 1, "ts_ms": T, "vault": "A",
        "book": {"asks": [(60010.0, 5.0)], "bids": [(59990.0, 5.0)]}}
CLOSE = {"coin": "BTC", "px": 61000.0, "mid": 61000.0, "sz": 0.5, "signe": -1, "ts_ms": T + 1000, "vault": "A",
         "book": {"asks": [(61010.0, 5.0)], "bids": [(60990.0, 5.0)]}}


def test_run_en_memoire_reconcilie():
    r = run_mega_cablage(evenements=[OPEN, CLOSE], notre_equity=1000.0, notional_max=500.0,
                         leader_equity_defaut=100000.0)
    assert r.ticks == 2 and r.events_traites == 2 and r.reconcilie is True


def test_refus_hors_dry_run():
    with pytest.raises(ValueError):
        run_mega_cablage(evenements=[OPEN], dry_run=False)
    assert main(["--no-dry-run"]) == 2       # __main__ refuse aussi
    assert main([]) == 0                       # aucun evenement -> ok (note AUCUN_EVENEMENT)


def test_boucle_continue_source_injectee():
    batches = iter([[OPEN], [CLOSE], []])

    def source():
        try:
            return next(batches)
        except StopIteration:
            return None

    r = boucle_continue(source=source, notre_equity=1000.0, notional_max=500.0, leader_equity_defaut=100000.0)
    assert r.events_traites == 2 and r.reconcilie is True
