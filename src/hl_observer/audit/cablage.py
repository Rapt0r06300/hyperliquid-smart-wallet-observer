"""L'AUDIT DE CABLAGE : « QUI APPELLE CE MODULE ? » (T3, 2026-07-12)

LA PATHOLOGIE QUE CE MODULE TRAQUE
----------------------------------
Le projet a une maladie recurrente, et elle a un nom :

    **la capacite est presente, l'interrupteur est eteint, et personne ne rale.**

Le releve des cas deja trouves, tous par accident, jamais par un outil :

  * le **poller de carnet L2** n'a JAMAIS demarre : son unique point de depart etait derriere
    un flag absent du launcher. Aucun log, aucune erreur, un `l2_book.jsonl` inexistant pendant
    des semaines -- et tout le market making etait intestable sans qu'on le sache ;
  * la **jambe de funding** : exactement le meme bug, corrige le 08/07. Une jambe reparee,
    l'autre laissee ;
  * le **garde-fou lookahead** n'est pas branche sur la recherche 150 M ;
  * le **copy-follow** n'etait pas garde par le verrou d'edge ;
  * `delta_neutral_carry.py` (trouve pendant T2) : un module PUR, TESTE, complet... a qui
    **personne n'a jamais donne de donnees reelles**. Il repondait a la question. On ne la lui
    a jamais posee.

Ces cinq bugs ont ete trouves un par un, par hasard, apres des semaines. Cet outil les aurait
tous rendus visibles en une seconde.

TROIS CATEGORIES, ET LA TROISIEME EST LA PLUS DANGEREUSE
-------------------------------------------------------
1. **ORPHELIN**            -- module importe par PERSONNE. Du code mort, franc.
2. **TESTE MAIS NON BRANCHE** -- module importe UNIQUEMENT par les tests. Le pire des deux
   mondes : la suite est verte, la capacite existe, elle a des tests... et aucun chemin de
   production ne l'appelle. C'est la signature exacte de `delta_neutral_carry`.

   ⚠️ CE QUE CET OUTIL MESURE, EXACTEMENT : l'**atteignabilite par IMPORT** depuis les vraies
   portes (`__main__`, `cli`, `ui`). **Importe n'est PAS appele.** `edge_calculator` est
   IMPORTE a chaque demarrage (via `edge/__init__.py`), mais sa fonction `compute_net_edge`
   n'est appelee par AUCUN chemin de production -- le moteur d'edge vivant est `edge_net_v12`.
   Un module ici declare "vivant" peut donc n'etre qu'un import mort. L'outil borne le
   probleme par le HAUT : ce qu'il declare MORT l'est vraiment ; ce qu'il declare vivant
   reste a verifier a la main. Il ne ment jamais dans le sens rassurant.
3. **INTERRUPTEUR MORT**   -- un flag d'environnement LU par le code avec un defaut FAUX, et
   POSE par aucun lanceur. La capacite est la, le code la lit, et elle est eteinte **pour
   toujours**, en silence. C'est le bug du poller L2, mot pour mot.

PUR, sans I/O : on lui donne des sources, il rend un verdict. Aucun ordre reel.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# Un defaut qui vaut ceci = la capacite est ETEINTE, sans ambiguite possible.
DEFAUTS_ETEINTS = {"0", "false", "no", "off"}

# Un defaut VIDE est AMBIGU, et le classer "eteint" etait une sur-interpretation de ma part :
#   HYPERSMART_TOP_WALLET_SAMPLE_LIMIT = ""  ->  "aucune limite"  = PERMISSIF, pas eteint
#   HYPERSMART_PNL_AUDIT_PREFER_APPEND_ONLY = ""  ->  falsy        = eteint, probablement
# Les deux s'ecrivent pareil. On ne peut pas trancher depuis le defaut seul -- alors on ne
# tranche PAS. On les signale a part, pour une lecture humaine.
# (Meme discipline que le reste du projet : donnee ambigue -> on n'affirme rien.)
DEFAUTS_AMBIGUS = {"", "none", "null"}

# Ces modules sont des points d'entree : personne ne les importe, et c'est NORMAL.
POINTS_D_ENTREE = ("__main__", "__init__", "cli", "conftest")


@dataclass(frozen=True, slots=True)
class Interrupteur:
    """Un flag d'environnement, et QUI le lit / QUI le pose."""

    nom: str
    defaut: str | None
    lu_par: tuple[str, ...]
    pose_par: tuple[str, ...]

    @property
    def mort(self) -> bool:
        """Lu par le code, avec un defaut SANS AMBIGUITE eteint, et pose par AUCUN lanceur.
        La capacite existe, elle est cablee, et elle ne s'allumera jamais."""
        if self.pose_par:
            return False
        if self.defaut is None:
            return False                      # pas de defaut lisible -> on n'affirme rien
        return self.defaut.strip().lower() in DEFAUTS_ETEINTS

    @property
    def ambigu(self) -> bool:
        """Defaut vide : « aucune limite » (permissif) ou « eteint » ? Les deux s'ecrivent
        pareil. On ne tranche PAS -- on demande une lecture humaine."""
        if self.pose_par or self.defaut is None:
            return False
        return self.defaut.strip().lower() in DEFAUTS_AMBIGUS

    def as_dict(self) -> dict[str, Any]:
        return {"nom": self.nom, "defaut": self.defaut, "lu_par": list(self.lu_par),
                "pose_par": list(self.pose_par), "mort": self.mort, "ambigu": self.ambigu}


