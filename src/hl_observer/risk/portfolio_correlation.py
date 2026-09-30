"""RISK-1 — Exposition nette réelle & positions redondantes.

7 positions LONG sur des alts corrélés ≠ 7 paris: c'est UN gros pari directionnel
déguisé. Ce module mesure l'exposition NETTE (par groupe de corrélation) et refuse
une nouvelle position qui ne fait qu'empiler le même risque. Pur, read-only.

La corrélation est fournie par groupes (classes d'actifs / clusters), pas estimée
ici — pas de matrice inventée. Sans groupe connu, un coin est son propre groupe.
"""

from __future__ import annotations

# Groupes de corrélation par défaut (extensible via env/config plus tard).
DEFAULT_GROUPS = {
    "BTC": "majors", "ETH": "majors",
    "SOL": "l1_alts", "AVAX": "l1_alts", "NEAR": "l1_alts", "APT": "l1_alts", "SUI": "l1_alts",
    "HYPE": "hl_eco",
    "DOGE": "memes", "WIF": "memes", "FARTCOIN": "memes", "KBONK": "memes", "MON": "memes",
}


def _group(coin: str, groups: dict[str, str]) -> str:
    return groups.get(str(coin).upper(), f"solo:{str(coin).upper()}")


def net_group_exposure(positions: list[dict], *, groups: dict[str, str] | None = None) -> dict[str, float]:
    """Exposition signée nette (USDT) par groupe: LONG +, SHORT −."""

    g = groups or DEFAULT_GROUPS
    out: dict[str, float] = {}
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        coin = str(p.get("coin") or "").upper()
        if not coin:
            continue
        side = str(p.get("side") or p.get("direction") or "").upper()
        notional = abs(float(p.get("notional_usdt") or p.get("copied_notional_usdt") or 0.0))
        signed = notional if side == "LONG" else (-notional if side == "SHORT" else 0.0)
        out[_group(coin, g)] = round(out.get(_group(coin, g), 0.0) + signed, 4)
    return out


def correlation_open_refusal(
    positions: list[dict],
    *,
    coin: str,
    side: str,
    new_notional_usdt: float,
    groups: dict[str, str] | None = None,
    max_group_net_exposure_usdt: float = 120.0,
    max_positions_per_group: int = 3,
) -> str:
    """Refuse une entrée qui sur-concentre un groupe de corrélation. '' = OK."""

    g = groups or DEFAULT_GROUPS
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        return "CORR_INVALID_SIDE"
    grp = _group(coin, g)
    same_group = [
        p for p in (positions or [])
        if isinstance(p, dict) and _group(str(p.get("coin") or ""), g) == grp
    ]
    same_dir = [p for p in same_group if str(p.get("side") or p.get("direction") or "").upper() == side]
    if len(same_dir) >= max_positions_per_group:
        return "CORR_TOO_MANY_SAME_GROUP_SAME_SIDE"
    exposure = net_group_exposure(positions, groups=g).get(grp, 0.0)
    add = abs(float(new_notional_usdt)) if side == "LONG" else -abs(float(new_notional_usdt))
    if abs(exposure + add) > float(max_group_net_exposure_usdt):
        return "CORR_GROUP_NET_EXPOSURE_EXCEEDED"
    return ""


def portfolio_concentration_report(positions: list[dict], *, groups: dict[str, str] | None = None) -> dict:
    exp = net_group_exposure(positions, groups=groups)
    gross = sum(abs(v) for v in exp.values()) or 1.0
    net = sum(exp.values())
    dominant = max(exp.items(), key=lambda kv: abs(kv[1])) if exp else (None, 0.0)
    return {
        "net_exposure_by_group": exp,
        "gross_exposure_usdt": round(gross, 4),
        "net_directional_usdt": round(net, 4),
        "directionality_ratio": round(abs(net) / gross, 4),  # 1.0 = tout dans le même sens
        "dominant_group": dominant[0],
        "dominant_group_exposure_usdt": round(dominant[1], 4),
    }


__all__ = [
    "DEFAULT_GROUPS", "net_group_exposure", "correlation_open_refusal",
    "portfolio_concentration_report",
]
