"""RECHERCHE ARBITRAGE — la VRAIE grille du fade de dislocation HL, PAS le SL/TP + filtres COPY.

Le bug du 22/07 (comme le carry) : les candidats arbitrage ont 0 % des champs de filtre COPY
(`signal_age`/`consensus`/`liquidity`) → 3 presets sur 4 vidaient la population → `0.0` partout.

Le mécanisme réel de CES candidats : `FADE_DISLOCATION_HL` — quand le prix HL décroche de
`ecart_prix_bps`, on parie qu'il REVIENT (mean-reversion), dans la `direction` du candidat. C'est
DIRECTIONNEL (jambe HL seule ; l'arbitrage 2-jambes à convergence, lui, est cherché ailleurs par
`cross_venue` sur la série de dispersion). Sa vraie grille balaie donc :

    seuil d'écart d'entrée (bps)  ×  horizon de détention (min)

évaluée par le simulateur VALIDÉ `simulate_exit_on_path` (mêmes chiffres que le replay), au COÛT
EXÉCUTABLE (~19,5 bps, `arb_executable`) et non au mid, avec le PLAFOND anti-aberrant
(`MAX_ECART_PLAUSIBLE_BPS` : un |écart| absurde = mauvais appariement, jamais un edge). Métrique =
net MOYEN par trade. Honnête : un écart illisible ou un coin sans marks = non mesurable, jamais
compté. REPLAY-only, aucun ordre.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from hl_observer.backtesting.ab_flag_replay import (load_jsonl, marks_by_coin, simulate_exit_on_path)
from hl_observer.funding.arb_executable import MAX_ECART_PLAUSIBLE_BPS, cout_executable_bps
from hl_observer.paper_trading.sl_tp import SLTPConfig

MIN_CANDIDATS = 30
MIN_TRADES = 20
COUT_ARB_BPS = cout_executable_bps()             # ~19,5 bps ALLER-RETOUR (exécutable, pas le mid)
#: `simulate_exit_on_path` facture `cost_bps` À L'ENTRÉE ET À LA SORTIE (×2). Notre coût est déjà
#: l'aller-retour complet → on passe la MOITIÉ par jambe pour ne PAS le compter deux fois.
COUT_ARB_PAR_JAMBE_BPS = COUT_ARB_BPS / 2.0
#: SL/TP volontairement HORS D'ATTEINTE : on tient jusqu'à l'horizon et on mesure la réversion
#: réelle (le fade « à la sortie d'horizon »), sans injecter de TP/SL arbitraire.
_TENIR = SLTPConfig(stop_loss_bps=1e9, take_profit_bps=1e9)


def _base(root: str | Path) -> Path:
    p = Path(root) / "runtime" / "replay" / "_merged"
    return p if (p / "candidates.jsonl").exists() else Path(root) / "runtime" / "replay"


def charger_arb(root: str | Path) -> tuple[list[dict], dict]:
    """Candidats arbitrage (fade de dislocation) + index des marks HL. Aucun réseau."""
    base = _base(root)
    if not (base / "candidates.jsonl").exists():
        return [], {}
    from hl_observer.ops.strategie_candidat import strategie_effective
    cands = [c for c in load_jsonl(str(base / "candidates.jsonl"))
             if isinstance(c, dict) and strategie_effective(c) == "arbitrage"]
    marks = marks_by_coin(load_jsonl(str(base / "marks.jsonl"))) if (base / "marks.jsonl").exists() else {}
    return cands, marks


def grille_arb() -> Iterator[dict[str, Any]]:
    """Le VRAI espace du fade : seuil d'écart d'entrée × horizon. Rien de copy, rien d'inventé."""
    for ecart_min in (20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 160.0, 220.0):
        for horizon in (15.0, 30.0, 60.0, 120.0, 240.0):
            yield {"ecart_min_bps": ecart_min, "horizon_min": horizon}


