"""INVARIANTS ÉCONOMIQUES du runtime EXPERIMENTAL_PAPER (Flo 26/07). Cœur PUR, sans effet de bord.

Garantit que chaque PnL/ROI paper repose sur une exécution POSSIBLE et un capital COHÉRENT :
  * validation numérique CENTRALE (math.isfinite) — refuse NaN/inf, notionnel<=0, horizon<=0, latence<0 ;
  * gate ROI RÉELLE — ROI_NON_MESURABLE (NaN/inf/absent) et ROI_INSUFFISANT (< seuil) ;
  * gate BUDGET GLOBAL — somme de TOUTES les positions ouvertes (tous moteurs) vs le budget total ;
  * exécution honnête — prix de sortie exécutable (long au bid, short à l'ask) et décomposition des coûts
    SANS double-compter un spread déjà intégré au prix.
0 réseau, 0 ordre, 0 clé. Utilisé par admettre() et par les fermetures.
"""
from __future__ import annotations

import math

#: champs numériques d'un signal qui DOIVENT être finis avant toute décision. `roi_annuel_pct` a sa PROPRE
#: gate (roi_gate -> ROI_NON_MESURABLE), il est donc exclu de ce validateur générique.
CHAMPS_SIGNAL = ("prix_entree", "notional_usd", "cout_entree_bps", "edge_estime_bps",
                 "pnl_attendu_usd", "ts_signal_ms", "hold_h", "d_bps_h", "base_entree_bps", "latence_ms")


def est_fini(x) -> bool:
    """True seulement si x est un nombre RÉEL fini (ni None, ni NaN, ni ±inf, ni bool déguisé)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def valider_numerique(champs: dict) -> tuple[bool, str | None]:
    """Refuse tout champ absent / NaN / inf. Rend (True, None) ou (False, '<CHAMP>_NON_FINI')."""
    for nom, v in champs.items():
        if v is None:
            return False, "%s_ABSENT" % nom.upper()
        if not est_fini(v):
            return False, "%s_NON_FINI" % nom.upper()
    return True, None


def valider_signal(sig) -> tuple[bool, str | None]:
    """Validation numérique CENTRALE + bornes physiques : notionnel>0, horizon>0, latence>=0. La finitude
    du prix est vérifiée ici (NaN/inf refusés) ; sa POSITIVITÉ (prix>0) reste la propriété de la gate
    dédiée `PRIX_NON_EXECUTABLE` en aval, pour ne pas changer le motif de refus historique."""
    champs = {c: getattr(sig, c, None) for c in CHAMPS_SIGNAL}
    ok, motif = valider_numerique(champs)
    if not ok:
        return False, motif
    if float(sig.notional_usd) <= 0:
        return False, "NOTIONAL_NON_POSITIF"
    if float(sig.hold_h) <= 0:
        return False, "HORIZON_NON_POSITIF"
    if float(sig.latence_ms) < 0:
        return False, "LATENCE_NEGATIVE"
    return True, None


def roi_gate(roi_annuel_pct, *, min_roi: float) -> tuple[bool, str | None]:
    """Gate ROI RÉELLE (le seuil déclaré doit être APPLIQUÉ). NaN/inf/absent -> ROI_NON_MESURABLE."""
    if roi_annuel_pct is None or not est_fini(roi_annuel_pct):
        return False, "ROI_NON_MESURABLE"
    if float(roi_annuel_pct) < float(min_roi):
        return False, "ROI_INSUFFISANT"
    return True, None


def budget_global_utilise(store: dict) -> float:
    """Somme des notionnels de TOUTES les positions ouvertes (tous moteurs confondus)."""
    return sum(float(p.get("notional_usd") or 0.0) for p in (store.get("ouvertes") or {}).values())


def budget_global_ok(store: dict, notional: float, *, budget_total: float) -> tuple[bool, str | None]:
    """Refuse si la NOUVELLE position ferait dépasser le budget total GLOBAL (au-delà des limites par moteur)."""
    if not est_fini(notional) or notional <= 0:
        return False, "NOTIONAL_NON_POSITIF"
    if budget_global_utilise(store) + float(notional) > float(budget_total) + 1e-9:
        return False, "BUDGET_GLOBAL_DEPASSE"
    return True, None


def prix_sortie_executable(sens: int, *, bid: float, ask: float) -> float | None:
    """Prix de sortie RÉELLEMENT exécutable : on CLÔTURE en croisant. Un LONG se ferme en VENDANT au BID ;
    un SHORT se ferme en RACHETANT à l'ASK. None si le carnet est illisible."""
    if not (est_fini(bid) and est_fini(ask) and ask > bid > 0):
        return None
    return float(bid) if int(sens) > 0 else float(ask)


def cout_sortie_sans_double_spread(*, frais_bps: float, slippage_bps: float, impact_bps: float = 0.0,
                                   latence_bps: float = 0.0) -> float:
    """Coût de sortie quand le prix EST DÉJÀ exécutable (bid/ask) : le spread est DÉJÀ payé par le
    croisement, on ne le re-soustrait PAS. On ajoute seulement commission + slippage AU-DELÀ du top-of-book
    + impact + latence. Rend le coût en bps (jamais le demi-spread)."""
    return float(frais_bps) + float(slippage_bps) + float(impact_bps) + float(latence_bps)


def roi_sur_capital(realized_usd: float, *, capital_immobilise_usd: float) -> float | None:
    """ROI sur le capital RÉELLEMENT immobilisé (pas le budget total). None si capital nul/non-fini."""
    if not est_fini(capital_immobilise_usd) or capital_immobilise_usd <= 0 or not est_fini(realized_usd):
        return None
    return float(realized_usd) / float(capital_immobilise_usd) * 100.0


__all__ = ["est_fini", "valider_numerique", "valider_signal", "roi_gate", "budget_global_utilise",
           "budget_global_ok", "prix_sortie_executable", "cout_sortie_sans_double_spread", "roi_sur_capital",
           "CHAMPS_SIGNAL"]
