"""Statistical summaries shared by Lead-Lag shadow backtests."""
from __future__ import annotations

import math
import statistics as st
from typing import Any

from hl_observer.backtesting.quant_methods import block_bootstrap


def _metriques(nets: list[float], *, n_periodes: int) -> dict[str, Any]:
    """Espérance, drawdown du cumul, et stabilité par période."""

    esper = st.mean(nets)
    cum, pic, dd = 0.0, 0.0, 0.0
    for value in nets:
        cum += value
        pic = max(pic, cum)
        dd = min(dd, cum - pic)
    taille = max(1, len(nets) // n_periodes)
    periodes = [nets[index:index + taille] for index in range(0, len(nets), taille)]
    moys = [st.mean(period) for period in periodes if period]
    bootstrap_totals = block_bootstrap(
        nets,
        block=max(1, int(math.sqrt(len(nets)))),
        n=500,
        seed=20260729,
    )
    bootstrap_means = sorted(total / len(nets) for total in bootstrap_totals)
    lower_index = max(0, int(len(bootstrap_means) * 0.025) - 1)
    upper_index = min(len(bootstrap_means) - 1, int(len(bootstrap_means) * 0.975))
    bootstrap_ci = (
        [round(bootstrap_means[lower_index], 3), round(bootstrap_means[upper_index], 3)]
        if bootstrap_means
        else [None, None]
    )
    return {
        "esperance_nette_bps": round(esper, 3),
        "n": len(nets),
        "drawdown_cumule_bps": round(dd, 2),
        "periodes_positives": f"{sum(1 for value in moys if value > 0)}/{len(moys)}",
        "moyennes_par_periode_bps": [round(value, 3) for value in moys],
        "bootstrap_mean_ci95_bps": bootstrap_ci,
        "stable": bool(moys) and all(value > 0 for value in moys),
    }


__all__ = ["_metriques"]