def evaluer_arb(cands: list[dict], marks: dict, config: dict[str, Any]) -> dict[str, Any]:
    """Net moyen (USD) du fade sur les candidats dont |écart| ∈ [seuil, plafond]. On simule la
    `direction` du candidat au COÛT EXÉCUTABLE ; un coin sans marks ou un écart illisible = non
    mesurable, exclu (jamais compté d'un seul côté)."""
    emin = float(config["ecart_min_bps"])
    hz = float(config["horizon_min"])
    nets: list[float] = []
    ecartes = 0
    for c in cands:
        try:
            ecart = abs(float(c.get("ecart_prix_bps") or 0.0))
            entry = float(c.get("current_mid") or 0.0)
            ts = float(c.get("recorded_at") or 0.0)
        except (TypeError, ValueError):
            continue
        side = str(c.get("direction") or "").upper()
        if ecart > MAX_ECART_PLAUSIBLE_BPS:          # mauvais appariement -> jamais un edge
            ecartes += 1
            continue
        if ecart < emin or side not in ("LONG", "SHORT") or entry <= 0 or ts <= 0:
            continue
        pnl = simulate_exit_on_path(side=side, entry_price=entry,
                                    path=marks.get(str(c.get("coin") or "").upper(), []),
                                    entry_ts=ts, config=_TENIR, horizon_min=hz,
                                    cost_bps=COUT_ARB_PAR_JAMBE_BPS)   # ×2 dans le simulateur = 19,5 total
        if pnl is not None:
            nets.append(pnl)
    return {"net_total_usd": round(sum(nets), 6), "n_trades": len(nets),
            "net_moyen_usd": round(sum(nets) / len(nets), 6) if nets else 0.0,
            "ecartes_aberrants": ecartes}


def chercher_arbitrage(root: str | Path, *, budget_s: float | None = None) -> dict[str, Any]:
    """Balaie la grille et retient les seuils au net MOYEN positif, sur assez de trades. Compatible
    RECAP. Coût EXÉCUTABLE (pas le mid) : c'est la vérité gênante du +0,54 $, mesurée au bon prix."""
    cands, marks = charger_arb(root)
    if len(cands) < MIN_CANDIDATS:
        return {"statut": "INSUFFISANT", "strategie": "arbitrage", "essais": [],
                "motif": "%d candidats arbitrage (<%d) — laisser le venues-collector tourner"
                         % (len(cands), MIN_CANDIDATS)}
    essais: list[dict] = []
    promus: list[dict] = []
    for cfg in grille_arb():
        r = evaluer_arb(cands, marks, cfg)
        vivant = r["net_moyen_usd"] > 0.0 and r["n_trades"] >= MIN_TRADES
        essais.append({"config": cfg, "verdict": "PROMU" if vivant else "REJETE",
                       "nets": {"moyen_usd": r["net_moyen_usd"], "total_usd": r["net_total_usd"],
                                "stress": r["net_moyen_usd"]}, "n_trades": r["n_trades"]})
        if vivant:
            promus.append({"config": cfg, "rang": "ARGENT",
                           "nets": {"moyen_usd": r["net_moyen_usd"], "stress": r["net_moyen_usd"],
                                    "n_trades": r["n_trades"]}})
    gagnant = max(promus, key=lambda p: p["nets"]["stress"])["config"] if promus else None
    return {"statut": "PROMU" if promus else "ESPACE_EPUISE", "strategie": "arbitrage",
            "essais": essais, "promus": promus, "gagnant": gagnant, "n_candidats": len(cands),
            "honnetete": "fade directionnel au COÛT EXÉCUTABLE (%.1f bps), plafond anti-aberrant "
                         "%.0f bps ; l'arbitrage 2-jambes à convergence est cherché par cross_venue"
                         % (COUT_ARB_BPS, MAX_ECART_PLAUSIBLE_BPS)}


__all__ = ["charger_arb", "grille_arb", "evaluer_arb", "chercher_arbitrage", "COUT_ARB_BPS"]
