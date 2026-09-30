"""IMPROVE-23 (#130) -- LE CHAINON MANQUANT ENTRE T3b ET GH-01.

L'HISTOIRE, EN TROIS TEMPS
--------------------------
1. **T3b (12/07)** a enterre 21 garde-fous morts de `risk/`, dont `kill_switch`,
   `circuit_breaker` et `loss_halts`. Le motif ecrit sur chaque tombe :
   « remplace par `protections_v26` / `graded_halt` (**vivants**) ».

2. **GH-01 (13/07)** a decouvert que `protections_v26` et `graded_halt` avaient certes du code
   joignable... mais que **leurs interrupteurs n'etaient poses par AUCUN lanceur**. Ils ne se
   sont jamais executes.

   >>> UN REMPLACANT ETEINT N'EST PAS UN REMPLACANT. <<<

   Pendant ce temps, `kill_switch` etait enterre en son nom. On avait donc, pour de vrai :
   **aucun kill-switch du tout**, et un registre qui affirmait le contraire.

3. Ce test est l'invariant qui ferme le trou. Il exige que chaque tombe cite au moins un
   remplacant qui est **A LA FOIS** :
     * JOIGNABLE depuis un point d'entree (invariant T3b, sur les MODULES) ;
     * et, s'il a un interrupteur, **ALLUME** (invariant GH-01, sur les FLAGS).

T3b gardait les modules. GH-01 gardait les interrupteurs. **Rien ne gardait le LIEN entre les
deux** -- et c'est precisement dans ce lien que la contradiction vivait.
"""

from __future__ import annotations

import re
from pathlib import Path

from hl_observer.audit.cablage import (
    _points_d_entree,
    flags_poses,
    modules_atteignables,
)
from hl_observer.risk.interrupteurs import ALLUME, PAR_FLAG
from hl_observer.risk.tombstones import TOMBES

RACINE = Path(__file__).resolve().parents[1]
IGNORE = ("__pycache__", "_archive", "DISABLED")

#: Un nom de module cite dans le champ `remplace_par`, ex. "risk.graded_halt".
_CITE_MODULE = re.compile(
    r"\b((?:risk|signals|paper_trading|exits|edge|funding|copy_wallet|collection|ui"
    r"|simulation|copying|state|strategies|decision_engine)\.[a-z_][a-z0-9_]*)"
)

#: 🚩 CE QUE MA PREMIERE VERSION NE VOYAIT PAS.
#
# La tombe `trade_floor` cite `HYPERSMART_MIN_PAPER_NOTIONAL_USDT` : un FLAG, pas un module.
# Mon detecteur ne lisait que les modules -> il a crie « aucun remplacant » sur une tombe
# parfaitement legitime. **Un faux positif coute aussi cher qu'un faux negatif** : il fait jeter
# un resultat valide, et il apprend a l'equipe a ignorer le garde-fou.
#
# Mais je ne l'affaiblis pas -- je l'ELARGIS. Un flag cite comme remplacant doit, lui aussi,
# etre VIVANT : pose par un lanceur. Un garde-fou enterre au nom d'un flag que personne ne pose
# est exactement la meme maladie, sous un autre deguisement.
_CITE_FLAG = re.compile(r"\b(HYPERSMART_[A-Z0-9_]+)")

#: Et une FONCTION. `slippage_model` est enterre au nom de `live_costs_for` -- ni module, ni flag.
#
# Trois formes de remplacant existent donc, et il a fallu les trois echecs successifs de ce test
# pour que je les voie toutes. C'est la valeur d'un invariant : il ne se contente pas de ce que
# j'avais prevu. Une fonction-remplacante est vivante si un module JOIGNABLE l'APPELLE.
#
# 🚩 ET LE 4e FAUX POSITIF, qui m'a appris ou est la frontiere : ma 1re version acceptait
# n'importe quel mot de 6 lettres. Elle a donc "trouve" les fonctions `config()` et
# `reconciliation()` -- dans une phrase FRANCAISE qui disait « la config » et « la reconciliation
# PnL ». Coincidence de vocabulaire, pas citation de code.
#
# La regle qui separe les deux : un identifiant de CODE porte un `_`. Le francais, non.
# Ce n'est pas un affaiblissement : c'est refuser de traiter un mot de la langue comme une preuve.
_CITE_FONCTION = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")