@dataclass
class Verdict:
    orphelins: list[str] = field(default_factory=list)
    testes_non_branches: list[str] = field(default_factory=list)
    interrupteurs: list[Interrupteur] = field(default_factory=list)

    # LA QUATRIEME PORTE : LES OUTILS DE RECHERCHE (#597, 2026-07-13)
    #
    # Modules INATTEIGNABLES depuis le bot vivant, mais atteignables depuis un script
    # `tools/*.py` qu'un lanceur (.cmd/.ps1) demarre pour de vrai. Ce n'est PAS du code mort :
    # c'est le runtime de RECHERCHE. `scenario_search` -- le moteur qui a evalue 150 M de
    # scenarios, lance des dizaines de fois -- tombait ici, et l'audit le declarait "mort".
    #
    # ⚠️ MAIS CE N'EST PAS "VIVANT" NON PLUS. Un garde-fou de `risk/` joignable uniquement
    # depuis un script d'audit ne protege AUCUNE position. Pour les paquets du chemin de
    # production, `outille` doit continuer a compter comme MORT (cf. test_risk_guards_no_limbo).
    outilles: list[str] = field(default_factory=list)

    # LE GARDE-FOU DE L'AUDIT LUI-MEME.
    # `_importes_par` avale les SyntaxError en silence -> un fichier illisible n'importe RIEN,
    # et tout ce qu'il appelait devient "mort". Or le mount TRONQUE les gros fichiers : si
    # `cli.py` (3400 lignes) arrive coupe, l'audit rendrait un rapport catastrophiste et FAUX.
    # Un audit qui ment est pire que pas d'audit : il rassure, ou il affole -- au hasard.
    # Donc on ne les cache pas : on les NOMME, et l'appelant doit s'arreter s'il y en a.
    illisibles: list[str] = field(default_factory=list)

    @property
    def interrupteurs_morts(self) -> list[Interrupteur]:
        return [i for i in self.interrupteurs if i.mort]

    @property
    def fiable(self) -> bool:
        """FAUX des qu'un fichier n'a pas pu etre lu -- le verdict n'est alors pas opposable."""
        return not self.illisibles

    def as_dict(self) -> dict[str, Any]:
        return {
            "orphelins": self.orphelins,
            "testes_non_branches": self.testes_non_branches,
            "outilles": self.outilles,
            "interrupteurs_morts": [i.as_dict() for i in self.interrupteurs_morts],
            "illisibles": self.illisibles,
            "fiable": self.fiable,
            "real_execution": False,
        }


# ----------------------------------------------------------------- le graphe des imports

def _sans_bom(source: str) -> str:
    """Retire le BOM UTF-8 (U+FEFF) en tete.

    POURQUOI (2026-07-12) -- ET C'ETAIT ENCORE UN BUG DE MON PROPRE AUDIT
    --------------------------------------------------------------------
    Mon garde-fou "fichier illisible" a immediatement accuse
    `tests/test_testnet_mode_controlled.py` :

        SyntaxError : invalid non-printable character U+FEFF   (ligne 1, col 1)

    Or ce fichier est PARFAITEMENT valide : quand Python lit un `.py`, il DETECTE et RETIRE
    le BOM. pytest l'importe sans broncher. C'est `ast.parse()` sur une chaine que J'AI
    decodee en `utf-8` (au lieu de `utf-8-sig`) qui gardait le BOM et s'etranglait dessus.

    Le garde-fou a bien joue son role -- il a refuse de conclure plutot que de rendre un
    faux verdict. Mais il accusait un innocent. **Suspecter son propre outil avant le code
    d'autrui** : c'est la meme lecon que "suspecter la fixture avant le code", d'un cran
    au-dessus.
    """
    return source.lstrip("﻿")


