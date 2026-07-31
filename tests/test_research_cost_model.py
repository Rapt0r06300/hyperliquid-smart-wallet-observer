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
    # FIX-06 : slippage/latency MANQUANTS -> coût INCOMPLET (les 4 composantes requises par défaut)
    c = C.decomposer_cout(fees_bps=9.0, spread_bps=1.0)
    assert c["cost_total_bps"] == 10.0 and c["cost_incomplet"] is True
    complet = C.decomposer_cout(fees_bps=9.0, spread_bps=1.0, slippage_bps=0.5, latency_bps=0.0)
    assert complet["cost_total_bps"] == 10.5 and complet["cost_incomplet"] is False


def test_cout_bloque_promote():
    assert C.cout_bloque_promote(C.decomposer_cout(fees_bps=9.0, spread_bps=1.0)) is True   # slippage/latency manquants
    complet = C.decomposer_cout(fees_bps=9.0, spread_bps=1.0, slippage_bps=0.5, latency_bps=0.0)
    assert C.cout_bloque_promote(complet) is False


def test_cout_executable():
    c = C.cout_executable_taker_bps("HL", spread_bps=2.0, slippage_bps=1.0, latency_bps=0.5)
    assert c["cost_total_bps"] == 12.5 and c["cost_incomplet"] is False
