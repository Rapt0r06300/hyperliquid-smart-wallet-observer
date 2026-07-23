"""LEAD-LAG SHADOW — Binance mène, HL suit ? La mesure NETTE après coûts (23/07, chantier ARB).

L'ancien détecteur d'arb était INVALIDE (base persistante = mapping/quote périmée). Le collecteur BBO
donne maintenant une TAPE propre (chaque message, horloge MONOTONE, mapping exact). Ce module y mesure
l'expérience que Flo a cadrée :

    CHOC exécutable sur Binance (|Δ mid| ≥ seuil)
      -> réaction FUTURE de HL à 50/100/250/500/1000 ms (horloge monotone, jamais l'horloge exchange)
      -> ENTRÉE au bid/ask HL réellement dispo (on paie le demi-spread, aller-retour)
      -> profondeur au top (capacité)
      -> frais + spread + slippage
      -> PnL NET forward par horizon.

DISCIPLINE : seuils GELÉS avant la fenêtre live-forward ; les coins non rentables sont GARDÉS comme
CONTRÔLE (si le « contrôle » gagne autant, c'est un artefact d'horloge, pas un edge). Aucune donnée
inventée : sans réaction HL à l'horizon voulu, l'événement est écarté, jamais comblé. PAPER/shadow only.
"""
from __future__ import annotations

import bisect
import json
import statistics as st
from pathlib import Path
from typing import Any

TAPE = Path("runtime") / "data" / "bbo_tape.jsonl"
#: GELÉS (avant tout live-forward). Un choc = mouvement Binance franc ; coûts = frais + slippage
#: (le demi-spread HL réel est AJOUTÉ par-dessus, lu dans la tape).
SEUIL_CHOC_BPS = 8.0
FRAIS_SLIPPAGE_BPS = 6.0
HORIZONS_MS = (50.0, 100.0, 250.0, 500.0, 1000.0)
MIN_CHOCS = 30


def charger_tape(root: str | Path) -> dict[str, dict[str, list]]:
    """{coin: {'HL': [(recu_ns, mid, bid, ask)], 'BIN': [(recu_ns, mid)]}} trié. Ligne cassée -> sautée."""
    from collections import defaultdict
    p = Path(root) / TAPE
    if not p.exists():
        return {}
    par: dict[str, dict[str, list]] = defaultdict(lambda: {"HL": [], "BIN": []})
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l)
            coin = str(d["coin"]).upper()
            r = int(d["recu_ns"]); mid = float(d["mid"])
        except (KeyError, TypeError, ValueError):
            continue
        if d.get("venue") == "HL":
            par[coin]["HL"].append((r, mid, float(d.get("bid") or mid), float(d.get("ask") or mid)))
        elif d.get("venue") == "BIN":
            par[coin]["BIN"].append((r, mid))
    for c in par:
        par[c]["HL"].sort(); par[c]["BIN"].sort()
    return dict(par)


def _hl_a(hl: list, t_ns: int) -> tuple | None:
    """Le dernier événement HL à/avant `t_ns` (mid, bid, ask). None si aucun."""
    i = bisect.bisect_right([e[0] for e in hl], t_ns) - 1
    return hl[i] if i >= 0 else None


def net_par_horizon(hl: list, bn: list, *, seuil_choc_bps: float, frais_slippage_bps: float,
                    horizons_ms) -> dict[float, list[float]]:
    """Pour chaque choc Binance, le net forward HL par horizon. Cœur PUR (testable sans réseau)."""
    out: dict[float, list[float]] = {h: [] for h in horizons_ms}
    for i in range(1, len(bn)):
        if bn[i - 1][1] <= 0:
            continue
        choc = (bn[i][1] - bn[i - 1][1]) / bn[i - 1][1] * 1e4
        if abs(choc) < seuil_choc_bps:
            continue
        t0 = bn[i][0]
        e0 = _hl_a(hl, t0)
        if e0 is None or e0[1] <= 0:
            continue
        direction = 1.0 if choc > 0 else -1.0
        demi_spread = (e0[3] - e0[2]) / 2.0 / e0[1] * 1e4     # demi-spread HL RÉEL à l'entrée
        cout = 2.0 * max(0.0, demi_spread) + frais_slippage_bps
        for h in horizons_ms:
            eh = _hl_a(hl, t0 + int(h * 1e6))
            if eh is None or eh[0] <= e0[0]:                  # pas de tick HL après l'entrée -> écarté
                continue
            reaction = (eh[1] - e0[1]) / e0[1] * 1e4 * direction
            out[h].append(reaction - cout)
    return out


def backtest(root: str | Path = ".", *, seuil_choc_bps: float = SEUIL_CHOC_BPS,
             frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS, horizons_ms=HORIZONS_MS,
             coins_controle: tuple = (), min_chocs: int = MIN_CHOCS) -> dict[str, Any]:
    """Le verdict lead-lag NET par horizon, coins de test vs coins de CONTRÔLE. NEED_MORE_DATA
    tant qu'il n'y a pas assez de chocs (un edge sur peu de chocs est du bruit)."""
    tape = charger_tape(root)
    controle = {c.upper() for c in coins_controle}
    test_nets: dict[float, list[float]] = {h: [] for h in horizons_ms}
    ctrl_nets: dict[float, list[float]] = {h: [] for h in horizons_ms}
    for coin, ev in tape.items():
        if len(ev["BIN"]) < 3 or len(ev["HL"]) < 3:
            continue
        nets = net_par_horizon(ev["HL"], ev["BIN"], seuil_choc_bps=seuil_choc_bps,
                               frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons_ms)
        cible = ctrl_nets if coin in controle else test_nets
        for h in horizons_ms:
            cible[h].extend(nets[h])
    n_test = max((len(v) for v in test_nets.values()), default=0)
    if n_test < min_chocs:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "chocs_test": n_test,
                "cible": min_chocs, "detail": "pas assez de chocs — laisser le BBO tourner (live-forward)."}

    def _resume(d):
        return {h: {"net_moyen_bps": round(st.mean(v), 3), "n": len(v)} for h, v in d.items() if v}

    par_h = _resume(test_nets)
    gagnants = {h: r for h, r in par_h.items() if r["net_moyen_bps"] > 0}
    return {"strategie": "lead_lag_shadow", "statut": "PROMETTEUR" if gagnants else "PAS_D_EDGE",
            "seuils_geles": {"choc_bps": seuil_choc_bps, "frais_slippage_bps": frais_slippage_bps},
            "net_par_horizon": par_h, "controle_par_horizon": _resume(ctrl_nets),
            "avertissement": "Net APRÈS demi-spread HL réel + frais/slippage. Si le CONTRÔLE gagne "
                             "autant, c'est un artefact d'horloge, pas un edge. Sub-seconde = souvent "
                             "gagné par des racers co-localisés qu'on ne bat pas."}


__all__ = ["SEUIL_CHOC_BPS", "FRAIS_SLIPPAGE_BPS", "HORIZONS_MS", "charger_tape",
           "net_par_horizon", "backtest"]