def _module_de(chemin: str) -> str:
    """'src/hl_observer/funding/delta_neutral_carry.py' -> 'hl_observer.funding.delta_neutral_carry'"""
    c = chemin.replace("\\", "/")
    for prefixe in ("src/", "./"):
        if c.startswith(prefixe):
            c = c[len(prefixe):]
    if c.endswith(".py"):
        c = c[:-3]
    if c.endswith("/__init__"):
        c = c[: -len("/__init__")]
    return c.replace("/", ".")


def _paquet_de(chemin: str) -> str:
    """Le paquet qui CONTIENT ce fichier -- la base de resolution des imports relatifs.

    'src/hl_observer/funding/carry.py'    -> 'hl_observer.funding'
    'src/hl_observer/funding/__init__.py' -> 'hl_observer.funding'   (il EST le paquet)
    """
    est_init = chemin.replace("\\", "/").endswith("/__init__.py")
    module = _module_de(chemin)
    if est_init:
        return module
    return module.rsplit(".", 1)[0] if "." in module else ""


def _importes_par(source: str, chemin: str = "") -> set[str]:
    """Les modules qu'un fichier importe. Par l'AST, jamais par grep.

    Un grep sur `import x` rate `from a import (\\n  b,\\n  c)` et attrape les commentaires.
    L'AST ne se trompe pas : il lit ce que Python lit.

    LES IMPORTS RELATIFS -- LE BUG QUI RENDAIT CET AUDIT INUTILE (2026-07-12)
    ------------------------------------------------------------------------
    Ma 1re version faisait `if n.level: continue` : elle SAUTAIT `from ..config import x`.
    Resultat sur le vrai depot : **148 "orphelins"**, dont `hl_observer.config` -- un module
    evidemment utilise partout. Un rapport de 148 lignes dont la plupart sont fausses ne se
    lit plus : il rend le VRAI signal invisible.

    C'est exactement le peche que cet outil est cense denoncer : **un garde-fou qui ne garde
    rien.** Un audit qui ment est PIRE que pas d'audit -- il rassure.

    On resout donc les niveaux : `from .` = le paquet du fichier, `from ..` = son parent, etc.
    """
    out: set[str] = set()
    try:
        arbre = ast.parse(_sans_bom(source))
    except SyntaxError:
        return out

    base = _paquet_de(chemin) if chemin else ""

    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name)
        elif isinstance(n, ast.ImportFrom):
            if n.level:                            # import RELATIF
                morceaux = base.split(".") if base else []
                remontee = n.level - 1             # `from .` = 1 -> aucune remontee
                if remontee > len(morceaux):
                    continue                       # remontee impossible : on n'invente rien
                racine = ".".join(morceaux[: len(morceaux) - remontee]) if remontee else base
            else:
                racine = ""

            prefixe = ".".join(x for x in (racine, n.module or "") if x)
            if not prefixe:
                continue
            out.add(prefixe)
            for a in n.names:                      # `from p.q import r` peut viser le module p.q.r
                out.add("%s.%s" % (prefixe, a.name))
    return out


def graphe_des_imports(fichiers: dict[str, str]) -> dict[str, set[str]]:
    """module -> l'ensemble des FICHIERS qui l'importent. La question de T3, litteralement."""
    graphe: dict[str, set[str]] = {}
    for chemin, source in fichiers.items():
        for cible in _importes_par(source, chemin):
            graphe.setdefault(cible, set()).add(chemin)
    return graphe


def _est_un_test(chemin: str) -> bool:
    c = chemin.replace("\\", "/")
    return c.startswith("tests/") or "/tests/" in c or "/test_" in c or c.startswith("test_")


def _est_un_point_d_entree(module: str) -> bool:
    return module.rsplit(".", 1)[-1] in POINTS_D_ENTREE


