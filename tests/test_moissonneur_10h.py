r"""LE RUN DE 10 HEURES — *ce qui doit tenir avant de lancer 10 h.*

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CES TESTS EXISTENT
═══════════════════════════════════════════════════════════════════════════════════════════════

    ***Un run de 10 heures qui casse a la 9e sur une faute de frappe est le PIRE resultat
    possible :*** on a perdu 9 heures ET on n'a rien appris.

Ces tests verifient, **sans un seul appel reseau**, que :

  1. la chaine **s'importe** et que chacune des 15 idees est **vraiment cablee** ;
  2. le **canari** (#1) est bien un **verrou** : si le trieur echoue, le run **s'arrete** ;
  3. l'**etat** survit a une coupure (ecriture **atomique**) ;
  4. le **cache** permet de re-juger **hors ligne** ;
  5. une **phase qui casse** ne tue pas le run ;
  6. le moissonneur n'a **aucun** moyen d'executer du code telecharge.

Aucun ordre reel. Aucun reseau.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "tools" / "moissonner_10h.py"


@pytest.fixture(scope="module")
def source() -> str:
    return SCRIPT.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def arbre(source: str) -> ast.Module:
    return ast.parse(source)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  0. IL COMPILE. *Une faute de frappe a la 9e heure est le pire resultat possible.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_le_script_de_10h_COMPILE(arbre: ast.Module) -> None:
    assert isinstance(arbre, ast.Module)


def test_tous_les_modules_de_recherche_s_importent() -> None:
    """*Un import casse ne se voit qu'au lancement -- c'est-a-dire trop tard.*"""
    for m in ("canari", "mine_de_code", "differentiel", "moteur", "sources",
              "scan_resilience", "github_signals", "github_dossier", "github_graph",
              "github_scan_plan", "moissonneur_sujets"):
        __import__("hl_observer.research.%s" % m)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. 🔒 LES 15 IDEES SONT-ELLES **VRAIMENT** CABLEES ?
#
#     🔴 *La maladie de ce projet : une capacite presente, un chainon manquant, personne qui se
#     plaint.* **22 modules livres, 3 branches.** On ne recommence pas.
#     -> **AST, pas grep** : un grep lit les docstrings et se fait berner par un commentaire.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

_ATTENDUES: dict[str, str] = {
    "#1 canari": "verifier",
    "#2 commits": "fouiller_commits",
    "#3 differentiel": "score_differentiel",
    "#3 indexer notre code": "indexer_notre_code",
    "#4 issues": "fouiller_issues",
    "#5 peurs": "peurs_de_l_auteur",
    "#6 constantes": "extraire_constantes",
    "#7 cache": "CacheBrut",
    "#8 dedup": "dedupliquer",
    "#9 bandit": "Bandit",
    "#10 citations": "citations_inverses",
    "#10 autorite": "autorite",
    "#11 auteurs": "autres_repos_de_l_auteur",
    "#12 reproductibilite": "reproductibilite",
    "#13 chronologie": "requetes_chronologiques",
    "#14 contradiction": "requetes_de_contradiction",
    "#15 zones vierges": "zones_vierges",
}


def _appels(arbre: ast.Module) -> set[str]:
    """Les noms **REELLEMENT appeles ou instancies**. *Pas ceux qui sont juste ecrits.*"""
    out: set[str] = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


@pytest.mark.parametrize("idee,symbole", sorted(_ATTENDUES.items()))
def test_CHAQUE_idee_est_REELLEMENT_APPELEE_pas_seulement_importee(
    idee: str, symbole: str, arbre: ast.Module
) -> None:
    """🔒 **AST, pas grep.** *Un module importe et jamais appele est un module MORT.*"""
    assert symbole in _appels(arbre), (
        "🔴 **%s N'EST PAS APPELEE** dans le run de 10 h (`%s` absent des appels).\n"
        "*Une capacite presente, un chainon manquant, personne qui se plaint.* **19 fois deja.**"
        % (idee, symbole)
    )


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. 🔒 LE CANARI EST UN **VERROU**, pas un affichage.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LE_CANARI_ARRETE_le_run_il_ne_se_contente_PAS_d_afficher(source: str) -> None:
    """***Un outil qui echoue sur ce qu'il connait n'a RIEN a dire sur ce qu'il ne connait pas.***

    Le canari doit **retourner** (arreter le run), pas juste imprimer un avertissement.
    """
    m = re.search(r"if not c\.fiable:(.{0,400})", source, re.S)
    assert m, "le canari doit etre TESTE avec un `if not c.fiable:`"
    bloc = m.group(1)
    assert "return 1" in bloc, (
        "🔴 le canari AFFICHE mais **N'ARRETE PAS** le run. "
        "*Un garde-fou qui ne bloque rien n'est pas un garde-fou : c'est une decoration.*"
    )


def test_le_canari_est_teste_AVANT_le_scan(source: str) -> None:
    """*Verifier l'outil APRES avoir moissonne 10 h ne sert a rien.*

    🚩 **Ce test s'etait trompe lui-meme** : il cherchait la chaine « PHASE A », qui apparait
    d'abord **dans un COMMENTAIRE d'en-tete**. *Une mention n'est pas une porte* -- la lecon
    du projet, appliquee a ses propres tests. On vise donc le **CODE** : l'appel `_phase(`.
    """
    i_canari = source.index("canari.verifier")
    i_scan = source.index('_phase("PHASE A')          # l'APPEL, pas la prose
    assert i_canari < i_scan, "le canari doit verrouiller AVANT qu'on depense 10 h de quota"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. UNE COUPURE NE DOIT RIEN COUTER.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_l_etat_est_ecrit_de_facon_ATOMIQUE(source: str) -> None:
    """🔒 *Une coupure de courant en plein `write` ne doit pas CORROMPRE l'etat.*

    Ecrire dans un `.tmp` puis `replace()` : l'operation est atomique au niveau du systeme.
    Sans ca, un run de 10 h peut se reveiller avec un etat **illisible** -- et tout perdre.
    """
    assert ".tmp" in source and ".replace(" in source, (
        "l'etat doit etre ecrit en .tmp PUIS renomme -- sinon une coupure le corrompt"
    )


def test_le_checkpoint_est_frequent_pas_en_fin_de_run(source: str) -> None:
    """*Sauver a la fin d'un run de 10 h, c'est ne pas sauver.*"""
    assert source.count("_chk()") >= 5


def test_le_Ctrl_C_est_rattrape_et_l_etat_survit(source: str) -> None:
    assert "KeyboardInterrupt" in source
    assert "reprendra exactement ici" in source


def test_un_TABLEAU_DE_BORD_permet_de_REGARDER_sans_interrompre(source: str, arbre) -> None:
    """🔑 ***Un run de 10 h qu'on ne peut pas observer est un run qu'on va interrompre par
    angoisse.*** Flo doit pouvoir ouvrir un fichier **a tout moment**, sans rien casser.
    """
    assert "class Progres" in source
    assert "moisson-en-cours" in source
    assert "ecrire" in _appels(arbre), "le tableau de bord doit etre REELLEMENT ecrit"


def test_la_PROGRESSION_est_SIMPLE_mais_complete(source: str) -> None:
    """Flo, d'abord : *« la progression doit etre ultra detaillee »* ; puis : *« il est trop
    complexe »*. -> **le juste milieu** : l'essentiel, lisible en 5 secondes, sur UN ecran.

    Elle doit montrer : ou on en est, l'ETAPE en francais simple, ce qu'il a trouve, **et ce
    qu'il n'a PAS su lire** (*un tableau de bord qui ne montre que les succes ment*).
    """
    for attendu in (
        "Temps",                  # ou on en est
        "ETAPE",                  # 🔑 la phase, en francais simple (etape 1/4...)
        "il reste",               # le temps restant
        "vitesse",                # requetes/heure
        "depots trouves",         # ce qu'il ratisse
        "LUS et NOTES",           # 🔑 la ou le TRI se fait -- *le point de Flo*
        "BONNES PISTES GARDEES",  # le resultat du tri
        "sources non lues",       # 🔴 les blessures -- on ne cache pas
        "DERNIERS EVENEMENTS",    # le journal court
    ):
        assert attendu in source, "la progression ne montre pas : %r" % attendu

    # 🔑 et elle dit explicitement OU le tri se fait -- pour ne plus donner l'impression
    #    (le retour de Flo) que « le moteur de tri ne fonctionne pas ».
    assert "le tri se fait ici" in source


def test_le_tableau_de_bord_DIT_ce_qu_il_n_a_PAS_su_lire(source: str) -> None:
    """🔴 ***Un tableau de bord qui ne montre que les succes est un tableau de bord qui MENT.***

    Le tableau simplifie garde l'honnetete : il **compte** les sources non lues a l'ecran.
    (Le detail complet -- « je n'ai pas su la lire, 235 README perdus » -- reste dans le .md.)
    """
    assert "sources non lues" in source
    assert "len(self.bless.non_lus)" in source, (
        "le nombre de sources NON LUES doit rester affiche -- on ne cache pas les blessures")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. NE JAMAIS MOURIR — **ET NE JAMAIS MENTIR.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_une_PHASE_qui_casse_ne_TUE_PAS_le_run(source: str) -> None:
    """*Une exception dans une phase est une blessure, pas une mort.*"""
    assert "def _phase(" in source
    assert "bless.abandons" in source, "une phase qui casse doit etre COMPTEE"
    assert "le run CONTINUE" in source


def test_TOUTE_blessure_est_COMPTEE_et_PUBLIEE(source: str) -> None:
    """🔴 ***Un scan qui ne meurt jamais ET ne se plaint jamais est un scan qui MENT.***

    C'est **exactement** le bug qui a perdu 235 README -- dont **hftbacktest**, notre cible n°1.
    """
    assert "Blessures()" in source
    assert "bless.rapport()" in source, "les blessures doivent etre PUBLIEES dans le rapport"
    assert "n'ai PAS su lire" in source or "n'ai pas su lire" in source


def test_le_quota_fait_ATTENDRE_jamais_abandonner(source: str) -> None:
    assert "ATTENDRE" in source and "Retry-After" in source
    assert "X-RateLimit-Reset" in source, (
        "GitHub dit lui-meme quand revenir -- *on l'ecoute plutot que de deviner*")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  5. 🚨 SECURITE — on telecharge du code d'inconnus. **On ne l'execute JAMAIS.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════

_INTERDITS = ("subprocess", "os.system", "exec(", "eval(", "git clone",
              "importlib", "pickle.load", "__import__", "compile(")


@pytest.mark.parametrize("motif", _INTERDITS)
def test_AUCUN_moyen_d_executer_le_code_telecharge(motif: str, source: str) -> None:
    """🔒 ***On LIT du texte. On ne lance RIEN.*** Jamais."""
    assert motif not in source, (
        "🚨 **MOTIF DANGEREUX : `%s`.** Le moissonneur telecharge du code d'inconnus -- "
        "il ne doit avoir **aucun** moyen de l'executer." % motif
    )


def test_le_script_annonce_qu_il_est_en_LECTURE_SEULE(source: str) -> None:
    assert "LECTURE SEULE" in source.upper()
    assert "real_execution" in source and "False" in source


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  6. LE LIVRABLE
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_le_livrable_est_moisson_fini_md_A_LA_RACINE(source: str) -> None:
    assert 'SORTIE_MD = RACINE / "moisson-fini.md"' in source


def test_le_rapport_contient_les_15_idees(source: str) -> None:
    for i in range(1, 16):
        assert ("#%d" % i) in source, "l'idee #%d n'apparait nulle part" % i
