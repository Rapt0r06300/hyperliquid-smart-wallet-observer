"""#318 / P2-6 — LES HORLOGES. Ou : comment la FRAICHEUR devient FABRIQUEE (2026-07-13).

`signal_age` est **la porte qui autorise les entrees** (fresh <= 10 s). Si elle ment, tout ment.
Et elle mentait, de deux facons independantes.

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 BUG 1 — LE « MAINTENANT » AUTO-REFERENTIEL  (`strategies/fusion_runtime.py`)
═══════════════════════════════════════════════════════════════════════════════════════════════

    context_now_ms = max([0] + [e.event_time_ms ...] + [v.observed_at_ms for v in leader_votes])
    last_vote_ms   = max([0] + [v.observed_at_ms for v in winning_votes])
    signal_age_ms  = context_now_ms - last_vote_ms

Le « maintenant » est calcule **A PARTIR DES DONNEES**, y compris du signal qu'on est en train de
dater. Deux consequences, toutes deux silencieuses :

  * si le vote GAGNANT est le plus recent de tous (cas frequent : un signal frais gagne), alors
    `context_now == last_vote` et **l'age vaut ZERO par construction.** Ce n'est pas une mesure,
    c'est une **tautologie** ;
  * si le flux de prix **CALE** (c'est arrive DEUX fois : 02:32 et 04:08), `context_now` **GELE**.
    Un signal vieux de dix minutes reste alors eternellement « frais » -- **et le bot entre.**

*Une horloge qui s'arrete quand les donnees s'arretent ne mesure plus le temps : elle mesure les
donnees.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 BUG 2 — DEUX DOMAINES D'HORLOGE DANS UN SEUL CHAMP  (`copying/runtime_v9_adapter.py`)
═══════════════════════════════════════════════════════════════════════════════════════════════

    source_ts_ms = leader_exchange_ts or observed_at_ms

Ce champ contient **soit l'horloge de l'exchange, soit la notre**, selon ce qui est disponible.
Comparer deux valeurs de ce champ, ou en soustraire une d'une autre, **n'a aucun sens** : ce sont
deux referentiels differents, decales d'un ecart inconnu.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE MODULE : les horloges sont NOMMEES, et un age ne se calcule QUE dans un seul domaine.
DENY-BY-DEFAULT : si on ne peut pas garantir le domaine, on rend `None` -> `INSUFFICIENT_DATA`.
Jamais un zero rassurant.

PUR (aucun appel a `time`) : le `now` est TOUJOURS injecte. C'est ce qui rend le module testable
-- et c'est aussi ce qui empeche un futur appelant de re-fabriquer un « maintenant » a partir des
donnees : il doit le fournir explicitement, donc l'assumer.

Aucun ordre reel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# ---------------------------------------------------------------------------------------------
# LES DEUX DOMAINES. Ils ne se melangent pas. Jamais.
# ---------------------------------------------------------------------------------------------
LOCAL = "LOCAL"          # notre montre : l'instant ou NOUS avons observe
EXCHANGE = "EXCHANGE"    # la montre de Hyperliquid : l'instant ou l'evenement s'est produit
INCONNU = "INCONNU"      # on ne sait pas -> on ne calcule RIEN

DOMAINES = (LOCAL, EXCHANGE)

MOTIF_DOMAINES_MELANGES = "AGE_ENTRE_DEUX_HORLOGES_DIFFERENTES_NO_TRADE"
MOTIF_HORLOGE_INCONNUE = "DOMAINE_D_HORLOGE_INCONNU_NO_TRADE"
MOTIF_NOW_ANTERIEUR = "MAINTENANT_ANTERIEUR_A_L_OBSERVATION_HORLOGE_INCOHERENTE"
MOTIF_NOW_DERIVE_DES_DONNEES = "MAINTENANT_DERIVE_DES_DONNEES_TAUTOLOGIE"

# Au-dela, l'ecart entre notre montre et celle de l'exchange n'est plus du bruit : c'est un bug.
ECART_HORLOGE_MAX_MS = 5_000.0


@dataclass(frozen=True, slots=True)
class Instant:
    """Un horodatage QUI SAIT D'OU IL VIENT. C'est tout l'objet du module."""

    ms: int
    domaine: str            # LOCAL | EXCHANGE | INCONNU

    @property
    def utilisable(self) -> bool:
        return self.domaine in DOMAINES and self.ms > 0


def local(ms: int | float | None) -> Instant:
    return Instant(ms=int(ms or 0), domaine=LOCAL if ms else INCONNU)


def exchange(ms: int | float | None) -> Instant:
    return Instant(ms=int(ms or 0), domaine=EXCHANGE if ms else INCONNU)


def inconnu(ms: int | float | None = 0) -> Instant:
    """🚩 CE QUE `leader_exchange_ts or observed_at_ms` PRODUISAIT REELLEMENT.

    Un horodatage dont on ne sait plus s'il vient de notre montre ou de celle de l'exchange.
    Il n'est PAS utilisable pour un age. On le nomme, pour qu'il ne se cache plus.
    """
    return Instant(ms=int(ms or 0), domaine=INCONNU)


