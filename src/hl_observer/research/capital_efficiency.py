"""ALPHA P47 — EFFICIENCE du capital : net_edge_per_margin_hour = net PnL / marge moyenne / temps en marché.

Un edge net positif mais qui immobilise beaucoup de marge longtemps vaut moins qu'un edge plus petit mais
rapide et léger. On compare les alphas à ce ratio, pas au PnL brut. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def net_edge_per_margin_hour(net_pnl_usd: Any, marge_moyenne_usd: Any, temps_en_marche_h: Any) -> Any:
    """PnL net par dollar de marge et par heure en marché. UNMEASURABLE si un facteur manque/<=0."""
    if not all(isinstance(x, (int, float)) for x in (net_pnl_usd, marge_moyenne_usd, temps_en_marche_h)):
        return UNMEASURABLE
    if marge_moyenne_usd <= 0 or temps_en_marche_h <= 0:
        return UNMEASURABLE
    return round(net_pnl_usd / (marge_moyenne_usd * temps_en_marche_h), 6)


def comparer(alphas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ajoute `capital_per_h` à chaque alpha et trie décroissant (mesurables d'abord)."""
    out = []
    for a in alphas:
        v = net_edge_per_margin_hour(a.get("net_pnl_usd"), a.get("marge_moyenne_usd"), a.get("temps_en_marche_h"))
        out.append({**a, "capital_per_h": v})

    def cle(a: dict[str, Any]) -> float:
        return -a["capital_per_h"] if isinstance(a["capital_per_h"], (int, float)) else 1e18
    return sorted(out, key=cle)


def compare_selectivity_vs_volume(
    train_rows: Sequence[Mapping[str, Any]],
    oos_rows: Sequence[Mapping[str, Any]],
    *,
    cutoff_ms: int,
    min_oos_selected: int = 1,
    signal_ts_field: str = "signal_ts_ms",
    episode_id_field: str = "episode_id",
    selected_field: str = "selected",
    gross_pnl_field: str = "gross_pnl_usd",
    cost_field: str = "costs_usd",
    margin_field: str = "margin_usd",
    duration_field: str = "duration_h",
) -> dict[str, Any]:
    """Compare a pre-declared selective arm with all OOS trades.

    Costs are explicit and net PnL is recomputed as gross minus costs.  The
    result is a diagnostic ratio weighted by capital-hours, never a runtime
    activation or an argument that more trade count is better.
    """

    if isinstance(cutoff_ms, bool) or not isinstance(cutoff_ms, int) or cutoff_ms <= 0:
        return {"status": "UNMEASURABLE", "reason": "INVALID_CUTOFF", "paper_read_only": True}
    minimum = int(min_oos_selected)
    if minimum < 1:
        return {"status": "UNMEASURABLE", "reason": "INVALID_MINIMUM", "paper_read_only": True}

    def _parse(rows: Sequence[Mapping[str, Any]], *, train: bool) -> tuple[list[dict[str, Any]], str | None]:
        parsed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows or ():
            if not isinstance(row, Mapping):
                return [], "INVALID_ROW"
            episode = str(row.get(episode_id_field) or "").strip()
            ts = row.get(signal_ts_field)
            try:
                gross = float(row.get(gross_pnl_field))
                costs = float(row.get(cost_field))
                margin = float(row.get(margin_field))
                duration = float(row.get(duration_field))
            except (TypeError, ValueError):
                return [], "MISSING_ECONOMIC_EVIDENCE"
            selected = row.get(selected_field)
            if (
                not episode
                or episode in seen
                or isinstance(ts, bool)
                or not isinstance(ts, int)
                or ts <= 0
                or (train and ts > cutoff_ms)
                or (not train and ts <= cutoff_ms)
                or type(selected) is not bool
                or not all(math.isfinite(value) for value in (gross, costs, margin, duration))
                or costs < 0
                or margin <= 0
                or duration <= 0
            ):
                return [], "INVALID_SPLIT_SELECTION_OR_ECONOMICS"
            seen.add(episode)
            parsed.append({
                "episode_id": episode,
                "selected": selected,
                "gross_pnl_usd": gross,
                "costs_usd": costs,
                "net_pnl_usd": gross - costs,
                "capital_hours": margin * duration,
            })
        return parsed, None

    train, train_error = _parse(train_rows, train=True)
    oos, oos_error = _parse(oos_rows, train=False)
    if train_error or oos_error or not train or not oos:
        return {
            "status": "UNMEASURABLE",
            "reason": train_error or oos_error or "EMPTY_SPLIT",
            "paper_read_only": True,
            "real_execution": False,
        }

    def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"trades": 0, "net_pnl_usd": None, "costs_usd": None, "capital_hours": None, "net_per_capital_hour": None}
        net = sum(float(row["net_pnl_usd"]) for row in rows)
        costs = sum(float(row["costs_usd"]) for row in rows)
        capital_hours = sum(float(row["capital_hours"]) for row in rows)
        return {
            "trades": len(rows),
            "net_pnl_usd": round(net, 8),
            "costs_usd": round(costs, 8),
            "capital_hours": round(capital_hours, 8),
            "net_per_capital_hour": round(net / capital_hours, 8) if capital_hours > 0 else None,
        }

    selected_oos = [row for row in oos if row["selected"]]
    baseline = _metrics(oos)
    selective = _metrics(selected_oos)
    comparable = len(selected_oos) >= minimum
    return {
        "status": "COMPARABLE" if comparable else "UNMEASURABLE",
        "reason": None if comparable else "INSUFFICIENT_OOS_SELECTED_SAMPLE",
        "cutoff_ms": cutoff_ms,
        "train_rows": len(train),
        "train_selected_rows": sum(1 for row in train if row["selected"]),
        "baseline_oos": baseline,
        "selective_oos": selective,
        "trade_count_is_not_objective": True,
        "same_oos_episodes": True,
        "net_definition": "gross_pnl_usd-costs_usd",
        "capital_efficiency_definition": "net_pnl_usd/sum(margin_usd*duration_h)",
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
    }


def selectivity_vs_volume_receipt(
    train_rows: Sequence[Mapping[str, Any]],
    oos_rows: Sequence[Mapping[str, Any]],
    *,
    cutoff_ms: int,
    min_oos_selected: int = 1,
) -> dict[str, Any]:
    """Return the ECO-160 contract without turning trade selectivity into promotion.

    The underlying comparison is costed and uses one frozen OOS universe.  A
    ``PROVEN`` result means only that the comparison was auditable; it is not a
    profitability claim and cannot activate a strategy.
    """
    result = compare_selectivity_vs_volume(
        train_rows,
        oos_rows,
        cutoff_ms=cutoff_ms,
        min_oos_selected=min_oos_selected,
    )
    result.update(
        contract="ECO-160-selectivity-not-volume",
        selection_is_predeclared=True,
        same_oos_universe=True,
        paper_read_only=True,
        promotion="DISABLED_UNTIL_REVIEW",
    )
    if result.get("status") == "COMPARABLE":
        result["status"] = "PROVEN"
        result["verdict"] = "COMPARISON_AUDITABLE"
    return result


__all__ = [
    "net_edge_per_margin_hour", "comparer", "compare_selectivity_vs_volume",
    "selectivity_vs_volume_receipt", "UNMEASURABLE",
]
