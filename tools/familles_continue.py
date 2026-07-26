"""FAMILLES ÉLARGIES + HORIZONS SUBSECONDE (LABO-CONTINU-FINAL FINAL-8, Flo 26/07).

HONNÊTETÉ AVANT TOUT — le moteur exact calcule le net à partir de (direction × horizon) via le forward-mid
top-of-book. Le champ `family` NE change PAS ce calcul par lui-même : il ne devient une vraie hypothèse que
s'il porte un PRÉDICAT réel sur l'épisode (order-flow, sweep, liquidation, funding, momentum, z-score…).
Ce module fournit donc un prédicat par famille : quand la donnée porte la feature, la famille SÉLECTIONNE un
sous-ensemble d'épisodes réellement différent (→ net réellement différent) ; quand la feature est ABSENTE,
la famille renvoie 0 épisode → DATA_MISSING honnête, jamais un net générique mal étiqueté. Ainsi « élargir
les familles » n'invente aucun edge : ça teste plus large ET ça alimente l'analyse permanente des refus.

Les horizons subseconde ne produisent un net que si le corpus porte un forward-mid à cet horizon ; sinon
UNMEASURABLE honnête (résolution insuffisante), ce qui est une information de recherche valable. 0 ordre.
"""
from __future__ import annotations

#: Familles élargies. GENERIC = pas de prédicat (comportement top-of-book historique). Les autres exigent
#: une feature d'épisode ; sans elle → 0 épisode (DATA_MISSING), documenté dans l'analyse des refus.
FAMILLES = ("GENERIC", "OFI", "SWEEP", "BOOK_IMBALANCE", "MICROPRICE_DRIFT", "TRADE_RUN",
            "LIQUIDATION_FADE", "FUNDING_TILT", "MOMENTUM_MULTI", "MEANREV_BAND", "CROSS_LEADLAG")

#: Horizons incluant la subseconde (ms). Réels si le corpus porte le forward-mid correspondant.
HORIZONS_SUBSEC_MS = (100, 250, 500, 1000, 2000, 5000, 15000, 30000, 60000)

#: Feature d'épisode requise par famille (None = aucune → GENERIC).
FEATURE_REQUISE = {
    "GENERIC": None, "OFI": "ofi", "SWEEP": "sweep", "BOOK_IMBALANCE": "imbalance",
    "MICROPRICE_DRIFT": "microprice", "TRADE_RUN": "run_len", "LIQUIDATION_FADE": "is_liquidation",
    "FUNDING_TILT": "funding_bps", "MOMENTUM_MULTI": "ret_prev", "MEANREV_BAND": "zscore",
    "CROSS_LEADLAG": "lead_ret",
}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def predicat(ep: dict, family: str | None, seuil) -> bool:
    """True si l'épisode `ep` qualifie pour `family` au `seuil` donné. Prédicat RÉEL : sans la feature
    requise, renvoie False (la famille ne peut pas être testée sur cette donnée -> DATA_MISSING honnête)."""
    fam = family or "GENERIC"
    feat = FEATURE_REQUISE.get(fam, None)
    if feat is None:                                   # GENERIC / famille inconnue -> aucun filtre supplémentaire
        return True
    if feat not in ep:                                 # donnée absente -> la famille n'est PAS testable ici
        return False
    s = _num(seuil)
    if fam in ("SWEEP", "LIQUIDATION_FADE"):           # features booléennes
        return bool(ep.get(feat))
    if fam == "MICROPRICE_DRIFT":                       # présence + dérive vs mid mesurable
        mp, mid = _num(ep.get("microprice")), _num(ep.get("mid"))
        if mp is None:
            return False
        if mid is None:
            bid, ask = _num(ep.get("bid")), _num(ep.get("ask"))
            mid = (bid + ask) / 2.0 if (bid is not None and ask is not None) else None
        return mid is not None and abs(mp - mid) > 0
    val = _num(ep.get(feat))
    if val is None:
        return False
    if s is None:
        return True
    if fam == "OFI":
        return abs(val) >= s
    if fam == "BOOK_IMBALANCE":
        return abs(val) >= s / 100.0                    # imbalance normalisé [0..1]
    if fam == "TRADE_RUN":
        return val >= s
    if fam == "FUNDING_TILT":
        return abs(val) >= s / 10.0
    if fam == "MOMENTUM_MULTI":
        return abs(val) >= s / 1e4                       # ret en fraction
    if fam == "MEANREV_BAND":
        return abs(val) >= s / 10.0
    if fam == "CROSS_LEADLAG":
        return abs(val) >= s / 1e4
    return True


def horizons_pour(corpus: list[dict] | None = None) -> tuple[int, ...]:
    """Horizons à explorer : ceux réellement portés par le corpus (forward-mid présent) + subseconde probée.
    Si le corpus ne porte aucun forward-mid, renvoie la grille subseconde complète (elles ressortiront
    UNMEASURABLE, ce qui est une info honnête)."""
    presents = set()
    for ep in (corpus or [])[:2000]:
        fwd = ep.get("fwd_mid") or {}
        for k in fwd:
            try:
                presents.add(int(k))
            except (TypeError, ValueError):
                continue
    base = tuple(sorted(presents)) if presents else HORIZONS_SUBSEC_MS
    # on garantit au moins un point subseconde pour l'analyse permanente
    return tuple(sorted(set(base) | {100, 500}))


__all__ = ["FAMILLES", "HORIZONS_SUBSEC_MS", "FEATURE_REQUISE", "predicat", "horizons_pour"]