def modules_atteignables(fichiers: dict[str, str], points_d_entree: Iterable[str]) -> set[str]:
    """Les modules VRAIMENT joignables depuis un point d'entree -- en suivant les imports
    TRANSITIVEMENT, pas sur un seul saut.

    LE BUG QUE CETTE FONCTION REPARE -- ET C'ETAIT UN BUG DE MON PROPRE AUDIT (2026-07-12)
    ------------------------------------------------------------------------------------
    Ma 1re version demandait seulement : « quelqu'un (hors tests) importe-t-il ce module ? »
    Elle declarait donc `perf.latency_tracker` **branche**... parce que
    `integration.scale_perf_runtime` l'importe. Or `scale_perf_runtime` est lui-meme MORT :
    personne ne l'appelle.

        latency_tracker  <--  scale_perf_runtime  <--  PERSONNE

    **Un module importe uniquement par un module mort est mort aussi.** Un seul saut ne suffit
    pas : il faut remonter jusqu'a un vrai point d'entree (`__main__`, `cli`, l'UI...).

    Consequence : le « 225 modules non branches » de ma 1re passe etait une **borne BASSE**.
    Un audit qui sous-estime rassure -- exactement le defaut qu'il est cense denoncer.
    """
    graphe_sortant: dict[str, set[str]] = {}
    for chemin, source in fichiers.items():
        if _est_un_test(chemin):
            continue
        graphe_sortant[_module_de(chemin)] = _importes_par(source, chemin)

    vus: set[str] = set()
    a_voir = [p for m in points_d_entree for p in _ancetres(m) if p in graphe_sortant]
    while a_voir:
        m = a_voir.pop()
        if m in vus:
            continue
        vus.add(m)
        for cible in graphe_sortant.get(m, set()):
            # LES PAQUETS ANCETRES SONT EXECUTES, EUX AUSSI -- 2e bug de mon audit (12/07).
            #
            # `from hl_observer.edge.edge_remaining import compute_edge_remaining` n'importe
            # pas QUE `edge_remaining` : Python execute d'abord `hl_observer/__init__.py`,
            # puis `hl_observer/edge/__init__.py`. Et ce dernier fait
            #     from hl_observer.edge.edge_calculator import compute_net_edge
            # -> `edge_calculator` EST charge au runtime.
            #
            # Ma 1re version transitive ne remontait pas aux ancetres. Elle declarait donc
            # MORTS `edge_calculator`, `exit_engine`, la moitie de `paper_trading/`... des
            # modules que l'interpreteur charge a chaque demarrage. J'allais publier ce
            # chiffre. CLAUDE.md m'a contredit -- et c'est CLAUDE.md qui avait raison.
            for p in _ancetres(cible):
                if p in graphe_sortant and p not in vus:
                    a_voir.append(p)
    return vus


def _ancetres(module: str) -> list[str]:
    """'a.b.c' -> ['a', 'a.b', 'a.b.c'] : tout ce que Python execute pour importer `a.b.c`."""
    bouts = module.split(".")
    return [".".join(bouts[: i + 1]) for i in range(len(bouts))]


# 🚩 CORRIGE LE 2026-07-12 (T3d) -- IL Y AVAIT UNE QUATRIEME PORTE, ET JE L'AVAIS RATEE.
#
# L'ancienne version disait, en toutes lettres : « Ce sont les TROIS seules portes »
# (`__main__`, `cli`, `ui.*`). C'etait FAUX.
#
# Le lanceur reel `tools/start_hypersmart_simulation.ps1` demarre AUSSI, en sous-processus,
# `tools/hypersmart_simulation_poll_loop.ps1`, qui contient :
#
#     $runnerArgs = "-u -m hl_observer.runtime.persistent_poll_runner --root ..."
#
# C'est un SECOND point d'entree de production, invisible a l'AST (il vit dans un .ps1) et
# absent de ma liste ecrite a la main. Tout ce que ce runner importe -- `detailed_logger`,
# `equity_history_store` -- etait donc declare MORT alors qu'il tourne a chaque session.
#
# Un point d'entree qu'on ECRIT A LA MAIN se perime le jour ou quelqu'un en ajoute un.
# On les DERIVE desormais des lanceurs eux-memes : `python -m hl_observer.X` dans un
# .ps1/.cmd/.sh EST une porte, par definition.
_PORTE_DANS_UN_LANCEUR = re.compile(r"-m\s+(hl_observer(?:\.[\w]+)*)")


