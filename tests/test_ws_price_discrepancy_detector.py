from hl_observer.arbitrage.ws_price_discrepancy_detector import detect_ws_price_discrepancies
from hl_observer.realtime.multi_source_price_stream import PriceEvent


def test_ws_price_discrepancy_detector_finds_large_spread():
    rows = detect_ws_price_discrepancies(
        [PriceEvent("hl", "HYPE", 100, 100, 1), PriceEvent("cex", "HYPE", 101, 101, 1)],
        min_spread_bps=50,
    )
    assert len(rows) == 1
    assert rows[0].decision == "PAPER_DISCREPANCY"
