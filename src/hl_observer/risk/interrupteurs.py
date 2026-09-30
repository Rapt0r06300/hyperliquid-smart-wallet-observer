"""GH-01 -- LE REGISTRE DES INTERRUPTEURS. La maladie du projet, enfin nommee.

SEPT FOIS. Sept fois on a trouve la meme chose :

  * le poller de carnet L2      -> capacite presente, interrupteur eteint (11/07)
  * la jambe de funding         -> capacite presente, interrupteur eteint (08/07)
  * le garde-fou lookahead      -> present, jamais appele
  * le verrou du copy-follow    -> present, contourne
  * `delta_neutral_carry`       -> present, jamais appele
  * le bus GitHub               -> allume par DEFAUT, jamais eteint dans le code (12/07)
  * **la pile V26 ENTIERE**     -> 5 interrupteurs, AUCUN dans un lanceur (13/07)

T3b a cree l'invariant sur les MODULES : « un module ni joignable ni enterre fait ECHOUER la
suite ». Il a marche -- il a trouve 4 garde-fous que mon grep avait rates.

**Mais il n'existait AUCUN invariant sur les INTERRUPTEURS.** Un module peut etre parfaitement
branche, teste, joignable... et ne jamais s'executer parce que son flag vaut "0" et que personne
ne l'a jamais pose. Le module est vivant ; la fonctionnalite est morte. L'audit de cablage ne
voit rien : l'import existe, l'appel existe. Seule la VALEUR du flag decide -- et elle est
invisible au code.

    >>> UN INTERRUPTEUR NI ALLUME NI DECLARE ETEINT FAIT ECHOUER LA SUITE. <<<

Ce module est le registre. Chaque `MASTER_FLAG` du code doit y figurer avec une DECISION :

  ALLUME                : le lanceur le pose. Le test verifie qu'il y est VRAIMENT.
  ETEINT_VOLONTAIREMENT : on a choisi de ne pas l'allumer, et on ECRIT POURQUOI.
  ETEINT_PAR_OUBLI      : interdit. Cette valeur existe pour etre bannie par le test.

Aucune I/O, aucun ordre. Le test (`tests/test_interrupteurs.py`) lit les lanceurs et confronte.
"""

from __future__ import annotations

from dataclasses import dataclass

ALLUME = "ALLUME"
ETEINT_VOLONTAIREMENT = "ETEINT_VOLONTAIREMENT"
ETEINT_PAR_OUBLI = "ETEINT_PAR_OUBLI"          # interdit -- existe pour etre banni

DECISIONS = (ALLUME, ETEINT_VOLONTAIREMENT, ETEINT_PAR_OUBLI)


@dataclass(frozen=True, slots=True)
class Interrupteur:
    flag: str
    module: str
    decision: str
    role: str            # ce que ca fait
    motif: str           # POURQUOI cette decision -- pas un slogan, un raisonnement


# ---------------------------------------------------------------------------
# LE REGISTRE
# ---------------------------------------------------------------------------
#
# 🚩 REGLE DE DECISION QU'ON S'APPLIQUE ICI, ET QU'IL FAUT TENIR :
#
#   * un interrupteur qui ne fait que REFUSER (un garde-fou) -> ALLUME.
#     Le pire qu'il puisse faire est de refuser un trade. Or on a MESURE (Q1, Q3) qu'il n'y a
#     pas d'edge a capturer : le cout d'un refus de trop est nul, le cout d'une perte evitee
#     est reel. L'asymetrie est ecrasante.
#
#   * un interrupteur qui change la TAILLE ou le SENS d'un trade -> ETEINT, avec motif.
#     Il modifie le PnL. On ne l'allume pas « pour voir » : on le mesure d'abord.
#
# Cette regle n'est pas de la prudence -- c'est de l'arithmetique.

