"""La question d'un trader senior n'est pas « le signal est-il positif ? » mais « puis-je tenir
assez longtemps pour payer le trade ? »

POURQUOI CE MODULE EXISTE
-------------------------
Tout ce que ce labo a mesuré meurt dans les coûts : `fast_follow` rejeté à tous les horizons
≤ 300 s **même à spread nul** (donc tué par les FRAIS, pas par le spread), DeepLOB à −4 242 bps,
et le maker naïf mesuré à −3,42 bp de markout à 10 s. Le seul edge encore vivant est le **carry de
funding cross-sectionnel**, avec un PBO de 0,81.

La littérature dit pourquoi, et c'est contre-intuitif :

* **Ce n'est pas le taux qui décide, c'est la DURÉE DE DÉTENTION.** `N* = C / mu` : un
  aller-retour de 0,38 % à 0,01 %/8 h demande 38 périodes, soit 12,7 jours, avant de rentrer dans
  ses frais. Agir sur un seul relevé élevé est presque toujours une erreur.
* **`N*` est un PILE OU FACE.** C'est exactement le point où P(profit) = 50 %, ce que les
  calculateurs ne disent jamais. Pour être confiant à 95 %, il faut résoudre
  `mu·N − z·sigma·sqrt(N) − C = 0`, ce qui donne **~4,2× plus long** en i.i.d. et **~6,4× plus
  long** avec une persistance AR(1) modeste (phi = 0,3), vérifié par Monte-Carlo sur
  200 000 trajectoires.
* **Trader le signal le détruit.** Mesuré sur deux ans : la règle à seuil produit le plus de revenu
  BRUT de toutes les règles testées et finit à **−9 % à −15 % net** — l'exécution consomme trois
  fois le brut. La règle qui tient en continu et ne révise que sur une horloge de 30 jours
  (1 à 5 allers-retours en DEUX ANS) rend **+2,7 % à +5,4 % net**. En une phrase :
  **la direction du signal est un régime qui dure des mois, son niveau est du bruit horaire.**
* **Marge d'erreur** : la règle patiente supporte un coût d'aller-retour de plus de 250 bps ; la
  règle active meurt au-delà de 8 bps. Aucune place pour une mauvaise exécution.

CE QUE CE MODULE REFUSE
-----------------------
* un taux nul ou négatif dans le sens de la position → aucune durée ne rend le trade rentable, on
  ne renvoie pas un grand nombre mais un REFUS ;
* une volatilité inconnue → pas de seuil à 95 %, et surtout pas le seuil naïf à la place : on
  dirait « confiant » là où l'on est à pile ou face ;
* un horizon de données plus court que la durée requise → `NON_TENABLE`. Entrer dans un trade qu'on
  ne pourra pas tenir assez longtemps, c'est payer les frais sans encaisser le carry.

PAPER / lecture seule.
"""
from __future__ import annotations

import math
from typing import Any

TENABLE = "TENABLE"
NON_TENABLE = "NON_TENABLE"
NON_MESURABLE = "NON_MESURABLE"

TAUX_NUL_OU_CONTRAIRE = "TAUX_NUL_OU_CONTRAIRE"
VOLATILITE_INCONNUE = "VOLATILITE_INCONNUE"
HORIZON_TROP_COURT = "HORIZON_DE_DONNEES_TROP_COURT"

#: 1,645 = quantile normal à 95 % unilatéral.
Z_95 = 1.6448536269514722


def _fini(valeur: Any) -> float | None:
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return None
    return sortie if math.isfinite(sortie) else None


def intervalles_pour_rentrer(cout_aller_retour: float, taux_par_intervalle: float) -> float | None:
    """`N* = C / mu` — le seuil que tout le monde calcule, et qui vaut P(profit) = 50 %.

    Renvoie None si le taux est nul ou de signe contraire : aucune durée ne rend alors le trade
    rentable, et renvoyer un grand nombre laisserait croire qu'il suffit d'attendre.
    """
    cout = _fini(cout_aller_retour)
    taux = _fini(taux_par_intervalle)
    if cout is None or taux is None or taux <= 0 or cout < 0:
        return None
    return cout / taux


