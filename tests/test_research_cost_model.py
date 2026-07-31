"""ALPHA P14 — source unique de couts (research) : frais depuis config, decomposition, cost_incomplet bloque promote."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import cost_model as C  # noqa: E402


def test_fees_roundtrip_source_unique():
    assert C.fees_roundtrip_taker_bps("HL") == 9.0            # 4.5 + 4.5 depuis frais_venues
    assert C.fees_roundtrip_taker_bps("HL", "BIN") == 9.0     # cross-venue = deux venues


def test_decomposer_total_et_incomplet():
    c = C.decomposer_cout(fees_bps=9.0, spread_bps=1.0)       # slippage/latency absents mais non requis
    assert c["cost_total_bps"] == 10.0 and c["cost_incomplet"] is False
    c2 = C.decomposer_cout(fees_bps=9.0)                       # spread requis manquant
    assert c2["cost_incomplet"] is True


def test_cout_bloque_promote():
    assert C.cout_bloque_promote(C.decomposer_cout(fees_bps=9.0)) is True
    assert C.cout_bloque_promote(C.decomposer_cout(fees_bps=9.0, spread_bps=1.0)) is False


def test_cout_executable():
    c = C.cout_executable_taker_bps("HL", spread_bps=2.0, slippage_bps=1.0, latency_bps=0.5)
    assert c["cost_total_bps"] == 12.5 and c["cost_incomplet"] is False