REGISTRE: tuple[Interrupteur, ...] = (
    Interrupteur(
        flag="HYPERSMART_V26_PROTECTIONS",
        module="risk.protections_v26",
        decision=ALLUME,
        role=("StoplossGuard (N stops dans une fenetre -> halt, GLOBAL ou PAR MARCHE), "
              "LowProfitMarket (marche non rentable -> blacklist), "
              "WindowedMaxDrawdown (perte de fenetre -> pause). "
              "C'est EXACTEMENT ce que GH-01 demandait : global_stop + stop_per_pair."),
        motif=("Il ne fait que REFUSER. Nourri par le ledger reel (v26_exit_pipeline), lu par "
               "v26_entry_vetos. Code, teste, branche -- et JAMAIS allume : le flag n'est dans "
               "aucun lanceur. Trois pierres tombales justifient l'enterrement d'autres modules "
               "par « remplace par protections_v26 (vivant) » : un remplacant ETEINT n'est pas "
               "un remplacant. Cette contradiction se resout en l'allumant."),
    ),
    Interrupteur(
        flag="HYPERSMART_V26_GRADED_HALT",
        module="risk.graded_halt",
        decision=ALLUME,
        role="Machine a etats GREEN / AMBER / RED sur le PnL de fenetre. RED = plus aucune entree.",
        motif=("Il ne fait que REFUSER, et il est le successeur declare de circuit_breaker et "
               "kill_switch (tous deux ENTERRES en le citant comme vivant). Meme contradiction "
               "que ci-dessus : on a enterre les anciens au profit d'un garde-fou eteint."),
    ),
    Interrupteur(
        flag="HYPERSMART_V26_MARKET_QUALITY",
        module="signals.v26_entry_vetos",
        decision=ALLUME,
        role="Veto d'entree sur la qualite du marche (spread, profondeur, toxicite mesures).",
        motif=("Il ne fait que REFUSER, et il consomme le carnet L2 REEL (repare le 11/07). "
               "Le laisser eteint annule le benefice de cette reparation : on aurait collecte "
               "le carnet pour rien."),
    ),
    Interrupteur(
        flag="HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE",
        module="signals.v26_entry_vetos",
        decision=ALLUME,
        role="Rend les vetos V26 CONTRAIGNANTS (sinon ils sont consultatifs et ignores).",
        motif=("Sans lui, tous les vetos ci-dessus sont calcules... puis jetes. C'est le pire "
               "cas de figure : le cout du calcul, aucun benefice de la protection. Un veto "
               "consultatif n'est pas un veto."),
    ),
    Interrupteur(
        flag="HYPERSMART_NOYAU_AUTORITAIRE",
        module="decision_engine.local_engine",
        decision=ALLUME,
        role=("Rend le NOYAU UNIQUE (G2) contraignant sur les ENTREES : famille du signal (Q3), "
              "edge issu de la table MESUREE (Q1), prix executables (Q2), edge net apres couts. "
              "Eteint, le noyau est CONSULTATIF : il calcule son verdict, l'ecrit dans la preuve, "
              "et on l'ignore. Il ne garde JAMAIS les sorties -- bloquer une sortie piegerait une "
              "position ouverte."),
        motif=("Il ne fait que REFUSER une ENTREE, jamais une sortie, et jamais il ne change la "
               "taille. Sa raison d'etre est de fermer le trou trouve en G2 : LocalDecisionEngine "
               "prenait l'edge TEL QUE L'APPELANT LE DONNAIT, et le RiskEngine notait ce chiffre "
               "sans jamais questionner sa provenance -- c'est exactement ainsi que trois edges "
               "FABRIQUES ont vecu des mois. Le laisser eteint, ce serait reconstruire le trou "
               "qu'on vient de boucher."),
    ),
    Interrupteur(
        flag="HYPERSMART_V26_KELLY_LEADER",
        module="risk.kelly_leader_book",
        decision=ETEINT_VOLONTAIREMENT,
        role="Dimensionne la position selon un Kelly par leader (historique de ses trades).",
        motif=("🔴 IL CHANGE LA TAILLE, PAS SEULEMENT L'AUTORISATION -- donc il change le PnL. "
               "Et surtout : Kelly suppose un edge POSITIF connu. Or Q1 et Q3 ont MESURE que "
               "l'edge du copy-trading est nul (voire negatif). Kelly sur un edge nul dit "
               "« ne mise rien » ; Kelly sur un edge mal estime dit n'importe quoi, et il le dit "
               "en AUGMENTANT la taille. L'allumer sur un signal sans edge, c'est amplifier une "
               "perte. On le mesure d'abord, on l'allume ensuite -- jamais l'inverse."),
    ),
)