def _collecter(motifs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in motifs:
        for p in RACINE.glob(motif):
            rel = p.relative_to(RACINE).as_posix()
            if any(x in rel for x in IGNORE):
                continue
            try:
                out[rel] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
    return out


def _nom_complet(court: str) -> str:
    return "hl_observer." + court


def _joignables() -> set[str]:
    py = _collecter(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    lanceurs = _collecter(("*.cmd", "*.ps1", "*.sh", "tools/**/*.cmd", "tools/**/*.ps1"))
    return modules_atteignables(py, _points_d_entree(py, "hl_observer", lanceurs))


def _flag_du_module(module_court: str) -> str | None:
    """L'interrupteur qui commande ce module, s'il en a un (registre GH-01)."""
    for flag, i in PAR_FLAG.items():
        if i.module == module_court or i.module.endswith("." + module_court.split(".")[-1]):
            return flag
    return None


def _est_vraiment_vivant(module_court: str, joignables: set[str]) -> tuple[bool, str]:
    """VIVANT = joignable ET (pas d'interrupteur OU interrupteur ALLUME).

    C'est la definition qui manquait. Un module peut etre parfaitement joignable, teste,
    importe... et ne jamais s'executer parce que son flag vaut "0".
    """
    if _nom_complet(module_court) not in joignables:
        return False, "MORT (joignable depuis aucun point d'entree)"
    flag = _flag_du_module(module_court)
    if flag is None:
        return True, "vivant (aucun interrupteur)"
    if PAR_FLAG[flag].decision == ALLUME:
        return True, "vivant (interrupteur %s ALLUME)" % flag
    return False, "🔴 ETEINT : son interrupteur %s est %s" % (flag, PAR_FLAG[flag].decision)


def _module_du_fichier(rel: str) -> str:
    """`src/hl_observer/edge/edge_source.py` -> `hl_observer.edge.edge_source`."""
    return rel.removeprefix("src/").removesuffix(".py").replace("/", ".")


def _fonction_est_vivante(nom: str, joignables: set[str]) -> tuple[bool, str] | None:
    """Une FONCTION-remplacante est vivante si un module JOIGNABLE l'APPELLE.

    Retourne None si `nom` n'est pas une fonction de notre code (le champ `remplace_par` est du
    francais : « les couts LIVE issus du carnet reel » -- « carnet » n'est pas une fonction).
    On ne retient donc que les identifiants qui existent VRAIMENT comme `def` chez nous.
    """
    src = {
        rel: txt
        for rel, txt in _collecter(("src/**/*.py",)).items()
        if not rel.startswith("src/hl_observer/audit/")
    }
    definie_dans = {_module_du_fichier(r) for r, t in src.items() if re.search(r"^\s*def %s\(" % nom, t, re.M)}
    if not definie_dans:
        return None  # ce n'est pas une fonction de chez nous : rien a verifier

    appelants = {
        _module_du_fichier(r)
        for r, t in src.items()
        if re.search(r"[^\w.]%s\(" % nom, t) and _module_du_fichier(r) not in definie_dans
    }
    vivants = sorted(m for m in appelants if m in joignables)
    if vivants:
        return True, "vivante (appelee par %s)" % ", ".join(vivants[:3])
    if not appelants:
        return False, "🔴 fonction DEFINIE mais APPELEE PAR PERSONNE"
    return False, "🔴 appelee seulement par des modules NON JOIGNABLES (%s)" % ", ".join(sorted(appelants)[:3])


def _flag_est_vivant(flag: str, poses: dict[str, set[str]] | dict) -> tuple[bool, str]:
    """Un FLAG cite comme remplacant doit etre POSE par un lanceur.

    Sinon : le garde-fou est enterre au nom d'une config que personne ne regle. C'est la meme
    maladie que le module eteint -- juste un deguisement de plus.
    """
    if flag in poses:
        ou = poses[flag]
        ou = ", ".join(sorted(Path(p).name for p in ou)) if not isinstance(ou, str) else str(ou)
        return True, "vivant (pose par %s)" % ou
    return False, "🔴 flag POSE PAR AUCUN LANCEUR"


def test_chaque_TOMBE_cite_au_moins_UN_remplacant_vraiment_vivant():
    """🔴 L'INVARIANT. Enterrer un garde-fou au nom d'un remplacant ETEINT, c'est n'avoir AUCUN
    garde-fou tout en croyant en avoir un.

    « Ce n'est pas l'absence de garde-fou qui fait mal. C'est le garde-fou qu'on CROIT avoir. »
    """
    joignables = _joignables()
    lanceurs = _collecter(("*.cmd", "*.ps1", "*.sh", "tools/**/*.cmd", "tools/**/*.ps1"))
    poses = flags_poses(lanceurs)
    coupables: list[str] = []

    # Ces motifs-la n'invoquent AUCUN remplacant : « impossible en paper » (il n'y a pas de
    # broker a reconcilier), « strategie, pas garde-fou », « realisme, pas garde-fou ». Rien a
    # verifier -- et surtout, ne pas aller pecher un mot de leur prose pour en faire une preuve.
    SANS_REMPLACANT = {"IMPOSSIBLE_EN_PAPER", "STRATEGIE_PAS_GARDE_FOU", "REALISME_PAS_GARDE_FOU"}

    for t in TOMBES:
        if t.motif in SANS_REMPLACANT:
            continue

        # Un remplacant peut etre un MODULE... ou un FLAG (une config qui fait le travail).
        # Les deux doivent etre VIVANTS. Ne verifier que les modules, c'etait etre aveugle
        # a la moitie du probleme.
        etats: list[tuple[str, bool, str]] = [
            (m, *_est_vraiment_vivant(m, joignables)) for m in _CITE_MODULE.findall(t.remplace_par)
        ]
        etats += [(f, *_flag_est_vivant(f, poses)) for f in _CITE_FLAG.findall(t.remplace_par)]

        # ... et une FONCTION (`slippage_model` -> `live_costs_for`). Les mots francais du texte
        # sont ignores d'office : seuls les identifiants qui existent comme `def` chez nous comptent.
        for nom in _CITE_FONCTION.findall(t.remplace_par):
            verdict = _fonction_est_vivante(nom, joignables)
            if verdict is not None:
                etats.append((nom + "()", *verdict))

        assert etats, (
            "la tombe `%s` (motif %s) ne cite AUCUN remplacant VERIFIABLE (ni module, ni flag, "
            "ni fonction) : elle ne cite que de la prose.\n"
            "Un DOUBLON de rien n'est pas un doublon. Ecris un nom que la machine peut aller "
            "verifier -- sinon la tombe n'est qu'une affirmation, et les affirmations sont "
            "exactement ce qui nous a menti sept fois." % (t.module, t.motif)
        )

        if not any(vivant for _, vivant, _ in etats):
            coupables.append(
                "%s (motif %s) -> AUCUN remplacant vivant :\n      %s"
                % (
                    t.module,
                    t.motif,
                    "\n      ".join("%s : %s" % (m, raison) for m, _, raison in etats),
                )
            )

    assert not coupables, (
        "🔴 TOMBE(S) SANS REMPLACANT VIVANT -- le garde-fou est enterre, et rien ne fait son "
        "travail :\n\n  "
        + "\n\n  ".join(coupables)
        + "\n\nUn remplacant MORT ou ETEINT n'est pas un remplacant. Soit on rallume le "
          "remplacant, soit on deterre l'enterre -- jamais l'entre-deux."
    )


def test_les_TROIS_halts_de_IMPROVE_23_ont_bien_un_successeur_ALLUME():
    """La question exacte de #130, posee nommement.

    `kill_switch`, `circuit_breaker`, `loss_halts` : enterres. Qui fait leur travail, MAINTENANT ?
    Reponse exigee : `protections_v26` et/ou `graded_halt`, joignables ET allumes (GH-01).
    """
    joignables = _joignables()
    for successeur in ("risk.protections_v26", "risk.graded_halt"):
        vivant, raison = _est_vraiment_vivant(successeur, joignables)
        assert vivant, (
            "%s est cense remplacer le kill-switch enterre, et il est %s.\n"
            "Sans lui, IMPROVE-23 n'est pas resolue : elle est CACHEE." % (successeur, raison)
        )


def test_un_FLAG_cite_comme_remplacant_doit_etre_POSE_par_un_lanceur():
    """🚩 LE FAUX POSITIF QUI M'A APPRIS QUELQUE CHOSE (13/07).

    Ma 1re version de cet invariant ne lisait que les MODULES. Elle a crie « aucun remplacant »
    sur la tombe `trade_floor`... qui cite un FLAG (`HYPERSMART_MIN_PAPER_NOTIONAL_USDT`).
    C'etait un FAUX POSITIF -- et un faux positif coute aussi cher qu'un faux negatif : il fait
    jeter un resultat valide, et il apprend a ignorer le garde-fou.

    Je ne l'ai pas affaibli pour le faire passer : je l'ai ELARGI. Un flag-remplacant doit
    lui aussi etre vivant, c'est-a-dire POSE par un lanceur. Un garde-fou enterre au nom d'une
    config que personne ne regle, c'est la meme maladie sous un autre deguisement.
    """
    poses = flags_poses(_collecter(("*.cmd", "*.ps1", "*.sh", "tools/**/*.cmd", "tools/**/*.ps1")))

    vivant, raison = _flag_est_vivant("HYPERSMART_MIN_PAPER_NOTIONAL_USDT", poses)
    assert vivant, (
        "`trade_floor` est enterre au nom du flag HYPERSMART_MIN_PAPER_NOTIONAL_USDT, "
        "et ce flag %s. Le plancher de notionnel ne s'applique donc PAS." % raison
    )

    # ... et le detecteur doit vraiment savoir dire NON.
    faux, raison_faux = _flag_est_vivant("HYPERSMART_FLAG_QUI_N_EXISTE_PAS", poses)
    assert not faux and "AUCUN LANCEUR" in raison_faux


def test_une_FONCTION_citee_comme_remplacante_doit_etre_APPELEE_par_un_module_joignable():
    """🚩 LE 2e FAUX POSITIF -- et la 3e forme de remplacant.

    `slippage_model` est enterre au nom de `live_costs_for` : ni module, ni flag, mais une
    FONCTION. Il a fallu que ce test echoue TROIS fois pour que je voie les trois formes.
    C'est exactement la valeur d'un invariant : il ne se contente pas de ce que j'avais prevu.

    ⚠️ Rappel de la tombe : ressusciter `slippage_model` serait une REGRESSION (il rendait un
    slippage CONSTANT -- le bug meme que P2-2 a corrige). C'est donc `live_costs_for` qui doit
    vivre, sans quoi les couts redeviennent des constantes inventees.
    """
    joignables = _joignables()

    verdict = _fonction_est_vivante("live_costs_for", joignables)
    assert verdict is not None, "`live_costs_for` n'existe plus comme fonction : la tombe ment"
    vivante, raison = verdict
    assert vivante, (
        "`slippage_model` est enterre au nom de `live_costs_for`, et cette fonction %s.\n"
        "Les couts d'execution ne viendraient donc de NULLE PART -- exactement le bug de P2-2." % raison
    )

    # Le detecteur doit savoir dire NON -- et savoir se taire sur un mot francais.
    assert _fonction_est_vivante("carnet", joignables) is None


def test_une_TOMBE_ne_peut_pas_citer_de_la_PROSE_comme_remplacant():
    """🚩 LE 3e FAUX POSITIF -- celui ou j'ai arrete d'elargir le detecteur.

    `stale_data_guard` citait « signal_age, CURRENT_MID_REQUIRED » : des noms de CHAMPS. J'aurais
    pu ajouter une 4e forme (l'attribut) et faire passer le test. Je ne l'ai pas fait, parce que
    « ce champ existe quelque part » ne prouve RIEN : un champ ne refuse pas une entree, un
    module le fait.

    La correction est allee dans la DONNEE, pas dans le detecteur : la tombe cite maintenant les
    modules qui refusent VRAIMENT un signal perime. C'est un DURCISSEMENT, pas un contournement --
    et la distinction est exactement celle que je dois savoir tenir quand un de mes tests rougit.
    """
    joignables = _joignables()
    tombe = next(t for t in TOMBES if t.module == "stale_data_guard")

    cites = _CITE_MODULE.findall(tombe.remplace_par)
    assert cites, "la tombe de `stale_data_guard` est retombee dans la prose invérifiable"

    vivants = [m for m in cites if _est_vraiment_vivant(m, joignables)[0]]
    assert vivants, (
        "aucun des refuseurs de fraicheur cites n'est vivant : %s.\n"
        "Le signal perime ne serait donc refuse par PERSONNE -- alors que la fraicheur est le "
        "gate le plus applique du projet." % cites
    )


def test_l_invariant_ATTRAPE_vraiment_un_remplacant_eteint():
    """Un garde-fou qui ne peut pas echouer ne garde rien. On lui donne le cas qu'il doit voir.

    On simule un module dont l'interrupteur est ETEINT_VOLONTAIREMENT (`kelly_leader_book`,
    eteint par decision explicite en GH-01) : il ne doit PAS compter comme remplacant vivant.
    """
    joignables = _joignables() | {"hl_observer.risk.kelly_leader_book"}
    vivant, raison = _est_vraiment_vivant("risk.kelly_leader_book", joignables)
    assert not vivant, "un module joignable mais ETEINT est compte comme vivant : l'invariant est aveugle"
    assert "ETEINT" in raison
