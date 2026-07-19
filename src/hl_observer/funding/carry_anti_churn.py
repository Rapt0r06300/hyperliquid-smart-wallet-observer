"""ANTI-CHURN DU CARRY — le bug qui mangeait 100 % du PnL (mesuré le 2026-07-19).

LA MESURE QUI A TOUT EXPLIQUÉ
-----------------------------
    opens = 32   closes = 31   sur 22,3 h   toujours le MÊME coin (HYPE)
    motif de fermeture : COIN_PLUS_DANS_SHORTLIST × 29
    realized = -4,998 $        funding réellement encaissé = 0,000457 $

La position ne se fermait pas parce que le trade tournait mal. Elle se fermait parce que HYPE
disparaissait momentanément de `carry_spot_shortlist.json` (le feeder tourne toutes les 10 min ;
une passe qui ne le liste pas suffisait). La passe suivante, HYPE revenait -> réouverture.

L'ARITHMÉTIQUE :
    notional 75 $ · funding 0,125 bps/h (le PLANCHER protocolaire)
    revenu           = 0,00094 $/h  = 2,25 centimes / JOUR
    aller-retour     = 12,47 + 11 bps ≈ 17,6 centimes
    -> UN aller-retour détruit ~188 HEURES de funding.
    31 allers-retours ≈ 5,45 $ : c'est tout le PnL négatif affiché.

LA FAUTE DE RAISONNEMENT, NOMMÉE
--------------------------------
Le code disait, en commentaire : « deny-by-default : on ne tient jamais une position sur une
donnée disparue ». C'est une MAUVAISE application de la règle. Deny-by-default veut dire :
**ne pas OUVRIR sans donnée**. Il ne dit pas : **FERMER quand la donnée cligne**. Ouvrir et
fermer sont des ACTIONS qui coûtent ; l'abstention est le défaut. Une donnée absente doit
figer la décision, pas déclencher un aller-retour à 17,6 centimes.

CE MODULE (pur, sans I/O) porte les 5 règles :
  A1  absence TOLÉRÉE quelques passes avant de fermer (une donnée qui cligne n'est pas une sortie)
  A2  hystérésis : on n'ouvre qu'au-dessus d'un seuil, on ne ferme qu'en dessous d'un seuil PLUS BAS
  A3  durée de détention minimale = le temps d'amortir le coût d'entrée
  A4  fermer doit RAPPORTER plus que les frais de sortie
  A5  compteur d'allers-retours : au-delà d'un seuil sur 24 h, le coin est gelé

RÈGLE INTOUCHABLE : rien de tout ceci ne retarde une sortie de DANGER (liquidation). Protéger le
capital passe avant l'économie des frais.

PAPER only : aucune de ces fonctions n'émet d'ordre.
"""
from __future__ import annotations

from typing import Any

#: A1 — nombre de passes consécutives où un coin peut manquer avant qu'on ferme pour de bon.
PASSES_ABSENCE_TOLEREES = 3
#: A1 bis — et au moins ce délai : 3 passes d'un feeder à 10 min, c'est 30 min de silence réel.
MINUTES_ABSENCE_TOLEREES = 45.0
#: A2 — on ferme sur funding faible seulement sous cette FRACTION du funding d'entrée.
FRACTION_HYSTERESIS_FERMETURE = 0.5
#: A5 — au-delà de tant d'allers-retours sur 24 h, le coin est gelé (symptôme, pas stratégie).
MAX_ALLERS_RETOURS_24H = 3

SORTIE_ABSENCE_PROLONGEE = "DONNEE_ABSENTE_PROLONGEE"
MOTIFS_DE_DANGER = ("LIQUID", "DANGER", "KILL")     # jamais retardés, jamais amortis


def est_un_danger(motif: str | None) -> bool:
    """Une sortie de DANGER ignore toutes les optimisations de frais. Le capital d'abord."""
    if not motif:
        return False
    haut = str(motif).upper()
    return any(mot in haut for mot in MOTIFS_DE_DANGER)


# --------------------------------------------------------------------- A1 : l'absence tolérée

def doit_fermer_pour_absence(*, absences_consecutives: int, minutes_depuis_1re_absence: float,
                             passes_tolerees: int = PASSES_ABSENCE_TOLEREES,
                             minutes_tolerees: float = MINUTES_ABSENCE_TOLEREES) -> bool:
    """Fermer pour ABSENCE de donnée exige que l'absence soit PROLONGÉE — les deux conditions.

    Un feeder qui saute une passe n'est pas un marché qui disparaît. Exiger le nombre de passes
    ET la durée évite les deux faux positifs symétriques (un poll rapide qui compte vite, un
    poll lent qui compte peu).
    """
    return (int(absences_consecutives) >= int(passes_tolerees)
            and float(minutes_depuis_1re_absence) >= float(minutes_tolerees))


