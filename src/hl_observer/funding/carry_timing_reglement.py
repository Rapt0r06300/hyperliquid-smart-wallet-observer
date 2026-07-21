"""TIMING DU RÈGLEMENT — le seul gain vraiment gratuit du carry (idée #6, 21/07).

LE FAIT, PAS UNE HYPOTHÈSE
--------------------------
Hyperliquid règle le funding **au sommet de chaque heure**, sur la position tenue à cet
instant précis (doc officielle ; on l'a codé le même jour dans `funding_settlement`).

Deux conséquences immédiates, et personne ne les exploitait :

  * **ouvrir à H−1 min** capture un règlement entier une minute plus tard ;
    ouvrir à H+1 min oblige à attendre 59 minutes pour le même paiement ;
  * **fermer à H+1 min** garde le règlement qu'on vient d'encaisser ;
    fermer à H−1 min le perd entièrement.

Au plancher (0,125 bps/h), un règlement vaut 0,125 bps. Sur notre notionnel de ~1 400 $,
c'est ~0,0175 $ par position et par aller-retour. Faible en valeur absolue — mais c'est
**gratuit** : aucun risque ajouté, aucun coût, aucune donnée supplémentaire. Et sur un
carry dont le net vaut 20 bps sur toute sa vie, 0,125 bps repris à chaque bout n'est pas
du bruit : c'est ~1 % du résultat, deux fois.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne retarde **jamais** une sortie de DANGER (liquidation, funding en hémorragie). Attendre
59 minutes pour grappiller 0,125 bps pendant qu'une jambe se fait liquider serait le genre
d'optimisation qui coûte cent fois ce qu'elle rapporte. Le capital d'abord, toujours.

Il ne décale pas non plus une ouverture au-delà d'une fenêtre courte : une décision carry
repose sur des inputs frais (15 min de péremption). Reporter d'une heure, c'est décider sur
des données périmées — on refuse, et on ouvre normalement.

PAPER only : décider d'un instant n'est pas passer un ordre.
"""
from __future__ import annotations

from typing import Any

PERIODE_MS = 3_600_000

#: on n'attend jamais plus que ça pour attraper un règlement : au-delà, la décision vieillit
#: (les inputs spot se périment à 15 min) et on déciderait sur du passé.
ATTENTE_MAX_OUVERTURE_MS = 5 * 60_000
#: fenêtre après le sommet pendant laquelle une sortie peut patienter pour garder le règlement.
ATTENTE_MAX_SORTIE_MS = 3 * 60_000
#: motifs de sortie qu'on ne retarde JAMAIS, quel qu'en soit le prix.
MOTIFS_DE_DANGER = ("LIQUID", "DANGER", "KILL", "HEMORRAGIE")


def ms_avant_reglement(now_ms: int, periode_ms: int = PERIODE_MS) -> int:
    """Combien de millisecondes avant le prochain sommet d'heure. 0 si on est dessus."""
    p = int(periode_ms) if int(periode_ms) > 0 else PERIODE_MS
    reste = int(now_ms) % p
    return 0 if reste == 0 else p - reste


def ms_depuis_reglement(now_ms: int, periode_ms: int = PERIODE_MS) -> int:
    """Combien de millisecondes depuis le dernier sommet d'heure."""
    p = int(periode_ms) if int(periode_ms) > 0 else PERIODE_MS
    return int(now_ms) % p


def gain_a_attendre_bps(funding_bps_h: float) -> float:
    """Ce qu'un règlement rapporte. Funding négatif -> attendre COÛTE (on paierait) : on rend
    une valeur négative, et l'appelant en déduit qu'il vaut mieux ouvrir APRÈS le sommet."""
    return float(funding_bps_h or 0.0)


def conseil_ouverture(now_ms: int, *, funding_bps_h: float,
                      attente_max_ms: int = ATTENTE_MAX_OUVERTURE_MS,
                      periode_ms: int = PERIODE_MS) -> dict[str, Any]:
    """Faut-il attendre quelques minutes pour ouvrir juste avant le règlement ?

    `{attendre: bool, ms: int, gain_bps: float, motif: str}`. On n'attend que si le règlement
    est PROCHE (sous `attente_max_ms`) **et** qu'il rapporte. Sinon on ouvre tout de suite :
    une opportunité de carry ne se met pas en pause pour 0,125 bps.
    """
    reste = ms_avant_reglement(now_ms, periode_ms)
    gain = gain_a_attendre_bps(funding_bps_h)
    if gain <= 0:
        return {"attendre": False, "ms": 0, "gain_bps": gain,
                "motif": "funding <= 0 : le reglement COUTE, ouvrir juste APRES le sommet"}
    if reste == 0:
        return {"attendre": False, "ms": 0, "gain_bps": gain,
                "motif": "on est sur le sommet : ouvrir maintenant capture le reglement"}
    if reste > int(attente_max_ms):
        return {"attendre": False, "ms": 0, "gain_bps": 0.0,
                "motif": "reglement dans %.0f min : trop loin, les inputs se perimeraient"
                         % (reste / 60_000.0)}
    return {"attendre": True, "ms": reste, "gain_bps": gain,
            "motif": "reglement dans %.1f min : attendre capture %.3f bps, gratuitement"
                     % (reste / 60_000.0, gain)}


def conseil_sortie(now_ms: int, *, funding_bps_h: float, motif_sortie: str | None = None,
                   attente_max_ms: int = ATTENTE_MAX_SORTIE_MS,
                   periode_ms: int = PERIODE_MS) -> dict[str, Any]:
    """Faut-il patienter quelques minutes pour ne pas perdre le règlement imminent ?

    **Un DANGER n'est jamais retardé** — c'est la règle qui prime sur toutes les autres.
    """
    haut = str(motif_sortie or "").upper()
    if any(mot in haut for mot in MOTIFS_DE_DANGER):
        return {"attendre": False, "ms": 0, "gain_bps": 0.0,
                "motif": "DANGER (%s) : on sort tout de suite, le capital avant 0,125 bps"
                         % motif_sortie}
    gain = gain_a_attendre_bps(funding_bps_h)
    if gain <= 0:
        return {"attendre": False, "ms": 0, "gain_bps": gain,
                "motif": "funding <= 0 : rester COUTE, sortir maintenant"}
    reste = ms_avant_reglement(now_ms, periode_ms)
    if reste == 0 or reste > int(attente_max_ms):
        return {"attendre": False, "ms": 0, "gain_bps": 0.0,
                "motif": "aucun reglement imminent (%.0f min) : sortir maintenant"
                         % (reste / 60_000.0)}
    return {"attendre": True, "ms": reste, "gain_bps": gain,
            "motif": "reglement dans %.1f min : patienter garde %.3f bps deja acquis"
                     % (reste / 60_000.0, gain)}


def valeur_annuelle_usd(notional_usd: float, funding_bps_h: float,
                        allers_retours_par_mois: float = 2.0) -> float:
    """Ce que ce timing vaut sur un an, en dollars — pour ne pas s'illusionner sur sa taille.
    Deux règlements gagnés par aller-retour (un à l'entrée, un à la sortie)."""
    par_ar = 2.0 * float(notional_usd) * float(funding_bps_h) / 1e4
    return round(par_ar * float(allers_retours_par_mois) * 12.0, 6)


__all__ = ["PERIODE_MS", "ATTENTE_MAX_OUVERTURE_MS", "ATTENTE_MAX_SORTIE_MS",
           "MOTIFS_DE_DANGER", "ms_avant_reglement", "ms_depuis_reglement",
           "gain_a_attendre_bps", "conseil_ouverture", "conseil_sortie", "valeur_annuelle_usd"]