def intervalles_confiance_95(*, cout_aller_retour: float, moyenne: float, ecart_type: float,
                             persistance: float = 0.0) -> float | None:
    """Durée pour être confiant à 95 %, pas à 50 %.

    On résout `mu·N − z·sigma_eff·sqrt(N) − C = 0`, quadratique en sqrt(N) :
        x = [z·s/mu + sqrt((z·s/mu)² + 4C/mu)] / 2,  N = x²

    `persistance` est le phi d'un AR(1) : le funding ne se réinitialise pas entre règlements, et
    sa variance cumulée ne croît donc pas linéairement en N. Le facteur de long terme vaut
    (1+phi)/(1−phi) — phi = 0,3, une persistance faible, suffit à multiplier la variance par 1,86
    et à rallonger la durée d'environ 50 %.
    """
    cout = _fini(cout_aller_retour)
    mu = _fini(moyenne)
    sigma = _fini(ecart_type)
    phi = _fini(persistance) or 0.0
    if cout is None or mu is None or sigma is None or mu <= 0 or sigma < 0 or cout < 0:
        return None
    if not (-0.999 < phi < 0.999):
        return None
    sigma_eff = sigma * math.sqrt((1.0 + phi) / (1.0 - phi)) if phi > 0 else sigma
    ratio = Z_95 * sigma_eff / mu
    x = (ratio + math.sqrt(ratio * ratio + 4.0 * cout / mu)) / 2.0
    return x * x


def taux_minimal(cout_aller_retour: float, intervalles_tenables: float) -> float | None:
    """Le taux en dessous duquel entrer est perdant, VU NOTRE structure de coûts.

    « Une APR élevée sur une ligne qu'on ne peut tenir que deux jours, au tarif taker, est
    souvent une perte. » C'est la discipline que toute la stratégie demande.
    """
    cout = _fini(cout_aller_retour)
    horizon = _fini(intervalles_tenables)
    if cout is None or horizon is None or horizon <= 0 or cout < 0:
        return None
    return cout / horizon


def decider(*, cout_aller_retour: float, moyenne: float, ecart_type: float | None,
            intervalles_disponibles: float, persistance: float = 0.0) -> dict[str, Any]:
    """Peut-on tenir assez longtemps ? Sinon on n'entre pas — même si le signal est beau.

    Entrer dans un trade qu'on ne pourra pas tenir jusqu'à son seuil, c'est payer les frais sans
    encaisser le carry : exactement ce que mesure la règle à seuil qui produit le plus de brut et
    finit à −9 % à −15 % net.
    """
    naif = intervalles_pour_rentrer(cout_aller_retour, moyenne)
    if naif is None:
        return {"verdict": NON_MESURABLE, "motif": TAUX_NUL_OU_CONTRAIRE,
                "lecture": ("taux nul ou de signe contraire : AUCUNE duree ne rend ce trade "
                            "rentable. Attendre ne corrige pas un signe.")}
    if ecart_type is None:
        return {"verdict": NON_MESURABLE, "motif": VOLATILITE_INCONNUE,
                "intervalles_50": naif,
                "lecture": (f"seuil a 50 % = {naif:.0f} intervalles, mais volatilite inconnue : "
                            "impossible de calculer le seuil a 95 %. Utiliser le seuil naif a la "
                            "place dirait « confiant » la ou l'on est a PILE OU FACE.")}
    sur = intervalles_confiance_95(cout_aller_retour=cout_aller_retour, moyenne=moyenne,
                                   ecart_type=ecart_type, persistance=persistance)
    if sur is None:
        return {"verdict": NON_MESURABLE, "motif": VOLATILITE_INCONNUE,
                "intervalles_50": naif, "lecture": "parametres hors domaine."}
    disponibles = _fini(intervalles_disponibles) or 0.0
    tenable = disponibles >= sur
    return {
        "verdict": TENABLE if tenable else NON_TENABLE,
        "motif": None if tenable else HORIZON_TROP_COURT,
        "intervalles_50": naif,
        "intervalles_95": sur,
        "facteur": sur / naif if naif > 0 else None,
        "intervalles_disponibles": disponibles,
        "taux_minimal_pour_l_horizon": taux_minimal(cout_aller_retour, disponibles),
        "lecture": (
            f"seuil a 50 % : {naif:.0f} intervalles (PILE OU FACE) ; "
            f"seuil a 95 % : {sur:.0f} ({sur / naif:.1f}x plus long) ; "
            f"disponibles : {disponibles:.0f} -> "
            + ("TENABLE" if tenable else
               "NON TENABLE : entrer ici, c'est payer les frais sans encaisser le carry")),
    }


__all__ = ["TENABLE", "NON_TENABLE", "NON_MESURABLE", "TAUX_NUL_OU_CONTRAIRE",
           "VOLATILITE_INCONNUE", "HORIZON_TROP_COURT", "Z_95",
           "intervalles_pour_rentrer", "intervalles_confiance_95", "taux_minimal", "decider"]
