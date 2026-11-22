"""Ce que la famille copy_vault EXIGE pour pouvoir prouver quoi que ce soit.

POURQUOI CE MODULE EXISTE (22/11/2026). `economic_collection_plan.py` portait ces deux listes
en ligne. En y ajoutant `userfills-poll` et sa justification mesuree, le fichier est passe de
803 a 819 lignes pour un plafond historique de **805** -- et la regle du depot est nette :
on ne releve JAMAIS un plafond, on extrait puis on l'abaisse (`test_pas_de_nouveau_fichier_geant`).

Extraire ici est d'ailleurs plus juste que condenser le commentaire : ces listes sont un
CONTRAT (ce qu'il faut allumer, ce qu'il faut avoir produit), pas de la logique de calcul. Un
contrat se lit mieux seul, avec la mesure qui le justifie a cote de lui.

Ce module ne depend de RIEN : ni du plan, ni du labo, ni d'un etat. Une constante de contrat
lue par tout le monde ne doit dependre de personne, sous peine de cycle.
"""
from __future__ import annotations

#: Les collecteurs a allumer pour que la famille copy_vault puisse etre prouvee.
#:
#: ⚠️ LE POLL REST EST PLUS COMPLET QUE LE FLUX « LIVE ». Mesure du 22/11/2026, par
#: `tools/couverture_live_contre_poll.py`, qui restreint les deux sources a leur intersection
#: STRICTE -- memes vaults, fenetre commune. Les comparer globalement ne mesurerait que la
#: difference des perimetres : `live` voit 17 vaults sur 13 jours, `poll` 27 vaults sur 1 jour,
#: et la comparaison brute annoncait « 6 495 fills rates » sans rien prouver. Sur
#: l'intersection (14 vaults communs, 22,67 h de fenetre partagee) :
#:
#:     fills live 26 864 | fills poll 31 500 | union 32 201
#:     manques par LIVE : 5 337  (16,57 %)   <- un fill sur six
#:     manques par POLL :   701  ( 2,18 %)
#:     couverture de la meilleure source : 97,82 %
#:
#: Un fill manquant a l'entree ou a la sortie rend l'episode incomplet, et le labo le rejette
#: (1 045 `STALE_OR_MISSING_EXIT_BOOK` sur 1 613 candidats TRAIN). Exiger `userfills-live` SEUL
#: laissait donc l'operateur perdre un fill sur six en croyant avoir tout allume.
#: `slots_userfills.py` le disait deja en prose (« un autre collecteur voit deja tout le monde :
#: le poll REST ») ; c'est desormais une EXIGENCE.
#:
#: Les deux restent requis : le WS capte les 2,18 % que le poll rate.
COPY_VAULT_REQUIRED_COLLECTORS: tuple[str, ...] = (
    "vault-collector",
    "scorer-vaults",
    "userfills-live",
    "userfills-poll",
    "copy-vault-checkpoints",
    "carnet-collector",
    "backfill-fills",
    "backfill-candles-vaults",
)

#: Les artefacts qui doivent EXISTER pour qu'une preuve soit seulement envisageable.
#: `vault_fills_poll.jsonl` est certifie sous la famille FILLS_FORWARD / LIVE_POLL
#: (`datasets/coffre_certifie.py`) : il entre dans le coffre comme les autres, il manquait
#: seulement a la liste de ce qu'on exige.
COPY_VAULT_REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "runtime/data/vault_fills.jsonl",
    "runtime/data/vault_fills_live.jsonl",
    "runtime/data/vault_fills_poll.jsonl",
    "runtime/data/vault_episodes.jsonl",
    "runtime/data/vault_snapshots.jsonl",
    "runtime/data/carnet_venues.jsonl",
    "runtime/data/copy_vault_l2_tape.jsonl",
)

__all__ = ["COPY_VAULT_REQUIRED_ARTIFACTS", "COPY_VAULT_REQUIRED_COLLECTORS"]
