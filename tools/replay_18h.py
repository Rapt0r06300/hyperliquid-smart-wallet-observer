"""REPLAY A/B + PARITÉ (labo 18 h, Flo 26/07).

- Replay MOTEUR A/B : même flux/timestamps/coûts, ancienne vs nouvelle version → comparer décisions/PnL,
  toute divergence expliquée.
- Direction A/B : continuation vs réversion — la direction opposée est RÉELLEMENT REJOUÉE (on recalcule le
  net depuis les prix avec le sens inversé), JAMAIS une simple négation `-net`.
- Exécution A/B : taker / maker risk-averse / maker probabiliste / top-of-book / VWAP / latence fixe vs empirique.
- Signal A/B : seul vs + confirmation OFI/régime/horloge/liquidité.
- Parité replay/forward : rejouer le MÊME fichier d'événements doit reproduire EXACTEMENT les mêmes décisions
  → `decision_hash(live) == decision_hash(replay)`.
Réutilise execution_paper.pnl_jambe (recalcul causal par jambe). 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hl_observer.experimental import execution_paper as EP  # noqa: E402


def decision_hash(decisions: list[dict]) -> str:
    """Empreinte STABLE d'une séquence de décisions (coin, ts, sens, action, prix). Sert à prouver la parité
    live==replay : mêmes entrées d'événements → mêmes décisions bit-à-bit."""
    canon = [[str(d.get("coin")), int(d.get("ts_ms") or 0), int(d.get("sens") or 0),
              str(d.get("action") or ""), round(float(d.get("prix") or 0.0), 8)] for d in decisions]
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parite(live: list[dict], replay: list[dict]) -> dict:
    """Parité stricte : True seulement si les hashs coïncident. Sinon on rend le 1er index divergent."""
    hl, hr = decision_hash(live), decision_hash(replay)
    ok = hl == hr
    idx = None
    if not ok:
        for i, (a, b) in enumerate(zip(live, replay)):
            if a != b:
                idx = i
                break
        if idx is None:
            idx = min(len(live), len(replay))
    return {"parite": ok, "hash_live": hl, "hash_replay": hr, "premier_divergent": idx,
            "n_live": len(live), "n_replay": len(replay)}


def replay_direction(episodes: list[dict], *, sens: int) -> dict:
    """Rejoue les épisodes avec un SENS imposé (+1 continuation / −1 réversion) en RECALCULANT le net par
    jambe depuis entry_px/exit_px/coûts — pas une négation du résultat. Chaque épisode doit porter
    entry_px, exit_px, size_usd, fee_bps, slippage_bps."""
    nets = []
    for e in episodes:
        try:
            jambe = {"side": int(sens), "entry_px": float(e["entry_px"]), "exit_px": float(e["exit_px"]),
                     "size_usd": float(e.get("size_usd") or 100.0), "fee_bps": float(e.get("fee_bps") or 0.0),
                     "slippage_bps": float(e.get("slippage_bps") or 0.0)}
            realized = EP.pnl_jambe(jambe)
            size = float(e.get("size_usd") or 100.0)
            nets.append(realized / size * 1e4 if size else 0.0)      # net en bps sur le notionnel
        except (KeyError, ValueError, TypeError):
            continue
    return {"sens": sens, "n": len(nets), "net_median_bps": (statistics.median(nets) if nets else None),
            "net_moyen_bps": (statistics.fmean(nets) if nets else None)}


def direction_ab(episodes: list[dict]) -> dict:
    """continuation (+1) vs réversion (−1), les DEUX réellement rejouées."""
    return {"continuation": replay_direction(episodes, sens=1), "reversion": replay_direction(episodes, sens=-1)}


def execution_ab(episodes: list[dict], *, modeles=("taker", "maker_risk_averse")) -> dict:
    """A/B d'exécution : recalcule le net sous chaque modèle (taker = fill plein ; maker = fill partiel selon
    le modèle de file). Retourne le net médian par modèle."""
    from recherche_18h_mecanismes import maker_risk_averse_fill, maker_probabiliste_fill
    sortie = {}
    for m in modeles:
        nets = []
        for e in episodes:
            gross = float(e.get("gross_bps") or 0.0)
            cout = float(e.get("cout_ar_bps") or 0.0)
            if m == "taker":
                frac = 1.0
            elif m == "maker_risk_averse":
                frac = maker_risk_averse_fill(float(e.get("queue_sz") or 0.0), float(e.get("vol_traversant_sz") or 0.0))
            else:
                frac = maker_probabiliste_fill(float(e.get("queue_sz") or 0.0), float(e.get("vol_traversant_sz") or 0.0))
            if frac <= 0:
                continue                          # no-fill : l'épisode ne compte pas comme trade rempli
            nets.append((gross - cout) * frac)
        sortie[m] = {"n": len(nets), "net_median_bps": (statistics.median(nets) if nets else None)}
    return sortie


__all__ = ["decision_hash", "parite", "replay_direction", "direction_ab", "execution_ab"]