def portes_declarees_par_les_lanceurs(lanceurs: dict[str, str], racine: str = "hl_observer") -> list[str]:
    """Les modules qu'un lanceur demarre par `python -m ...`. Ce sont de VRAIES portes."""
    out: set[str] = set()
    for _chemin, texte in (lanceurs or {}).items():
        for m in _PORTE_DANS_UN_LANCEUR.findall(texte or ""):
            if m.startswith(racine):
                out.add(m)
    return sorted(out)


# 🚩 #597 (2026-07-13) -- LA CINQUIEME PORTE, ET ELLE N'EST PAS EN `-m`.
#
# Le cliquet de cablage a rougi (304 > 303) apres l'ajout de trois modules de RECHERCHE
# (`regime_label`, `regime_wiring`, `audit.couverture`). Reflexe naturel : relever le plafond.
# C'est exactement ce qu'un cliquet interdit -- alors on est alle voir POURQUOI.
#
# Et en regardant la liste des "morts", on y trouve... **`hl_observer.backtesting.scenario_search`** :
# le moteur qui a evalue 150 000 000 de scenarios, lance des dizaines de fois, dont le resultat
# est cite dans MEMORY.md. Le declarer "mort" est un MENSONGE. Et il n'etait pas seul : les
# 61 modules de `backtesting/` sont dans le meme cas.
#
# La cause : les lanceurs ne demarrent pas la recherche par `python -m hl_observer.X`, mais par
#
#     python tools\h181_malediction_du_vainqueur.py
#     python tools\couverture_de_lignes.py
#     python tools\mesurer_carry_neutre.py
#
# Un script `tools/*.py` qu'un .cmd demarre EST une porte. Elle ne s'ecrit simplement pas en `-m`.
#
# ⚠️ ET CE N'EST PAS UNE FACON DE FAIRE TAIRE LE CLIQUET. La preuve : ce qui passe cette porte
# est range a part (`Verdict.outilles`), et pour les paquets du chemin de production (`risk/`,
# `paper_trading/`, `exits/`) il continue de compter comme MORT. Un garde-fou joignable
# uniquement depuis un script d'audit ne protege aucune position.
# 🔴 22/07 — ANGLE MORT CORRIGÉ. La regex exigeait que le chemin commence par `tools`/`scripts`,
# mais nos lanceurs .cmd utilisent l'idiome Windows `python "%~dp0tools\x.py"` (chemin relatif au
# script). Le préfixe `%~dp0` faisait rater le match -> `lanceur_tout_tester.py` (démarré par
# TOUT-TESTER.cmd) passait pour NON lancé, et tout ce qu'il importe pour MORT. On autorise donc un
# préfixe `%~dp0` ou `.\`/`./` avant le chemin capturé (la capture reste `tools\x.py`, propre).
_PYTHON_OUTIL_DANS_UN_LANCEUR = (
    r"""(?:python(?:\.exe)?|"%HYPERSMART_PYTHON%"|%HYPERSMART_PYTHON%)"""
)
_OUTIL_DANS_UN_LANCEUR = re.compile(
    _PYTHON_OUTIL_DANS_UN_LANCEUR
    + r"""\s+(?:-\S+\s+)*["\']?(?:%~dp0|\.[\\/])?"""
    + r"""((?:tools|scripts)[/\\][\w\-./\\]+\.py)""",
    re.IGNORECASE,
)


def outils_demarres_par_les_lanceurs(lanceurs: dict[str, str]) -> list[str]:
    """Les scripts `tools/*.py` qu'un .cmd/.ps1 lance VRAIMENT (`python tools\\x.py`).

    Un script que personne ne lance n'est PAS une porte : c'est un brouillon. On ne ressuscite
    donc pas tout `tools/` -- seulement ce qu'un humain peut reellement demarrer.
    """
    out: set[str] = set()
    for _chemin, texte in (lanceurs or {}).items():
        for m in _OUTIL_DANS_UN_LANCEUR.findall(texte or ""):
            out.add(m.replace("\\", "/"))
    return sorted(out)


