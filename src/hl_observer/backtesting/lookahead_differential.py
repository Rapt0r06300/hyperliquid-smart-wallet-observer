"""G1 -- LE TEST DIFFERENTIEL DE LOOKAHEAD. Il ne lit PAS le code : il le TORTURE.

POURQUOI PAS `assert_no_lookahead` ?
------------------------------------
`backtest/no_lookahead_guard.py` verifie des paires `(decision_ts, data_ts)` : il rale si une
decision utilise une donnee plus recente qu'elle. C'est correct -- et **inutile ici**.

Dans la recherche de scenarios (`scenario_search._eval_pairs`), la decision d'entree ne lit QUE
des champs du candidat (`edge_remaining_bps`, `signal_age_ms`, `liquidity_score`,
`consensus_wallets`, `leader_score`, `copy_degradation_bps`), tous horodates a `recorded_at`,
c'est-a-dire **a l'instant meme de la decision**. Donc `data_ts == decision_ts` par construction :
le garde-fou passerait TRIVIALEMENT, sur tous les scenarios, toujours.

**Un garde-fou qui ne peut pas echouer ne garde rien.** Le brancher la aurait ete du theatre : on
aurait coche « lookahead : OK » sans avoir rien verifie. C'est exactement le genre de faux confort
qu'on chasse depuis le debut.

CE QU'ON VERIFIE A LA PLACE
---------------------------
La seule propriete qui compte, et qu'aucune inspection de timestamps ne peut donner :

    >>> LA SELECTION D'ENTREE DOIT ETRE INVARIANTE AU FUTUR. <<<

Si on change ce qui se passe APRES l'entree, l'ensemble des candidats ACCEPTES ne doit pas bouger
d'un iota. Le PnL, lui, doit bouger -- c'est normal, c'est le resultat. Mais la DECISION, non.

On le teste en TORTURANT les donnees, sans jamais lire le code decisionnel :

  * `FUTUR_BROUILLE`  : les marks posterieurs a l'entree sont remplaces par du bruit ;
  * `FUTUR_EFFACE`    : ils sont purement supprimes ;
  * `FUTUR_INVERSE`   : le chemin futur est retourne (le prix fait exactement l'inverse).

Dans les trois cas, la meme liste de candidats doit etre acceptee. Sinon : FUITE.

⚠️ CE QUE CE TEST NE COUVRE PAS -- et il faut le dire
-----------------------------------------------------
Il verifie que la RECHERCHE ne lit pas le futur. Il ne peut PAS savoir si un champ du candidat a
ete calcule avec de l'information future **au moment de l'enregistrement**. Cette question-la
appartient au collecteur, pas au backtest. Un test ne peut pas prouver ce qu'il ne voit pas, et
pretendre le contraire serait le mensonge qu'on essaie d'eviter.

Module PUR : aucune I/O, aucun reseau, aucun ordre. Simulation paper uniquement.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

FUTUR_REEL = "FUTUR_REEL"
FUTUR_BROUILLE = "FUTUR_BROUILLE"
FUTUR_EFFACE = "FUTUR_EFFACE"
FUTUR_INVERSE = "FUTUR_INVERSE"

TORTURES = (FUTUR_BROUILLE, FUTUR_EFFACE, FUTUR_INVERSE)

FUITE_SELECTION_DEPEND_DU_FUTUR = "FUITE_LA_SELECTION_D_ENTREE_DEPEND_DU_FUTUR"


@dataclass(frozen=True, slots=True)
class Verdict:
    propre: bool
    n_candidats: int
    acceptes_reel: int
    ecarts: dict[str, int] = field(default_factory=dict)   # torture -> nb de differences
    exemples: tuple[str, ...] = field(default_factory=tuple)
    raison: str = ""

    @property
    def lookahead(self) -> bool:
        """🚩 LA DISTINCTION QUE MON PREMIER OUTIL RATAIT -- et qui changeait le verdict.

        Les trois tortures ne disent PAS la meme chose :

          BROUILLE / INVERSE : le futur EXISTE mais il MENT (bruit, ou chemin retourne).
              Si la selection change -> elle a LU ce futur. C'est du LOOKAHEAD. Fatal.

          EFFACE : le futur N'EXISTE PLUS.
              La selection change forcement : sans prix futur, il n'y a pas de PnL a mesurer.
              Ce n'est pas de la triche, c'est de la MESURABILITE. Ca s'appelle de la
              SURVIVANCE : il faut la CHIFFRER, pas la confondre avec une fuite.

        Un detecteur qui melange les deux fabrique une fausse alarme -- et une fausse alarme
        fait jeter un resultat valide. C'est aussi grave qu'un faux OK.
        """
        return bool(self.ecarts.get(FUTUR_BROUILLE, 0) or self.ecarts.get(FUTUR_INVERSE, 0))

    @property
    def survivance(self) -> int:
        """Nb de candidats qui n'etaient evaluables QUE parce qu'un mark futur existait."""
        return int(self.ecarts.get(FUTUR_EFFACE, 0))

    def as_dict(self) -> dict:
        return {
            "propre": self.propre,
            "lookahead": self.lookahead,
            "survivance": self.survivance,
            "n_candidats": self.n_candidats,
            "acceptes_reel": self.acceptes_reel,
            "ecarts": dict(self.ecarts),
            "exemples": list(self.exemples),
            "raison": self.raison,
        }


def _cle(c: dict) -> str:
    """Identite STABLE d'un candidat -- sans le prix futur, evidemment."""
    return "|".join((
        str(c.get("coin") or ""),
        str(c.get("direction") or ""),
        f"{float(c.get('recorded_at') or 0.0):.3f}",
        f"{float(c.get('current_mid') or 0.0):.10g}",
    ))


