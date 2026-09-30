"""BACKTEST DU FADE DE LIQUIDATIONS — juger le forced-flow (expérience #2, 23/07).

Le collecteur `tools/collecter_overshoots.py` enregistre chaque OVERSHOOT (mid loin de l'oracle =
forced-flow candidat) PUIS son chemin de prix forward (15/30/60/120 s). Ce module mesure : en fadant
l'overshoot (parier le retour vers l'oracle), gagne-t-on APRÈS coûts, par coin, hors échantillon ?

CE QUI REND CE BACKTEST HONNÊTE
  * **La réversion, pas l'overshoot.** Un mid-cap illiquide a un mid en permanence décalé de l'oracle
    (spread) SANS jamais revenir : son « overshoot » est du bruit, pas une purge. Seule la RÉVERSION
    mesurée (mid_fwd → oracle) distingue la vraie liquidation. On juge sur elle.
  * **Coûts pleins.** net = réversion − `cout_bps` (aller-retour taker HL + spread). Un fade qui ne
    bat pas ses coûts est REJETÉ, jamais maquillé.
  * **BTC exclu** (book trop profond, overshoot < spread — mesure externe walk-forward).
  * **OOS chronologique.** On coupe les événements en deux moitiés temporelles ; un edge doit tenir
    sur la 2ᵉ (jamais vu à la calibration). Sous `MIN_EVENEMENTS`, verdict = NEED_MORE_DATA — on ne
    tranche pas sur du bruit.
  * **Aucune donnée inventée.** Un événement sans le mid forward voulu est écarté, pas comblé.

PAPER only : mesurer une réversion n'est pas passer un ordre.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SORTIE = Path("runtime") / "data" / "overshoots_liquidation.jsonl"
#: coût all-in d'un aller-retour de fade (2 exécutions taker HL ~4,5 + spread mid-cap ~6). Conservateur.
COUT_FADE_BPS = 15.0
#: sous ce |overshoot|, ce n'est pas une purge, c'est du bruit de spread : on ne fade pas.
MIN_OVERSHOOT_BPS = 40.0
#: sous ce nombre d'événements, un classement est du bruit (leçon MinTRL / PBO).
MIN_EVENEMENTS = 50
BTC = "BTC"


def charger_evenements(root: str | Path) -> list[dict]:
    p = Path(root) / SORTIE
    if not p.exists():
        return []
    out: list[dict] = []
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("coin"):
            out.append(d)
    return out


def reversion_bps(event: dict, *, horizon_s: float) -> float | None:
    """Réversion réalisée en fadant l'overshoot, à l'horizon donné (bps du mid d'entrée).

    Fade d'un SELL_OVERSHOOT (mid SOUS l'oracle) = on est LONG : on gagne si le mid REMONTE. Retour
    `None` si le mid forward de cet horizon n'a pas été capturé (jamais comblé)."""
    try:
        m0 = float(event["mid_at_event"])
        mf = event.get("mid_fwd_%gs" % horizon_s)
        ov = float(event["overshoot_bps"])
    except (KeyError, TypeError, ValueError):
        return None
    if mf is None or m0 <= 0:
        return None
    signe = 1.0 if ov < 0 else -1.0                    # fade : parier le retour vers l'oracle
    return signe * (float(mf) - m0) / m0 * 1e4


def _net(evenements: list[dict], *, horizon_s: float, cout_bps: float,
         min_overshoot_bps: float) -> dict[str, list[float]]:
    """{coin: [net_bps par événement]} = réversion − coût, sur les overshoots assez francs, hors BTC."""
    from collections import defaultdict
    par: dict[str, list[float]] = defaultdict(list)
    for e in evenements:
        coin = str(e.get("coin") or "").upper()
        if coin == BTC or not coin:
            continue
        try:
            ov = abs(float(e.get("overshoot_bps")))
        except (TypeError, ValueError):
            continue
        if ov < min_overshoot_bps:
            continue
        r = reversion_bps(e, horizon_s=horizon_s)
        if r is not None:
            par[coin].append(r - cout_bps)
    return par


def backtest(root: str | Path = ".", *, horizon_s: float = 30.0, cout_bps: float = COUT_FADE_BPS,
             min_overshoot_bps: float = MIN_OVERSHOOT_BPS,
             min_evenements: int = MIN_EVENEMENTS) -> dict[str, Any]:
    """Le verdict du fade, par coin, coûts déduits, avec coupe OOS chronologique. Descriptif tant que
    `min_evenements` n'est pas atteint — jamais une promesse sur du bruit."""
    evs = sorted(charger_evenements(root), key=lambda e: float(e.get("ts_ms") or 0.0))
    utilisables = [e for e in evs if reversion_bps(e, horizon_s=horizon_s) is not None
                   and abs(float(e.get("overshoot_bps") or 0.0)) >= min_overshoot_bps
                   and str(e.get("coin") or "").upper() != BTC]
    n = len(utilisables)
    if n < min_evenements:
        return {"strategie": "fade_liquidation", "statut": "NEED_MORE_DATA",
                "evenements_utilisables": n, "cible": min_evenements, "horizon_s": horizon_s,
                "detail": "%d événement(s) fadables (< %d) : laisser le collecteur tourner. "
                          "Aucun verdict sur si peu — ce serait du bruit." % (n, min_evenements)}
    mid = n // 2
    ts_coupe = float(utilisables[mid].get("ts_ms") or 0.0)
    ins = [e for e in utilisables if float(e.get("ts_ms") or 0.0) < ts_coupe]
    oos = [e for e in utilisables if float(e.get("ts_ms") or 0.0) >= ts_coupe]

    def _resume(lot: list[dict]) -> dict:
        par = _net(lot, horizon_s=horizon_s, cout_bps=cout_bps, min_overshoot_bps=min_overshoot_bps)
        nets = [x for v in par.values() for x in v]
        gagnants = {c: round(sum(v) / len(v), 3) for c, v in par.items()
                    if len(v) >= 3 and sum(v) / len(v) > 0}
        return {"n": len(nets), "net_moyen_bps": round(sum(nets) / len(nets), 3) if nets else 0.0,
                "coins_net_positif": dict(sorted(gagnants.items(), key=lambda kv: -kv[1]))}

    r_is, r_oos = _resume(ins), _resume(oos)
    edge_oos = r_oos["net_moyen_bps"] > 0 and bool(r_oos["coins_net_positif"])
    return {"strategie": "fade_liquidation", "statut": "PROMETTEUR_OOS" if edge_oos else "PAS_D_EDGE_OOS",
            "horizon_s": horizon_s, "cout_bps": cout_bps, "min_overshoot_bps": min_overshoot_bps,
            "in_sample": r_is, "out_of_sample": r_oos,
            "avertissement": "Réversion nette de coûts ; edge validé seulement s'il tient en OOS ET "
                             "survit ensuite au PBO. BTC exclu. Mid-caps illiquides = à re-coster au "
                             "vrai carnet avant toute promesse."}


__all__ = ["charger_evenements", "reversion_bps", "backtest", "COUT_FADE_BPS",
           "MIN_OVERSHOOT_BPS", "MIN_EVENEMENTS", "SORTIE"]
