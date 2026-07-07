from hl_observer.arbitrage.opportunity_model import PaperArbitrageLeg, build_paper_arbitrage_opportunity
from hl_observer.arbitrage.opportunity_ranker import rank_paper_arbitrage_opportunities


def test_arbitrage_ranker_keeps_best_accepted_net_edge() -> None:
    low = build_paper_arbitrage_opportunity(
        long_leg=PaperArbitrageLeg("hl", "HYPE", "LONG", 100, fee_bps=2, slippage_bps=2),
        short_leg=PaperArbitrageLeg("cex", "HYPE", "SHORT", 100.3, fee_bps=2, slippage_bps=2),
    )
    high = build_paper_arbitrage_opportunity(
        long_leg=PaperArbitrageLeg("hl", "HYPE", "LONG", 100, fee_bps=2, slippage_bps=2),
        short_leg=PaperArbitrageLeg("cex", "HYPE", "SHORT", 102, fee_bps=2, slippage_bps=2),
    )

    assert rank_paper_arbitrage_opportunities([low, high])[0] == high