def torturer_les_marks(
    marks: dict[str, list[tuple[float, float]]],
    *,
    coupure_ts: float,
    mode: str,
    seed: int = 20260713,
) -> dict[str, list[tuple[float, float]]]:
    """Rend un carnet de marks dont le FUTUR (t > coupure_ts) est detruit. Le PASSE est intact.

    Le passe DOIT rester intact : on veut isoler la dependance au futur, pas casser l'entree.
    """
    rng = random.Random(seed)
    out: dict[str, list[tuple[float, float]]] = {}
    for coin, chemin in (marks or {}).items():
        passe = [(t, m) for (t, m) in chemin if t <= coupure_ts]
        futur = [(t, m) for (t, m) in chemin if t > coupure_ts]

        if mode == FUTUR_EFFACE:
            out[coin] = passe
        elif mode == FUTUR_BROUILLE:
            base = passe[-1][1] if passe else (futur[0][1] if futur else 1.0)
            out[coin] = passe + [
                (t, max(1e-12, base * (1.0 + rng.uniform(-0.20, 0.20)))) for (t, _m) in futur
            ]
        elif mode == FUTUR_INVERSE:
            # meme horodatage, prix retourne : le futur fait exactement l'inverse.
            prix = [m for (_t, m) in futur][::-1]
            out[coin] = passe + [(t, prix[i]) for i, (t, _m) in enumerate(futur)]
        else:
            out[coin] = list(chemin)
    return out


def selection_invariante_au_futur(
    selectionner,
    candidats: list[dict],
    marks: dict[str, list[tuple[float, float]]],
    *,
    coupure_ts: float | None = None,
    tortures: tuple[str, ...] = TORTURES,
) -> Verdict:
    """`selectionner(candidats, marks) -> iterable de candidats ACCEPTES`.

    On appelle la MEME fonction avec le vrai futur, puis avec un futur detruit de trois facons.
    La liste des acceptes doit etre IDENTIQUE. Le PnL peut changer -- pas la decision.

    On ne lit pas le code de `selectionner`. On le juge sur pieces.
    """
    if not candidats:
        return Verdict(True, 0, 0, raison="AUCUN_CANDIDAT")

    if coupure_ts is None:
        # La coupure doit etre AVANT le premier signal, sinon on ne detruit pas le futur de
        # tous les candidats -- on n'en testerait qu'une partie, et on se rassurerait a tort.
        coupure_ts = min(float(c.get("recorded_at") or 0.0) for c in candidats)

    ref = sorted(_cle(c) for c in selectionner(candidats, marks))
    ecarts: dict[str, int] = {}
    exemples: list[str] = []

    for mode in tortures:
        faux = torturer_les_marks(marks, coupure_ts=float(coupure_ts), mode=mode)
        obs = sorted(_cle(c) for c in selectionner(candidats, faux))
        if obs != ref:
            manquants = set(ref) - set(obs)
            apparus = set(obs) - set(ref)
            ecarts[mode] = len(manquants) + len(apparus)
            for k in list(manquants)[:2]:
                exemples.append(f"{mode}: DISPARU {k}")
            for k in list(apparus)[:2]:
                exemples.append(f"{mode}: APPARU  {k}")

    propre = not ecarts
    return Verdict(
        propre=propre,
        n_candidats=len(candidats),
        acceptes_reel=len(ref),
        ecarts=ecarts,
        exemples=tuple(exemples[:8]),
        raison="" if propre else FUITE_SELECTION_DEPEND_DU_FUTUR,
    )


__all__ = [
    "FUTUR_REEL", "FUTUR_BROUILLE", "FUTUR_EFFACE", "FUTUR_INVERSE", "TORTURES",
    "FUITE_SELECTION_DEPEND_DU_FUTUR",
    "Verdict", "torturer_les_marks", "selection_invariante_au_futur",
]