def portes_ouvertes_par_les_outils(
    lanceurs: dict[str, str],
    outils: dict[str, str],
    *,
    racine: str = "hl_observer",
) -> list[str]:
    """Les modules `hl_observer.*` que les OUTILS reellement lances importent.

    On suit aussi les imports d'un outil vers un AUTRE outil (`from auditer_cablage import ...`),
    parce que `tools/` est mis sur le sys.path par ses propres scripts. Un seul niveau ne
    suffirait pas -- c'est la meme lecon que l'atteignabilite transitive.
    """
    outils = {c.replace("\\", "/"): s for c, s in (outils or {}).items()}
    # nom de module d'un script d'outil : 'tools/analysis/x.py' -> 'x' ET 'analysis.x'
    par_nom: dict[str, str] = {}
    for chemin in outils:
        stem = chemin.rsplit("/", 1)[-1][:-3]
        par_nom.setdefault(stem, chemin)
        court = chemin[len("tools/"):-3].replace("/", ".") if chemin.startswith("tools/") else ""
        if court:
            par_nom.setdefault(court, chemin)

    a_voir = [c for c in outils_demarres_par_les_lanceurs(lanceurs) if c in outils]
    vus: set[str] = set()
    modules: set[str] = set()
    while a_voir:
        chemin = a_voir.pop()
        if chemin in vus:
            continue
        vus.add(chemin)
        for cible in _importes_par(outils[chemin], chemin=""):
            if cible == racine or cible.startswith(racine + "."):
                modules.add(cible)
            elif cible in par_nom and par_nom[cible] not in vus:
                a_voir.append(par_nom[cible])
    return sorted(modules)


def _points_d_entree(
    fichiers: dict[str, str], racine: str, lanceurs: dict[str, str] | None = None
) -> list[str]:
    """Par ou le programme DEMARRE reellement. Tout le reste doit s'y raccrocher.

    Trois portes CONNUES (`python -m hl_observer ui` -> `__main__`, `cli`, le serveur `ui`)
    + **toutes celles que les LANCEURS declarent** par un `python -m hl_observer.X`.

    Ce qu'on NE seme PAS, volontairement : les `__init__.py`. Un paquet mort a un `__init__`
    comme les autres ; le semer ressusciterait tout son contenu. Un `__init__` LEGITIME devient
    atteignable tout seul, des que quelqu'un de vivant importe son paquet -- la transitivite
    s'en charge, sans qu'on ait a le decreter.
    """
    out = []
    for chemin in fichiers:
        if _est_un_test(chemin):
            continue
        m = _module_de(chemin)
        if not m.startswith(racine):
            continue
        if m.rsplit(".", 1)[-1] in ("__main__", "cli") or m.startswith(racine + ".ui"):
            out.append(m)

    # les portes ouvertes par les lanceurs (.ps1/.cmd/.sh) -- invisibles a l'AST
    connus = {_module_de(c) for c in fichiers}
    for m in portes_declarees_par_les_lanceurs(lanceurs or {}, racine):
        if m in connus and m not in out:
            out.append(m)
    return out


def _illisibles(fichiers: dict[str, str]) -> list[str]:
    """Les fichiers que l'AST ne peut PAS parser -- tronques par le mount, ou casses."""
    out = []
    for chemin, source in sorted(fichiers.items()):
        try:
            ast.parse(_sans_bom(source))
        except SyntaxError:
            out.append(chemin)
    return out