FLAGS = tuple(i.flag for i in REGISTRE)
PAR_FLAG = {i.flag: i for i in REGISTRE}

# Les paquets ou l'on exige qu'un MASTER_FLAG soit declare ici.
# `decision_engine` ajoute le 13/07 avec G2 : le point de decision est precisement l'endroit ou
# un interrupteur eteint fait le plus de degats -- et c'est celui qu'on aurait le moins surveille.
PAQUETS_SURVEILLES = ("risk", "signals", "decision_engine")

REFUS_NON_DECLARE = "INTERRUPTEUR_NON_DECLARE_AU_REGISTRE"
REFUS_ALLUME_MAIS_ABSENT_DU_LANCEUR = "INTERRUPTEUR_DIT_ALLUME_MAIS_ABSENT_DU_LANCEUR"
REFUS_OUBLI = "INTERRUPTEUR_ETEINT_PAR_OUBLI"


def a_allumer() -> tuple[str, ...]:
    return tuple(i.flag for i in REGISTRE if i.decision == ALLUME)


def eteints_volontairement() -> tuple[str, ...]:
    return tuple(i.flag for i in REGISTRE if i.decision == ETEINT_VOLONTAIREMENT)


def decision_de(flag: str) -> str:
    i = PAR_FLAG.get(str(flag or "").strip())
    return i.decision if i else ""


def _vrai(v: object) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def sante(env: dict | None = None) -> dict:
    """L'ETAT REEL des interrupteurs, AU MOMENT OU LE MOTEUR TOURNE. Pas au moment du test.

    Le test (`tests/test_interrupteurs.py`) verifie que le LANCEUR pose les flags. Mais un
    lanceur peut etre contourne : quelqu'un lance `python -m hl_observer ui` a la main, un
    service Windows garde un vieil environnement, une variable « collante » persiste...

    Cette fonction est donc l'invariant a l'EXECUTION. Elle est appelee par le chemin de
    decision (`ui/fusion_persistent_adapter`), et ce qu'elle rend remonte au journal, au
    dashboard et a l'audit. Si un garde-fou declare ALLUME ne l'est pas, **on le CRIE** au
    lieu de tourner sans protection en silence.

    C'est la lecon des sept fois : ce n'est pas l'absence de garde-fou qui fait mal, c'est
    l'absence de garde-fou QU'ON CROIT AVOIR.
    """
    import os

    e = env if env is not None else os.environ
    attendus_allumes = a_allumer()
    eteints = [f for f in attendus_allumes if not _vrai(e.get(f))]
    allumes_par_erreur = [f for f in eteints_volontairement() if _vrai(e.get(f))]

    return {
        "ok": not eteints and not allumes_par_erreur,
        "declares_allumes": list(attendus_allumes),
        "REELLEMENT_ETEINTS": eteints,                 # <- des garde-fous qu'on CROIT actifs
        "allumes_contre_la_decision": allumes_par_erreur,
        "eteints_volontairement": list(eteints_volontairement()),
        "alerte": (
            f"{len(eteints)} garde-fou(s) declares ALLUME mais ETEINTS a l'execution : "
            f"{eteints}" if eteints else ""
        ),
    }


__all__ = [
    "sante",
    "ALLUME", "ETEINT_VOLONTAIREMENT", "ETEINT_PAR_OUBLI", "DECISIONS",
    "Interrupteur", "REGISTRE", "FLAGS", "PAR_FLAG", "PAQUETS_SURVEILLES",
    "REFUS_NON_DECLARE", "REFUS_ALLUME_MAIS_ABSENT_DU_LANCEUR", "REFUS_OUBLI",
    "a_allumer", "eteints_volontairement", "decision_de",
]
