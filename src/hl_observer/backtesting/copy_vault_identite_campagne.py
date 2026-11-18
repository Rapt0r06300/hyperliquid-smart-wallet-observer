"""L'IDENTITÉ D'UNE CAMPAGNE DE RECHERCHE : son digest de source, et sa tranche de temps.

POURQUOI CE MODULE EXISTE. Le dossier d'une campagne s'appelait exactement `{selection_digest}`,
et ce nom servait de double usage : identifier la source consommée, et séparer les historiques
d'essais. Les deux ont divergé le 18/11/2026, quand le labo a appris à travailler sur une tranche
de temps : dix-neuf tranches partagent le même `selection_digest` — c'est la même source — mais
elles ne doivent surtout pas partager `TRIALS.jsonl`, `ATTEMPTS.jsonl` ni `CHECKPOINT.json`.

Sans cette séparation, `seen` (l'ensemble des signatures de paramètres déjà essayées) était commun :
la tranche 2 aurait **sauté** les paramètres essayés sur la tranche 1, alors qu'ils portent sur
d'autres données. Et la reprise aurait fait croire à la tranche 2 qu'elle continuait la campagne de
la tranche 1.

LES DEUX SENS SONT NÉCESSAIRES, et c'est pour cela qu'ils vivent ensemble ici :

* `nom_de_campagne` fabrique le nom du dossier depuis le digest et la tranche ;
* `digest_de_campagne` retrouve le digest depuis le nom, parce que les **lignes** des reçus portent
  toujours le digest nu. Les relire avec le nom du dossier faisait **lever** le lecteur
  (« trial ledger identity mismatch ») dès la deuxième tranche — un défaut introduit par la
  correction elle-même, et trouvé en relisant son effet.

CE QUI N'EST PAS TOUCHÉ : `selection_digest`. Il est vérifié contre le manifeste SAFE et scellé dans
3 120 reçus de la roadmap ; le modifier les invaliderait tous. Seul le NOM DU DOSSIER porte la
tranche, et une campagne sans tranche garde exactement l'ancien chemin.
"""
from __future__ import annotations

#: Ce qui sépare le digest de la tranche dans un nom de dossier. Choisi parce qu'un digest
#: hexadécimal ne peut pas le contenir : la coupure est donc sans ambiguïté.
SEPARATEUR = "-t"


def nom_de_campagne(selection_digest: str, tranche: tuple[int, int] | None) -> str:
    """Le nom du dossier d'une campagne : `{digest}` ou `{digest}-t{début}-{fin}`.

    Sans tranche, le nom est exactement l'ancien — ce que la non-régression exige, puisque des
    campagnes existantes vivent déjà sous ces chemins.
    """
    if tranche is None:
        return selection_digest
    return f"{selection_digest}{SEPARATEUR}{int(tranche[0])}-{int(tranche[1])}"


def digest_de_campagne(nom: str) -> str:
    """Le digest porté par un dossier de campagne, qu'il soit tranché ou non.

    Les LIGNES des reçus portent toujours le digest nu, donc c'est lui qu'il faut passer aux
    lecteurs de reçus — qui lèvent sur un digest différent au lieu de filtrer. Un nom inattendu est
    rendu tel quel : mieux vaut un digest qui ne correspondra à rien qu'une exception sur un dossier
    étranger.
    """
    return nom.split(SEPARATEUR, 1)[0]


def est_tranchee(nom: str) -> bool:
    """Un dossier de campagne porte-t-il une tranche ?

    Sert à distinguer, dans un inventaire de campagnes, celles qui sont des contributions
    partielles de celles qui couvrent toute la fenêtre.
    """
    return SEPARATEUR in nom


__all__ = ["SEPARATEUR", "nom_de_campagne", "digest_de_campagne", "est_tranchee"]