def auditer_les_modules(
    fichiers: dict[str, str],
    *,
    racine: str = "hl_observer",
    lanceurs: dict[str, str] | None = None,
    outils: dict[str, str] | None = None,
) -> Verdict:
    """Qui appelle qui ? Et surtout : qui n'est joignable depuis AUCUN point d'entree ?

    `fichiers` : {chemin relatif -> source}. Inclure les tests ET le code de production :
    c'est justement la DIFFERENCE entre les deux qui revele les modules "testes mais morts".

    `lanceurs` : {chemin -> source} des .ps1/.cmd/.sh. **A FOURNIR.** Un `python -m hl_observer.X`
    dans un lanceur est un POINT D'ENTREE que l'AST ne peut pas voir (T3d : le poller de
    simulation demarre ainsi, et tout ce qu'il importe passait pour mort).

    L'atteignabilite est TRANSITIVE (cf. `modules_atteignables`) : etre importe ne suffit pas,
    il faut etre importe par quelque chose qui est lui-meme joignable.
    """
    v = Verdict()
    v.illisibles = _illisibles(fichiers)
    graphe = graphe_des_imports(fichiers)
    vivants = modules_atteignables(fichiers, _points_d_entree(fichiers, racine, lanceurs))

    # la porte de la RECHERCHE : les `tools/*.py` qu'un .cmd/.ps1 demarre pour de vrai (#597)
    outilles: set[str] = set()
    if outils:
        graines = portes_ouvertes_par_les_outils(lanceurs or {}, outils, racine=racine)
        outilles = modules_atteignables(fichiers, graines) - vivants

    for chemin, _src in sorted(fichiers.items()):
        if _est_un_test(chemin):
            continue
        # un `__init__.py` EST le paquet : personne ne l'importe nommement, et ce n'est pas
        # du code mort. Le signaler noyait 40 lignes de bruit dans le rapport.
        if chemin.replace("\\", "/").endswith("/__init__.py"):
            continue
        module = _module_de(chemin)
        if not module.startswith(racine) or _est_un_point_d_entree(module):
            continue
        if module in vivants:
            continue                          # joignable depuis une vraie porte -> vivant
        if module in outilles:
            v.outilles.append(module)         # joignable depuis un OUTIL lance -> recherche
            continue

        importeurs = {i for i in graphe.get(module, set()) if _module_de(i) != module}
        if any(_est_un_test(i) for i in importeurs):
            v.testes_non_branches.append(module)
        else:
            v.orphelins.append(module)

    return v


# ----------------------------------------------------------------- les interrupteurs

def _defaut_de(noeud: ast.Call) -> str | None:
    """Le 2e argument de `os.environ.get("X", "0")` -- c'est LUI qui decide si c'est mort."""
    if len(noeud.args) >= 2 and isinstance(noeud.args[1], ast.Constant):
        val = noeud.args[1].value
        return str(val) if val is not None else None
    for kw in noeud.keywords:
        if kw.arg == "default" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return None


def flags_lus(fichiers: dict[str, str]) -> dict[str, tuple[str | None, set[str]]]:
    """FLAG -> (defaut lu dans le code, fichiers qui le lisent).

    On ne cherche QUE les lectures avec defaut explicite : sans defaut, on ne peut pas dire si
    la capacite est eteinte -- et on n'affirme jamais ce qu'on ne peut pas prouver.
    """
    out: dict[str, tuple[str | None, set[str]]] = {}
    for chemin, source in fichiers.items():
        if _est_un_test(chemin):
            continue                          # un test qui pose un flag ne l'ALLUME pas en prod
        try:
            arbre = ast.parse(_sans_bom(source))
        except SyntaxError:
            continue
        for n in ast.walk(arbre):
            if not isinstance(n, ast.Call):
                continue
            nom_fn = ""
            if isinstance(n.func, ast.Attribute):
                nom_fn = n.func.attr
            elif isinstance(n.func, ast.Name):
                nom_fn = n.func.id
            if nom_fn not in {"get", "getenv"}:
                continue
            # il faut que ce soit bien os.environ / os.getenv, pas un dict quelconque
            src_fn = ast.unparse(n.func) if hasattr(ast, "unparse") else nom_fn
            if "environ" not in src_fn and "getenv" not in src_fn:
                continue
            if not n.args or not isinstance(n.args[0], ast.Constant):
                continue
            flag = str(n.args[0].value)
            if not flag or not flag.isupper():
                continue
            defaut = _defaut_de(n)
            ancien = out.get(flag)
            fichiers_ = (ancien[1] if ancien else set()) | {chemin}
            # si DEUX lectures donnent deux defauts, on garde le plus PERMISSIF (allume) :
            # on ne veut pas crier "mort" alors qu'un autre chemin l'allume par defaut.
            if ancien and ancien[0] is not None and defaut is not None:
                allume = [d for d in (ancien[0], defaut)
                          if d.strip().lower() not in DEFAUTS_ETEINTS]
                defaut = allume[0] if allume else defaut
            elif ancien and defaut is None:
                defaut = ancien[0]
            out[flag] = (defaut, fichiers_)
    return out


