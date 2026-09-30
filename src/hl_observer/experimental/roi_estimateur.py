"""ESTIMATEUR ROI ANNUEL CONSERVATEUR (LOT14 P0, Flo 26/07). Cœur PUR.

Problème corrigé : `Signal.roi_annuel_pct` valait 0.0 par défaut et aucun adaptateur ne le renseignait, donc
la gate ROI (>=15 %) rejetait TOUS les vrais signaux (`ROI_INSUFFISANT`). Ici on calcule un ROI annuel
**conservateur** — PAS une annualisation naïve `edge × heures/an` — à partir de :
  * rendement NET par événement (edge_net_bps sur le notional) ;
  * fréquence d'événements MESURÉE causalement (évts/jour observés) ;
  * durée d'immobilisation (hold_h) — plafonne le turnover du capital ;
  * taux de fill ;
  * capacité (notional vs profondeur exploitable) ;
  * positions simultanées possibles ;
  * dégradation forward (pertes/haircut mesurés) ;
  * utilisation réelle du budget.

Si un ingrédient ESSENTIEL manque (surtout la fréquence mesurée) -> retourne **None** = ROI_NON_MESURABLE.
Deux voies exploitent cette distinction (cf. moteur_paper.admettre) :
  * EXPERIMENTAL_PAPER : ROI None n'interdit pas la collecte forward (sous limites isolées) ;
  * strict : ROI None interdit l'admission.
0 réseau, 0 ordre.
"""
from __future__ import annotations

from hl_observer.experimental.invariants import est_fini

HEURES_PAR_AN = 8760.0
JOURS_PAR_AN = 365.0


def roi_annuel_conservateur(*, edge_net_bps, hold_h, freq_evenements_par_jour=None, fill_rate: float = 1.0,
                            capacite_usd=None, notional_usd=None, positions_simultanees: int = 1,
                            pertes_forward_frac: float = 0.0, budget_utilise_frac: float = 1.0) -> float | None:
    """ROI annuel NET conservateur en %, ou **None** si non mesurable.

    Modèle (conservateur, borné par le TURNOVER du capital) :
      rendement/évt = edge_net_bps/1e4  (fraction du notional captée, déjà nette des coûts)
      turns_max/an  = HEURES_PAR_AN / hold_h            (un slot ne peut pas enchaîner plus vite que le hold)
      évts/an       = min(freq/jour × 365, turns_max/an)  (jamais plus que ce que le capital permet)
      roi %         = rendement/évt × évts/an × fill × haircut_capacité × (1−pertes_forward) × budget × 100

    `freq_evenements_par_jour=None` -> **None** (fréquence non mesurée = ROI non prouvé)."""
    if not (est_fini(edge_net_bps) and est_fini(hold_h)) or float(hold_h) <= 0:
        return None
    if freq_evenements_par_jour is None or not est_fini(freq_evenements_par_jour) or float(freq_evenements_par_jour) < 0:
        return None                                             # fréquence non mesurée -> ROI_NON_MESURABLE
    rendement_par_evt = float(edge_net_bps) / 1e4
    turns_max_an = HEURES_PAR_AN / float(hold_h)
    evts_an = min(float(freq_evenements_par_jour) * JOURS_PAR_AN, turns_max_an)
    haircut_capacite = 1.0
    if capacite_usd is not None and notional_usd is not None and est_fini(capacite_usd) and est_fini(notional_usd):
        if float(capacite_usd) > 0 and float(notional_usd) > 0:
            haircut_capacite = min(1.0, float(capacite_usd) / float(notional_usd))
    fill = max(0.0, min(1.0, float(fill_rate) if est_fini(fill_rate) else 0.0))
    forward = max(0.0, min(1.0, float(pertes_forward_frac) if est_fini(pertes_forward_frac) else 0.0))
    budget = max(0.0, min(1.0, float(budget_utilise_frac) if est_fini(budget_utilise_frac) else 0.0))
    roi = rendement_par_evt * evts_an * fill * haircut_capacite * (1.0 - forward) * budget * 100.0
    return float(round(roi, 4))


def roi_depuis_signal(sig, *, freq_evenements_par_jour=None, fill_rate: float = 1.0,
                      capacite_usd=None, pertes_forward_frac: float = 0.0,
                      budget_utilise_frac: float = 1.0) -> float | None:
    """Applique l'estimateur aux champs d'un Signal déjà construit. Rend le ROI % (ou None)."""
    return roi_annuel_conservateur(
        edge_net_bps=getattr(sig, "edge_estime_bps", None), hold_h=getattr(sig, "hold_h", None),
        freq_evenements_par_jour=freq_evenements_par_jour, fill_rate=fill_rate,
        capacite_usd=capacite_usd, notional_usd=getattr(sig, "notional_usd", None),
        pertes_forward_frac=pertes_forward_frac, budget_utilise_frac=budget_utilise_frac)


__all__ = ["roi_annuel_conservateur", "roi_depuis_signal", "HEURES_PAR_AN", "JOURS_PAR_AN"]