# --------------------------------------------------------------------- A3 : amortir l'entrée

def heures_pour_amortir(*, cout_entree_bps: float, funding_bps_h: float) -> float:
    """Combien d'heures de funding faut-il pour rembourser l'entrée ? inf si le funding est nul.

    À 12,47 bps d'entrée et 0,125 bps/h, la réponse est ~100 h. Fermer avant, c'est acter
    la perte pour rien.
    """
    f = float(funding_bps_h)
    if f <= 0:
        return float("inf")
    return max(0.0, float(cout_entree_bps)) / f


def duree_min_tenue_respectee(position: dict[str, Any], *, now_ms: int,
                              funding_bps_h: float, marge: float = 1.0) -> bool:
    """A3 — a-t-on tenu assez longtemps pour avoir amorti l'entrée ? (hors danger)"""
    try:
        entree = int(position.get("entry_ts_ms") or 0)
    except (TypeError, ValueError):
        return True                       # horodatage illisible -> on ne bloque pas une sortie
    if entree <= 0:
        return True
    age_h = (int(now_ms) - entree) / 3.6e6
    seuil = heures_pour_amortir(
        cout_entree_bps=float(position.get("cout_entree_bps") or 0.0),
        funding_bps_h=funding_bps_h) * float(marge)
    if seuil == float("inf"):
        return True                       # funding nul : garder n'a plus de sens, on laisse sortir
    return age_h >= seuil


# --------------------------------------------------------------------- A2 : hystérésis

def funding_sous_seuil_de_sortie(*, funding_courant_bps_h: float, funding_entree_bps_h: float,
                                 fraction: float = FRACTION_HYSTERESIS_FERMETURE) -> bool:
    """A2 — on ne ferme pas dès que le funding baisse d'un cheveu sous celui d'entrée.

    Sans bande morte, un taux qui oscille autour du seuil produit exactement le clignotement
    ouvrir/fermer qu'on vient de payer 5 $.
    """
    entree = float(funding_entree_bps_h)
    if entree <= 0:
        return float(funding_courant_bps_h) <= 0.0
    return float(funding_courant_bps_h) < entree * float(fraction)


# --------------------------------------------------------------------- A4 : sortir doit rapporter

def sortie_rentable(*, gain_attendu_bps: float, cout_sortie_bps: float) -> bool:
    """A4 — fermer coûte ~11 bps. Une sortie qui rapporte moins que ça détruit de la valeur."""
    return float(gain_attendu_bps) > float(cout_sortie_bps)


# --------------------------------------------------------------------- A5 : le coin qui clignote

def churn_excessif(*, allers_retours_24h: int, seuil: int = MAX_ALLERS_RETOURS_24H) -> bool:
    """A5 — un coin qui ouvre/ferme sans arrêt est un SYMPTÔME, pas une stratégie. On le gèle."""
    return int(allers_retours_24h) >= int(seuil)


def filtrer_sortie(motif: str | None, position: dict[str, Any], *, now_ms: int,
                   funding_bps_h: float, cout_sortie_bps: float = 11.0) -> str | None:
    """LE POINT UNIQUE où une sortie est confirmée ou annulée. Retourne le motif, ou None (on garde).

    Ordre volontaire :
      1. DANGER  -> on sort, tout de suite, sans discuter (le capital avant les frais) ;
      2. funding <= 0 -> garder ne rapporte plus rien, on laisse sortir ;
      3. sinon, on exige d'avoir AMORTI l'entrée (A3) -- sinon on annule la sortie.
    """
    if motif is None:
        return None
    if est_un_danger(motif):
        return motif
    if float(funding_bps_h) <= 0.0:
        return motif
    if not duree_min_tenue_respectee(position, now_ms=now_ms, funding_bps_h=funding_bps_h):
        return None                       # trop tôt : fermer maintenant acterait la perte pour rien
    return motif


__all__ = [
    "PASSES_ABSENCE_TOLEREES", "MINUTES_ABSENCE_TOLEREES", "FRACTION_HYSTERESIS_FERMETURE",
    "MAX_ALLERS_RETOURS_24H", "SORTIE_ABSENCE_PROLONGEE", "est_un_danger",
    "doit_fermer_pour_absence", "heures_pour_amortir", "duree_min_tenue_respectee",
    "funding_sous_seuil_de_sortie", "sortie_rentable", "churn_excessif", "filtrer_sortie",
]