# TOUTES les facons de poser un flag. En rater UNE, c'est accuser a tort.
_POSES = (
    # cmd :  set "X=1"      |  PowerShell :  $env:X = "1"      |  shell :  export X=1
    re.compile(r"""(?:^|\s)(?:set\s+"?|\$env:|export\s+)([A-Z][A-Z0-9_]{2,})\s*=""", re.MULTILINE),
    # PowerShell, l'autre syntaxe :  [Environment]::SetEnvironmentVariable("X", "1", "Process")
    re.compile(r"""SetEnvironmentVariable\s*\(\s*["']([A-Z][A-Z0-9_]{2,})["']""", re.IGNORECASE),
    # Python :  os.environ["X"] = "1"   |   os.environ.setdefault("X", "1")
    re.compile(r"""environ\s*\[\s*["']([A-Z][A-Z0-9_]{2,})["']\s*\]\s*="""),
    re.compile(r"""environ\.setdefault\s*\(\s*["']([A-Z][A-Z0-9_]{2,})["']"""),
)

# La declaration nue (`X: 1` ou `X=1` en debut de ligne) n'a de sens que dans un YAML ou un
# .env. Si on l'appliquait aux .cmd/.ps1, n'importe quel mot en majuscules suivi d'un ':'
# passerait pour un flag POSE -- et un faux "pose" CACHE un vrai interrupteur mort.
# Un faux negatif est ici pire qu'un faux positif : il rend l'audit aveugle.
_POSE_DECLARATIVE = re.compile(r"""^\s*([A-Z][A-Z0-9_]{2,})\s*[:=]\s*\S""", re.MULTILINE)
_EXT_DECLARATIVES = (".yaml", ".yml", ".env")


def flags_poses(lanceurs: dict[str, str]) -> dict[str, set[str]]:
    """FLAG -> les lanceurs (.cmd/.ps1/.yaml/.env) qui le POSENT.

    C'est ici que se joue tout le bug du poller L2 : le code lisait le flag avec un defaut a
    "0", et AUCUN lanceur ne le posait. La capacite etait la, cablee, testee... et eteinte
    pour toujours.

    MA PROPRE ERREUR, TROUVEE EN LANCANT L'OUTIL (2026-07-12)
    --------------------------------------------------------
    Ma 1re regex ne connaissait que `set "X="`, `$env:X=` et `export X=`. Or le VRAI lanceur du
    projet (`tools/start_hypersmart_simulation.ps1`) utilise l'autre syntaxe PowerShell :

        [Environment]::SetEnvironmentVariable("HYPERSMART_RECORD_MICROSTRUCTURE", "1", "Process")

    L'audit a donc declare MORTS **quatre flags parfaitement vivants** -- dont celui du
    recorder de microstructure et celui du fallback de mid, deux correctifs recents.

    **Un audit qui crie au loup detruit la confiance qu'on met en lui.** Il devient un bruit
    qu'on apprend a ignorer -- et le jour ou il a raison, plus personne ne l'ecoute. Rater une
    syntaxe de pose n'est pas un detail : c'est accuser a tort.
    """
    out: dict[str, set[str]] = {}
    for chemin, source in lanceurs.items():
        motifs = list(_POSES)
        if chemin.lower().endswith(_EXT_DECLARATIVES):
            motifs.append(_POSE_DECLARATIVE)
        for motif in motifs:
            for m in motif.finditer(source):
                out.setdefault(m.group(1), set()).add(chemin)
    return out


def auditer_les_interrupteurs(
    fichiers: dict[str, str], lanceurs: dict[str, str], *, prefixes: Iterable[str] = ()
) -> list[Interrupteur]:
    """Le verdict par flag. `prefixes` : ne garder que nos flags (ex. HYPERSMART_, V26_, HL_)."""
    lus = flags_lus(fichiers)
    poses = flags_poses(lanceurs)
    prefixes = tuple(prefixes)

    out: list[Interrupteur] = []
    for flag, (defaut, ou) in sorted(lus.items()):
        if prefixes and not flag.startswith(prefixes):
            continue
        out.append(Interrupteur(
            nom=flag, defaut=defaut,
            lu_par=tuple(sorted(ou)),
            pose_par=tuple(sorted(poses.get(flag, set()))),
        ))
    return out


__all__ = [
    "DEFAUTS_ETEINTS", "POINTS_D_ENTREE",
    "Interrupteur", "Verdict",
    "auditer_les_interrupteurs", "auditer_les_modules",
    "flags_lus", "flags_poses", "graphe_des_imports",
    "modules_atteignables",
    "outils_demarres_par_les_lanceurs", "portes_declarees_par_les_lanceurs",
    "portes_ouvertes_par_les_outils",
]
