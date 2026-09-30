"""RENFORT DE POSITION (21/07, « améliore tout encore ») — le capital qui dort, sans churn.

LE CONSTAT : 5 positions tiennent 50 $ de marge (ouvertes avant le fix du capital fantôme)
alors que la marge dynamique en accorde 100. Les fermer pour rouvrir coûterait la sortie
(~11 bps) PLUS l'entrée — du churn déguisé en optimisation. Le RENFORT ajoute du notional
à une position vivante : on ne paie QUE l'entrée du montant ajouté, jamais de sortie.

RÈGLES (écrites avant le code) :
  R1. On ne renforce QUE ce qui est déjà VIABLE ce tick (même porte que l'ouverture) ;
  R2. Le notional AJOUTÉ doit pouvoir amortir SON PROPRE coût d'entrée avant la fin de vie
      de la position. (Corrigé le 21/07 : ma 1re version exigeait que la position EXISTANTE
      soit amortie. C'était le sunk cost à l'envers — le passé de la position ne dit rien
      sur la rentabilité du dollar qu'on ajoute. Et à ~19 jours d'amortissement au funding
      plancher, cette règle rendait le renfort mort-né. Le vrai test est celui-ci.) ;
  R3. Le prix d'entrée, la base d'entrée et le coût d'entrée deviennent des MOYENNES
      PONDÉRÉES par le notional : le PnL reste exact, aucune ligne du passé n'est réécrite ;
  R4. Écart minimum de 40 % entre la marge courante et la marge cible — sinon on ne bouge
      pas (renforcer de 3 $ paie des frais pour rien) ;
  R5. Un renfort par position et par 24 h (anti-emballement) ;
  R6. Le renfort passe la MÊME porte de risque qu'une ouverture (capital, levier, drawdown) —
      ajouter du notional EST une ouverture, elle n'a aucune raison d'être moins gardée.

Le funding déjà accru est CONSERVÉ tel quel : il a été gagné sur l'ancien notional, on ne
le rétro-projette jamais sur le nouveau (ce serait fabriquer du PnL).
"""
from __future__ import annotations

from typing import Any

ECART_MIN_FRACTION = 0.40           # R4 : moins de 40 % d'écart -> on ne bouge pas
DELAI_MIN_RENFORT_MS = 24 * 3600 * 1000     # R5 : un renfort par position et par jour
MOTIF = "RENFORT_MARGE_CIBLE"


def est_amortie(position: dict[str, Any]) -> bool:
    """Le funding ENCAISSÉ couvre-t-il DÉJÀ le coût d'entrée payé, en dollars ?

    Diagnostic (affiché, journalisé) — ce n'est PLUS une porte du renfort : voir R2. Mesure
    en dollars réels, pas une extrapolation ; complémentaire de `duree_min_tenue_respectee`
    (A3) qui, elle, extrapole un délai pour décider d'une SORTIE.
    """
    accru = float(position.get("funding_accrued_usdt") or 0.0)
    notional = float(position.get("notional_usdt") or 0.0)
    cout_bps = max(float(position.get("cout_entree_bps") or 0.0), 0.0)
    return accru >= notional * cout_bps / 1e4


def ajout_amortissable(*, cout_entree_bps_ajout: float, funding_bps_h: float,
                       heures_restantes: float) -> bool:
    """R2 — le dollar AJOUTÉ rembourse-t-il son entrée avant la fin de vie de la position ?

    C'est le SEUL test qui ait un sens économique : le notional ajouté paie sa propre entrée
    et encaisse le même funding. Il est rentable si, et seulement si, il a le temps.
    Funding nul ou négatif -> jamais (on n'ajoute pas sur un revenu qui n'existe pas).
    """
    f = float(funding_bps_h)
    if f <= 0.0 or float(heures_restantes) <= 0.0:
        return False
    cout = max(float(cout_entree_bps_ajout), 0.0)
    return (cout / f) <= float(heures_restantes)


def peut_renforcer(position: dict[str, Any], *, marge_cible_usd: float, now_ms: int,
                   viable: bool, amortissable: bool) -> tuple[bool, str]:
    """(possible, motif de refus). Règles R1-R5, dans l'ordre du plus dur. R6 (porte de risque)
    est appliquée par l'appelant, qui seul connaît le capital et les positions voisines."""
    if not viable:
        return False, "COIN_NON_VIABLE_CE_TICK"          # R1
    if not amortissable:
        return False, "AJOUT_NON_AMORTISSABLE_AVANT_FIN_DE_VIE"   # R2
    marge = float(position.get("marge_usdt") or 0.0)
    cible = float(marge_cible_usd or 0.0)
    if marge <= 0 or cible <= marge:
        return False, "MARGE_DEJA_AU_NIVEAU"
    if (cible - marge) / marge < ECART_MIN_FRACTION:     # R4
        return False, "ECART_TROP_FAIBLE"
    dernier = float(position.get("dernier_renfort_ts_ms") or 0.0)
    if dernier > 0 and (int(now_ms) - dernier) < DELAI_MIN_RENFORT_MS:
        return False, "RENFORT_DEJA_FAIT_AUJOURD_HUI"     # R5
    return True, ""


def renforcer(position: dict[str, Any], *, marge_cible_usd: float, now_ms: int,
              prix_perp: float | None = None, base_bps: float | None = None,
              cout_entree_bps_ajout: float | None = None) -> dict[str, Any]:
    """Retourne la position RENFORCÉE (R3 : moyennes pondérées par le notional).
    N'appelle JAMAIS `peut_renforcer` à ta place — la porte reste au-dessus, explicite."""
    p = dict(position)
    levier = float(p.get("levier") or 0.0)
    marge_avant = float(p.get("marge_usdt") or 0.0)
    notional_avant = float(p.get("notional_usdt") or 0.0)
    if levier <= 0 or marge_avant <= 0 or notional_avant <= 0:
        return position
    marge_apres = float(marge_cible_usd)
    ajout_marge = marge_apres - marge_avant
    ajout_notional = ajout_marge * levier
    if ajout_notional <= 0:
        return position
    notional_apres = notional_avant + ajout_notional
    poids_a, poids_b = notional_avant / notional_apres, ajout_notional / notional_apres

    def _moy(cle: str, valeur_ajout: float | None) -> None:
        if valeur_ajout is None:
            return                                   # pas de mesure -> on garde l'ancienne
        ancien = p.get(cle)
        if isinstance(ancien, (int, float)):
            p[cle] = round(float(ancien) * poids_a + float(valeur_ajout) * poids_b, 8)

    _moy("entry_perp_px", prix_perp)
    _moy("base_bps_entree", base_bps)
    _moy("base_mid_bps_entree", base_bps)
    _moy("cout_entree_bps", cout_entree_bps_ajout)
    p["marge_usdt"] = round(marge_apres, 6)
    p["notional_usdt"] = round(notional_apres, 6)
    p["dernier_renfort_ts_ms"] = int(now_ms)
    p["renforts"] = int(p.get("renforts") or 0) + 1
    # le funding accru reste INTACT : il a été gagné sur l'ancien notional.
    return p


__all__ = ["est_amortie", "ajout_amortissable", "peut_renforcer", "renforcer", "ECART_MIN_FRACTION", "DELAI_MIN_RENFORT_MS", "MOTIF"]
