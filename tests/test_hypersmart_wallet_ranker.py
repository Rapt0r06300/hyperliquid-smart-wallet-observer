from __future__ import annotations

from hyper_smart_observer.intelligence.wallet_intelligence import analyze_wallet_pnls
from hyper_smart_observer.intelligence.wallet_ranker import rank_wallet_reports


def test_wallet_ranker_orders_by_copyability() -> None:
    weak = analyze_wallet_pnls("0x" + "1" * 40, [1000, 1, 1, -1, 1, -1, 1, -1, 1, -1])
    strong = analyze_wallet_pnls("0x" + "2" * 40, [10, 9, 8, -2, 7, 6, -1, 5, 4, -1, 3, 2])

    ranks = rank_wallet_reports([weak, strong])

    assert ranks[0].wallet_address == "0x" + "2" * 40
    assert ranks[0].rank == 1
    assert ranks[0].copyability_score >= ranks[1].copyability_score
