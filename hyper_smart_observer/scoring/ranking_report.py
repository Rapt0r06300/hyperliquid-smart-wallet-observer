from __future__ import annotations

from hyper_smart_observer.scoring.smart_wallet_ranking import SmartWalletRanking


def format_ranking_report(rankings: list[SmartWalletRanking]) -> str:
    lines = ["Smart wallet ranking V2", "research only; not a trading signal"]
    for ranking in rankings:
        lines.append(f"{ranking.wallet_address} | {ranking.status} | score={ranking.rank_score:.2f} | {ranking.reason}")
    return "\n".join(lines)
