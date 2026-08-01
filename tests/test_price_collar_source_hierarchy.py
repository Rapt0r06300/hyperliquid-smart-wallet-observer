"""[pépite 253] price collar source hierarchy : BBO frais puis mark/index/reference si BBO invalide."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.price_collar_source_hierarchy import reference_collar   # noqa: E402


def test_bbo_frais_prioritaire():
    r = reference_collar(bbo_bid=100.0, bbo_ask=100.2, mark=99.0)
    assert r["reference"] == 100.1 and r["source"] == "BBO_MID"


def test_fallback_mark_si_bbo_croise():
    r = reference_collar(bbo_bid=100.5, bbo_ask=100.0, mark=99.5)   # BBO croisé -> mark
    assert r["reference"] == 99.5 and r["source"] == "MARK"


def test_aucune_source_fiable():
    r = reference_collar(bbo_bid=None, bbo_ask=None, mark=None, index=None, reference_secondaire=None)
    assert r["reference"] == "UNMEASURABLE"
