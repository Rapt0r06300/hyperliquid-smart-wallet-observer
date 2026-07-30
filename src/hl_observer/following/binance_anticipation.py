"""P5.1 (§7) — score d'ANTICIPATION Wallet×Binance : le wallet agit-il AVANT le mouvement, ou le suit-il ?

Question centrale (priorité de recherche n°1) : quels wallets Hyperliquid bougent AVANT Binance plutôt
que de le suivre ? Pour une action wallet à l'instant T, on mesure sur le chemin de prix Binance, à
plusieurs horizons (100 ms → 30 s) :

    move_before = rendement orienté sur [T−h, T]   (ce qui a DÉJÀ bougé avant l'action)
    move_after  = rendement orienté sur [T, T+h]   (ce qui bouge APRÈS l'action)
    anticipation = move_after − move_before          (haut = leader ; ≤0 = suiveur/en retard)

« Orienté » = signé selon l'action : pour un achat/long, une hausse est favorable ; pour une vente/short,
une baisse est favorable. Deny-by-default : si le chemin de prix ne COUVRE pas [T−h, T+h], l'horizon est
`UNMEASURABLE` (None), jamais fabriqué. La sélection DISCOVERY→RANK→FREEZE→OOS→FORWARD reste externe
(réutiliser `following.scoring_robuste`), ce module ne fait que MESURER. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.binance_anticipation.v1"

#: Horizons réellement observables (ms).
HORIZONS_MS = (100, 250, 500, 1_000, 2_000, 5_000, 10_000, 30_000)

_ACHAT = ("BUY", "B", "LONG", "OPEN", "ADD", "BID")
_VENTE = ("SELL", "S", "SHORT", "CLOSE", "REDUCE", "ASK")


def _sens(action: object) -> int | None:
    a = str(action or "").strip().upper()
    if a in _ACHAT:
        return 1
    if a in _VENTE:
        return -1
    return None


def _pt(x: object) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _normaliser_chemin(path: Sequence[Any]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for p in path or ():
        if isinstance(p, Mapping):
            ts, px = _pt(p.get("ts_ms")), _pt(p.get("price"))
        else:
            try:
                ts, px = _pt(p[0]), _pt(p[1])
            except (TypeError, IndexError):
                ts = px = None
        if ts is not None and px is not None and px > 0:
            out.append((ts, px))
    out.sort(key=lambda kv: kv[0])
    return out


def _prix_causal(chemin: list[tuple[float, float]], t: float) -> float | None:
    """Dernier prix observé à ou avant `t` (fonction en escalier causale). `None` si aucun."""
    prix = None
    for ts, px in chemin:
        if ts <= t:
            prix = px
        else:
            break
    return prix


def _rendement_bps(p0: float, p1: float) -> float:
    return (p1 / p0 - 1.0) * 10_000.0


def score_anticipation(
    *,
    t_event_ms: float,
    action: object,
    path: Sequence[Any],
    horizons_ms: Sequence[int] = HORIZONS_MS,
) -> dict[str, Any]:
    """Mesure l'anticipation par horizon. `UNMEASURABLE` si le chemin ne couvre pas [T−h, T+h]."""
    chemin = _normaliser_chemin(path)
    sens = _sens(action)
    t = _pt(t_event_ms)
    par_horizon: dict[int, Any] = {}
    mesurables: list[float] = []

    if chemin and t is not None and sens is not None:
        t_min, t_max = chemin[0][0], chemin[-1][0]
        p_now = _prix_causal(chemin, t)
        for h in horizons_ms:
            h = int(h)
            p_before = _prix_causal(chemin, t - h) if t_min <= t - h else None
            p_after = _prix_causal(chemin, t + h) if t_max >= t + h else None
            if p_now is None or p_before is None or p_after is None:
                par_horizon[h] = {"statut": "UNMEASURABLE"}
                continue
            mb = sens * _rendement_bps(p_before, p_now)
            ma = sens * _rendement_bps(p_now, p_after)
            antici = ma - mb
            par_horizon[h] = {
                "statut": "MEASURED",
                "move_before_bps": round(mb, 6),
                "move_after_bps": round(ma, 6),
                "anticipation_bps": round(antici, 6),
            }
            mesurables.append(antici)
    else:
        for h in horizons_ms:
            par_horizon[int(h)] = {"statut": "UNMEASURABLE"}

    return {
        "schema_version": SCHEMA_VERSION,
        "sens": sens,
        "par_horizon": par_horizon,
        "n_horizons_mesures": len(mesurables),
        "anticipation_moy_bps": (round(sum(mesurables) / len(mesurables), 6) if mesurables else None),
        "real_execution": False,
    }


def anticipation_moyenne_par_wallet(
    evenements: Sequence[Mapping[str, Any]],
    path_par_coin: Mapping[str, Sequence[Any]],
    *,
    horizon_ms: int = 1_000,
) -> dict[str, Any]:
    """Anticipation médiane par wallet à un horizon donné (mesure seulement — pas de sélection/freeze ici).

    `evenements` : [{wallet, coin, action, ts_ms}, ...]. Un événement sans chemin couvrant est ignoré."""
    par_wallet: dict[str, list[float]] = {}
    for ev in evenements or ():
        wallet = str(ev.get("wallet") or "")
        coin = str(ev.get("coin") or "").upper()
        if not wallet or coin not in path_par_coin:
            continue
        s = score_anticipation(t_event_ms=ev.get("ts_ms"), action=ev.get("action"),
                               path=path_par_coin[coin], horizons_ms=(horizon_ms,))
        cell = s["par_horizon"].get(int(horizon_ms), {})
        if cell.get("statut") == "MEASURED":
            par_wallet.setdefault(wallet, []).append(cell["anticipation_bps"])
    resultats = {}
    for wallet, vals in par_wallet.items():
        vals_tries = sorted(vals)
        n = len(vals_tries)
        mediane = vals_tries[n // 2] if n % 2 else (vals_tries[n // 2 - 1] + vals_tries[n // 2]) / 2.0
        resultats[wallet] = {"n": n, "anticipation_mediane_bps": round(mediane, 6)}
    return {"schema_version": SCHEMA_VERSION, "horizon_ms": int(horizon_ms),
            "wallets": resultats, "real_execution": False}


__all__ = [
    "SCHEMA_VERSION", "HORIZONS_MS", "score_anticipation", "anticipation_moyenne_par_wallet",
]