@dataclass(frozen=True, slots=True)
class Age:
    ms: float | None            # None = on ne sait pas. JAMAIS 0 par defaut.
    motif: str

    @property
    def connu(self) -> bool:
        return self.ms is not None

    def as_dict(self) -> dict[str, Any]:
        return {"age_ms": self.ms, "motif": self.motif, "real_execution": False}


AGE_OK = "AGE_MESURE"


def age(observation: Instant, maintenant: Instant) -> Age:
    """L'age d'une observation. **Dans UN SEUL domaine, ou pas du tout.**

    C'est la fonction qui remplace `context_now_ms - last_vote_ms`.
    """
    if not observation.utilisable or not maintenant.utilisable:
        return Age(None, MOTIF_HORLOGE_INCONNUE)
    if observation.domaine != maintenant.domaine:
        # 🔴 LE BUG 2. Soustraire l'heure de Hyperliquid de la notre donne un nombre... qui ne
        # veut RIEN dire. Et ce nombre autorisait des entrees.
        return Age(None, MOTIF_DOMAINES_MELANGES)
    delta = float(maintenant.ms - observation.ms)
    if delta < 0:
        # Notre montre est AVANT l'observation : soit un decalage d'horloge, soit un rejeu.
        # Dans les deux cas on ne sait pas dater -> on refuse. (L'ancien code faisait `max(0, ...)`
        # -> il transformait une INCOHERENCE en « parfaitement frais ».)
        return Age(None, MOTIF_NOW_ANTERIEUR)
    return Age(delta, AGE_OK)


def ecart_horloges(local_ms: int, exchange_ms: int) -> float:
    """De combien notre montre retarde-t-elle sur celle de l'exchange ?

    On ne le CORRIGE pas (on n'a pas de NTP ici) : on le MESURE, et on refuse si c'est trop gros.
    Un ecart de plusieurs secondes rendrait toute mesure de fraicheur fantaisiste.
    """
    return float(local_ms) - float(exchange_ms)


def horloges_coherentes(local_ms: int, exchange_ms: int,
                        *, max_ms: float = ECART_HORLOGE_MAX_MS) -> bool:
    return abs(ecart_horloges(local_ms, exchange_ms)) <= float(max_ms)


# =============================================================================================
# 🔴 L'INVARIANT DU BUG 1 : un « maintenant » ne peut pas venir des donnees qu'il date.
# =============================================================================================


def maintenant_est_derive_des_donnees(maintenant_ms: int, horodatages: Iterable[int]) -> bool:
    """Le « maintenant » est-il simplement le MAX des donnees ? Alors ce n'est pas une horloge.

    C'est exactement ce que faisait `context_now_ms = max(...)` : le signal le plus recent
    definissait lui-meme l'instant present -- donc son propre age etait ZERO.

    ⚠️ Ce n'est pas une heuristique fragile : on teste l'EGALITE avec le maximum. Si le
    « maintenant » vaut PILE le plus recent horodatage disponible, il n'apporte **aucune
    information exterieure aux donnees**. Une vraie horloge est, elle, toujours strictement
    posterieure -- ne serait-ce que du temps de traitement.
    """
    ts = [int(t) for t in horodatages if t]
    if not ts:
        return False
    return int(maintenant_ms) == max(ts)


def age_du_signal(
    *,
    observe_a_ms: int,
    maintenant_local_ms: int,
    horodatages_du_lot: Iterable[int] = (),
) -> Age:
    """LA fonction qui remplace le calcul de `signal_age_ms` dans `fusion_runtime`.

    Trois refus possibles, tous explicites :
      1. horloges melangees   -> on ne date pas ;
      2. « maintenant » < observation -> incoherence, on ne date pas (l'ancien code rendait 0) ;
      3. « maintenant » derive des donnees -> **tautologie**, on ne date pas.

    Sinon : l'age, en millisecondes, dans le domaine LOCAL.
    """
    if maintenant_est_derive_des_donnees(maintenant_local_ms, horodatages_du_lot):
        return Age(None, MOTIF_NOW_DERIVE_DES_DONNEES)
    return age(local(observe_a_ms), local(maintenant_local_ms))


__all__ = [
    "AGE_OK", "DOMAINES", "ECART_HORLOGE_MAX_MS", "EXCHANGE", "INCONNU", "LOCAL",
    "MOTIF_DOMAINES_MELANGES", "MOTIF_HORLOGE_INCONNUE", "MOTIF_NOW_ANTERIEUR",
    "MOTIF_NOW_DERIVE_DES_DONNEES",
    "Age", "Instant",
    "age", "age_du_signal", "ecart_horloges", "exchange", "horloges_coherentes", "inconnu",
    "local", "maintenant_est_derive_des_donnees",
]
