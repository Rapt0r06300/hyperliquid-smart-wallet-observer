"""ALPHA — matrice d'INCRÉMENT de features (P3, state-first) : une feature qui n'améliore pas le NET OOS = DROP.

Les 6 combinaisons obligatoires : STATE seul, FLOW seul, STATE+FLOW, WALLET+STATE, WALLET+STATE+FLOW,
ANTICIPATION+STATE+FLOW. On mesure le NET OOS de chaque combo (seuils gelés en découverte, mesure sur OOS
intact) et l'INCRÉMENT d'ajouter chaque brique. Règle : incrément ≤ 0 → DROP.

STATE-FIRST : on part de l'état (imbalance/depth), on n'ajoute le FLOW (OFI) que s'il ajoute du NET OOS.
Les combos WALLET+* et ANTICIPATION+* exigent d'ALIGNER des sources multiples (fills wallet / Binance) sur la
MÊME série de carnet — indisponible ici (fenêtres et coins disjoints) → sorties `UNMEASURABLE`, pas inventées.

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.research import ofi_microprice as _ofi

UNMEASURABLE = "UNMEASURABLE"

#: Mapping des briques nommées vers les clés de features causales (l2_book).
BRIQUES = {"STATE": "imb_depth", "FLOW": "ofi_l1"}


def _seuil_gele(feats: Sequence[Mapping[str, Any]], cle: str, *, quantile: float, coupe: int) -> float | None:
    vals = sorted(abs(f[cle]) for f in feats[:coupe]
                  if isinstance(f.get(cle), (int, float)) and not math.isnan(f[cle]))
    if len(vals) < 30:
        return None
    return vals[min(len(vals) - 1, int(quantile * len(vals)))]


def net_combo(feats: Sequence[Mapping[str, Any]], cles: Sequence[str], seuils: Mapping[str, float], *,
              horizon_pas: int, fee_bps: float, dt_max: float = 60.0) -> dict[str, Any]:
    """Signal-conjonction : on trade quand TOUTES les clés dépassent leur seuil ET s'accordent en direction.
    Entrée mid(t)→mid(t+h), non chevauchant, anti-trou ; net = markout − (frais + spread)."""
    n = len(feats)
    events: list[float] = []
    t = 0
    while t < n - horizon_pas:
        f = feats[t]
        vals = [f.get(k) for k in cles]
        ok = all(isinstance(v, (int, float)) and not math.isnan(v) and abs(v) >= seuils[k]
                 for v, k in zip(vals, cles))
        signs = {1 if v > 0 else -1 for v in vals} if ok else set()
        if ok and len(signs) == 1 and all(0 < feats[t + k]["dt_prev"] <= dt_max for k in range(1, horizon_pas + 1)):
            direction = signs.pop()
            mid0, mid1 = f["mid"], feats[t + horizon_pas]["mid"]
            gross = direction * (mid1 / mid0 - 1.0) * 1e4
            cout = fee_bps + (f["spread_bps"] if not math.isnan(f["spread_bps"]) else 0.0)
            events.append(gross - cout)
            t += horizon_pas
        else:
            t += 1
    if not events:
        return {"n": 0, "net_bps": None}
    return {"n": len(events), "net_bps": round(sum(events) / len(events), 4)}


def experience_combo(feats: Sequence[Mapping[str, Any]], briques: Sequence[str], *, horizon_pas: int = 2,
                     fee_bps: float = 9.0, quantile: float = 0.75, fraction_decouverte: float = 0.5) -> dict[str, Any]:
    """NET OOS d'une combo de briques mesurables (STATE/FLOW). UNMEASURABLE si une brique n'est pas alignable."""
    cles = []
    for b in briques:
        if b not in BRIQUES:
            return {"briques": list(briques), "statut": UNMEASURABLE, "net_bps_oos": UNMEASURABLE,
                    "raison": "%s exige un alignement multi-source indisponible (wallet/Binance vs carnet)" % b}
        cles.append(BRIQUES[b])
    coupe = int(len(feats) * fraction_decouverte)
    seuils = {}
    for k in cles:
        s = _seuil_gele(feats, k, quantile=quantile, coupe=coupe)
        if s is None:
            return {"briques": list(briques), "statut": UNMEASURABLE, "net_bps_oos": UNMEASURABLE,
                    "raison": "pas assez de valeurs pour geler le seuil de %s" % k}
        seuils[k] = s
    oos = net_combo(feats[coupe:], cles, seuils, horizon_pas=horizon_pas, fee_bps=fee_bps)
    return {"briques": list(briques), "statut": "MEASURABLE" if oos["n"] else UNMEASURABLE,
            "n_oos": oos["n"], "net_bps_oos": oos["net_bps"], "seuils_geles": seuils}


COMBOS = (("STATE",), ("FLOW",), ("STATE", "FLOW"), ("WALLET", "STATE"),
          ("WALLET", "STATE", "FLOW"), ("ANTICIPATION", "STATE", "FLOW"))


def matrice_increment(feats: Sequence[Mapping[str, Any]], *, horizon_pas: int = 2, fee_bps: float = 9.0) -> dict[str, Any]:
    """Évalue les 6 combos + l'incrément FLOW-sur-STATE. Règle DROP : incrément NET OOS ≤ 0 → on jette la brique."""
    res = {"_".join(c): experience_combo(feats, c, horizon_pas=horizon_pas, fee_bps=fee_bps) for c in COMBOS}
    net_state = res["STATE"].get("net_bps_oos")
    net_sf = res["STATE_FLOW"].get("net_bps_oos")
    increment_flow = None
    decision_flow = UNMEASURABLE
    if isinstance(net_state, (int, float)) and isinstance(net_sf, (int, float)):
        increment_flow = round(net_sf - net_state, 4)
        decision_flow = "KEEP_FLOW" if increment_flow > 0 else "DROP_FLOW"
    return {"combos": res, "increment_flow_sur_state_bps": increment_flow,
            "decision_flow": decision_flow,
            "note": "WALLET/ANTICIPATION = UNMEASURABLE ici (alignement multi-source indisponible)"}


def features_depuis_l2book(serie: Sequence[Mapping[str, float]], *, dt_max: float = 60.0) -> list[dict[str, Any]]:
    """Raccourci : features causales OFI/microprice/imbalance depuis une série l2_book."""
    return _ofi.features_causaux(serie, dt_max_feat=dt_max)


__all__ = ["BRIQUES", "COMBOS", "net_combo", "experience_combo", "matrice_increment", "features_depuis_l2book"]
