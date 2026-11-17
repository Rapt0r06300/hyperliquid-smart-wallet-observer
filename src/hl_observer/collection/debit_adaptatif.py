"""LE RATTRAPAGE S'IMPOSAIT 10 % DU DEBIT, ET C'EST POURQUOI IL DEMANDAIT 107 HEURES.

CE QUI ETAIT FAUX
-----------------
`collecte_fiable.BUDGET_POIDS_RATTRAPAGE_PAR_MINUTE` vaut **100 unites par minute**, alors que le
plafond que le projet se donne lui-meme (`SEUIL_POIDS_PARTAGE_PAR_MINUTE`) est de **1 000**, sous la
limite de 1 200/min/IP de la venue. Un rattrapage se contentait donc du dixieme du debit, en
permanence, **y compris quand aucun collecteur en direct ne demandait quoi que ce soit**.

Mesure du 15/11 : une requete de funding (500 points) attendait **28 s**. 261 coins x 53 pages pour
atteindre 1 100 jours = 13 833 requetes = **107 heures**. Le meme travail a 400 unites/minute tient
en 27 heures. Le facteur n'est pas une optimisation cosmetique : il decide si la profondeur est
atteignable avant la fin de la campagne ou pas.

POURQUOI PAS SIMPLEMENT LIRE LA CONSOMMATION REELLE
---------------------------------------------------
Parce qu'elle n'est PAS mesuree. `reserver_poids` tient une fenetre de 60 s dans le fichier designe
par `ALINA_BUDGET_DEBIT` — mais cette variable **n'est definie nulle part dans le projet**, et
seuls 5 collecteurs sur une vingtaine appellent la fonction. Le compteur partage est donc
doublement vide : non active, et incomplet meme s'il l'etait. Accelerer en lisant un compteur qui
sous-compte, c'est se garantir des refus de debit.

CE QU'ON FAIT A LA PLACE : MESURER PAR LE SEUL SIGNAL FIABLE
------------------------------------------------------------
Le refus de debit (HTTP 429) est la seule mesure que la venue nous donne vraiment. On regle donc le
debit comme TCP regle une fenetre d'envoi — **AIMD** : on monte d'un cran apres une serie de succes,
on DIVISE sur un refus. Le controleur trouve ainsi de lui-meme la place libre, sans jamais avoir
besoin de la connaitre a l'avance, et il la rend des qu'elle disparait.

* montee ADDITIVE (+`PAS_MONTEE` apres `SUCCES_AVANT_MONTEE` requetes servies) : prudente, lineaire ;
* descente MULTIPLICATIVE (x`FACTEUR_DESCENTE` sur un refus) : immediate, parce qu'un refus signifie
  que la limite est DEJA depassee ;
* plancher = l'ancien budget fixe : on ne fait jamais PIRE qu'avant ;
* plafond = `PLAFOND_RATTRAPAGE_PAR_MINUTE`, bien sous la limite de l'IP, pour qu'un collecteur en
  direct trouve toujours de la place. Le rattrapage reste le citoyen de seconde classe : il appelle
  deja `ceder_au_direct()` avant chaque requete.

CE QUE CE MODULE REFUSE
-----------------------
* **rendre une pause nulle** : un debit « illimite » est exactement ce qui fait bannir une IP ;
* **monter apres un refus non encaisse** : `refus()` remet le compteur de succes a zero, sinon la
  serie de succes d'avant le refus justifierait une montee juste apres lui ;
* **descendre sous le plancher** : sous 100/min le rattrapage n'avance plus, et un rattrapage qui
  n'avance pas est un rattrapage mort.

Pur et deterministe : aucune horloge, aucun reseau, aucun fichier. Lecture seule / PAPER.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: L'ancien budget fixe. Il devient le PLANCHER : on ne fait jamais pire qu'avant.
PLANCHER_RATTRAPAGE_PAR_MINUTE = 100.0
#: Plafond du rattrapage. La venue coupe a 1 200/min/IP et le projet se limite a 1 000 ; on garde
#: 400 unites de marge pour les collecteurs en direct, qui sont EN RAFALE et n'attendent pas.
PLAFOND_RATTRAPAGE_PAR_MINUTE = 600.0
#: Combien de requetes servies sans refus avant de monter d'un cran.
SUCCES_AVANT_MONTEE = 12
#: Le cran de montee, en unites de poids par minute.
PAS_MONTEE = 50.0
#: Ce qu'on garde du debit apres un refus. 0,5 = on divise par deux, comme TCP.
FACTEUR_DESCENTE = 0.5

MOTIF_DEMARRAGE = "DEMARRAGE_AU_PLANCHER"
MOTIF_MONTEE = "MONTEE_APRES_SUCCES"
MOTIF_DESCENTE = "DESCENTE_APRES_REFUS"
MOTIF_PLAFOND = "PLAFOND_ATTEINT"
MOTIF_PLANCHER = "PLANCHER_ATTEINT"


def pause_pour_poids(poids: float, *, budget_par_minute: float) -> float:
    """Secondes a laisser passer pour qu'une requete de ce poids tienne dans le budget.

    Un budget nul ou negatif ne veut PAS dire « pas d'attente » : cela n'aurait aucun sens
    physique. On retombe sur le plancher, qui est le comportement d'avant ce module.
    """
    budget = float(budget_par_minute)
    if not (budget > 0.0):
        budget = PLANCHER_RATTRAPAGE_PAR_MINUTE
    return max(0.0, float(poids)) / budget * 60.0


@dataclass
class CadenceAimd:
    """Le debit d'un rattrapage, regle par les refus de la venue plutot que devine.

    Usage :

        cadence = CadenceAimd()
        ...
        dormir(cadence.pause(poids_de_la_requete))   # AVANT la requete
        lignes, _, erreur = tirer(...)
        cadence.refus() if erreur == "LIMITE_DEBIT" else cadence.succes()
    """

    budget_par_minute: float = PLANCHER_RATTRAPAGE_PAR_MINUTE
    plancher: float = PLANCHER_RATTRAPAGE_PAR_MINUTE
    plafond: float = PLAFOND_RATTRAPAGE_PAR_MINUTE
    succes_avant_montee: int = SUCCES_AVANT_MONTEE
    pas_montee: float = PAS_MONTEE
    facteur_descente: float = FACTEUR_DESCENTE
    #: journal des changements, pour que l'operateur VOIE le debit bouger (et pourquoi)
    historique: list[tuple[float, str]] = field(default_factory=list)
    _succes: int = 0
    _refus: int = 0

    def __post_init__(self) -> None:
        if self.plafond < self.plancher:          # reglage incoherent : on garde l'ordre
            self.plafond = self.plancher
        self.budget_par_minute = self._borner(self.budget_par_minute)
        self.historique.append((self.budget_par_minute, MOTIF_DEMARRAGE))

    def _borner(self, valeur: float) -> float:
        return max(self.plancher, min(self.plafond, float(valeur)))

    def pause(self, poids: float) -> float:
        """La pause a prendre AVANT la requete, au debit courant. Jamais nulle pour un poids > 0."""
        return pause_pour_poids(poids, budget_par_minute=self.budget_par_minute)

    def succes(self) -> float:
        """Une requete servie. Monte d'un cran apres `succes_avant_montee` succes consecutifs."""
        self._succes += 1
        if self._succes < max(1, int(self.succes_avant_montee)):
            return self.budget_par_minute
        self._succes = 0
        avant = self.budget_par_minute
        self.budget_par_minute = self._borner(avant + max(0.0, float(self.pas_montee)))
        if self.budget_par_minute > avant:
            self.historique.append((self.budget_par_minute, MOTIF_MONTEE))
        elif not self.historique or self.historique[-1][1] != MOTIF_PLAFOND:
            self.historique.append((self.budget_par_minute, MOTIF_PLAFOND))
        return self.budget_par_minute

    def refus(self) -> float:
        """Un refus de debit : on DIVISE tout de suite, et la serie de succes repart de zero.

        Remettre le compteur a zero n'est pas un detail : sans cela, les onze succes qui ont precede
        le refus justifieraient une montee juste APRES lui.
        """
        self._refus += 1
        self._succes = 0
        avant = self.budget_par_minute
        self.budget_par_minute = self._borner(avant * max(0.0, float(self.facteur_descente)))
        motif = MOTIF_DESCENTE if self.budget_par_minute < avant else MOTIF_PLANCHER
        self.historique.append((self.budget_par_minute, motif))
        return self.budget_par_minute

    def resume(self) -> str:
        """Une ligne pour l'operateur : le debit courant, et de combien il a bouge."""
        depart = self.historique[0][0] if self.historique else self.plancher
        return (f"debit {self.budget_par_minute:.0f} u/min "
                f"(x{self.budget_par_minute / depart:.1f} vs depart) | "
                f"{self._refus} refus encaisse(s)")


__all__ = ["PLANCHER_RATTRAPAGE_PAR_MINUTE", "PLAFOND_RATTRAPAGE_PAR_MINUTE",
           "SUCCES_AVANT_MONTEE", "PAS_MONTEE", "FACTEUR_DESCENTE",
           "MOTIF_DEMARRAGE", "MOTIF_MONTEE", "MOTIF_DESCENTE", "MOTIF_PLAFOND",
           "MOTIF_PLANCHER", "pause_pour_poids", "CadenceAimd"]
