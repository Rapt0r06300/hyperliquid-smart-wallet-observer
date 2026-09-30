r"""LE DOSSIER ET LE GRAPHE — *ce qu'on garde, POURQUOI, OU on le branche, et ce qu'on ignore.*

Flo : *« un .md qui detaille enormement tout ce que le moissonneur aura trouve et trie »*
      *« pourquoi on a garde ceci, pourquoi ca nous est benefique, comment l'installer et le
        BRANCHER correctement »*
      *« le cmd doit connaitre l'architecture de notre bot »*

Ces tests verrouillent les 4 choses qui rendent le dossier utile plutot que joli :

  1. **LA LICENCE** — 49 %% des repos n'en ont AUCUNE. Pas de licence = tous droits reserves.
     *Un dossier qui dit « copiez ca » sans regarder la licence est un piege juridique.*
  2. **LE VERDICT** — la classification que CLAUDE.md impose (COPY_ADAPTED, INSPIRE_ONLY...).
  3. **OU CA SE BRANCHE** — *une idee sans point d'ancrage n'est pas une idee : c'est une
     distraction.*
  4. **CE QU'ON NE PEUT PAS PROUVER** — *un dossier qui n'a que des certitudes est un dossier
     qui ment.*

Aucun ordre reel. Lecture seule.
"""
from __future__ import annotations

import pytest

from hl_observer.research.github_dossier import (
    NOS_TROUS,
    OU_CA_SE_BRANCHE,
    classer,
    dossier_md,
    installation,
    plan_d_action,
    statut_licence,
)
from hl_observer.research.github_graph import (
    citations,
    dependances,
    est_une_liste,
    liens_de_repos,
    papiers,
    requetes_ciblees,
)

_SIG_UTILE = {
    "formules": {"kappa_intensite_de_fill": ["lambda(delta) = A * exp(-kappa * delta)"]},
    "aveux_de_limite": ["not a substitute for real L3 data"],
    "chiffres_verifiables": ["-7.97 bps"],
    "promesses_creuses": [],
}
_SIG_MENTEUR = {
    "formules": {"kappa_intensite_de_fill": ["kappa ="]},
    "aveux_de_limite": [],
    "chiffres_verifiables": [],
    "promesses_creuses": ["guaranteed profit"],
}
_SIG_HORS_SUJET = {"formules": {}, "aveux_de_limite": [], "chiffres_verifiables": [],
                   "promesses_creuses": []}


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. LA LICENCE — *deny-by-default. 49 % des repos n'en ont AUCUNE.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("lic,attendu", [
    ("MIT", "PERMISSIVE"), ("Apache-2.0", "PERMISSIVE"), ("BSD-3-Clause", "PERMISSIVE"),
    ("GPL-3.0", "COPYLEFT"), ("AGPL-3.0", "COPYLEFT"),
    (None, "AUCUNE"), ("", "AUCUNE"), ("NOASSERTION", "AUCUNE"),
    ("Sacred-Banana-License", "INCONNUE"),
])
def test_la_licence_est_lue_et_une_licence_inconnue_est_INTOUCHABLE(lic, attendu) -> None:
    """*Dans le doute, on n'a PAS le droit. Deny-by-default.*"""
    assert statut_licence(lic)[0] == attendu


def test_SANS_licence_on_ne_copie_JAMAIS_meme_si_le_repo_est_parfait() -> None:
    """🔴 **Pas de licence = tous droits reserves.** Ce n'est pas negociable."""
    f = classer("o/r", licence=None, signaux=_SIG_UTILE, n_lignes_de_code=20)
    assert f.verdict == "INSPIRE_ONLY"
    assert "copie" in f.pourquoi.lower()


def test_le_COPYLEFT_contaminerait_notre_code_donc_INSPIRE_ONLY() -> None:
    f = classer("o/r", licence="GPL-3.0", signaux=_SIG_UTILE, n_lignes_de_code=20)
    assert f.verdict == "INSPIRE_ONLY"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. LE VERDICT
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_un_repo_qui_PROMET_sans_jamais_DOUTER_est_ECARTE() -> None:
    """*Dans un corpus ou tout le monde promet de l'alpha, l'absence d'aveu est l'alarme.*"""
    f = classer("o/r", licence="MIT", signaux=_SIG_MENTEUR, n_lignes_de_code=50)
    assert f.verdict == "SKIP_WITH_REASON"
    assert "promet" in f.pourquoi.lower()


def test_un_repo_qui_ne_comble_AUCUN_trou_de_NOTRE_bot_est_ECARTE() -> None:
    """***Interessant n'est pas utile.*** Le seul critere : est-ce que ca repare quelque chose ?"""
    f = classer("o/r", licence="MIT", signaux=_SIG_HORS_SUJET, n_lignes_de_code=999)
    assert f.verdict == "SKIP_WITH_REASON"


def test_permissive_plus_code_lu_plus_un_trou_comble_donne_PORT_BEHAVIOR() -> None:
    f = classer("o/r", licence="MIT", signaux=_SIG_UTILE, n_lignes_de_code=12)
    assert f.verdict == "PORT_BEHAVIOR"
    assert "test" in f.pourquoi.lower(), "porter un comportement SANS test, ce n'est pas porter"
    assert "kappa_intensite_de_fill" in f.trous_combles


def test_si_on_n_a_PAS_LU_son_code_le_verdict_est_DIFFERE_pas_positif() -> None:
    """*Le README seul ne suffit pas a juger. Le README est la page de vente.*"""
    f = classer("o/r", licence="MIT", signaux=_SIG_UTILE, n_lignes_de_code=0)
    assert f.verdict == "DEFERRED_WITH_PLAN"
    assert any("code" in r.lower() for r in f.reserves)


def test_un_AVEU_devient_une_RESERVE_car_on_en_HERITE() -> None:
    """L'aveu rend le repo credible **et** nous previent d'une limite qu'on va reprendre."""
    f = classer("o/r", licence="MIT", signaux=_SIG_UTILE, n_lignes_de_code=12)
    assert any("avoue" in r.lower() for r in f.reserves)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. 🔌 OU CA SE BRANCHE — *une idee sans point d'ancrage est une distraction.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_CHAQUE_trou_connu_a_un_point_de_BRANCHEMENT_et_un_TEST() -> None:
    """🔒 Regle CLAUDE.md : **pas de module isole sans test ET plan de cablage.**"""
    for trou in NOS_TROUS:
        assert trou in OU_CA_SE_BRANCHE, (
            "le trou '%s' n'a AUCUN point de branchement -> c'est une distraction" % trou)
        cible, comment, test = OU_CA_SE_BRANCHE[trou]
        assert cible and comment and test, "un branchement sans test n'est pas un branchement"


def test_le_branchement_pointe_sur_des_modules_qui_EXISTENT_vraiment() -> None:
    """*Un plan de cablage qui cite un fichier inexistant est une fiction.*"""
    import pathlib
    racine = pathlib.Path(__file__).resolve().parents[1]
    for trou, (cible, _, _) in OU_CA_SE_BRANCHE.items():
        for m in __import__("re").finditer(r"`(src/hl_observer/[\w/]+\.py)`", cible):
            chemin = racine / m.group(1)
            assert chemin.exists(), (
                "le plan de cablage de '%s' cite `%s` -- **qui n'existe pas**" % (trou, m.group(1)))


def test_le_MM_ne_doit_PAS_etre_rebranche_il_est_MORT() -> None:
    """🔒 T1b : 0/29 a **100 %% de fill**. HLP, le MM **paye**, rend **-0,01 %%**.

    *On ne branche pas une strategie morte.* Le garde-fou est dans le plan lui-meme.
    """
    _, comment, test = OU_CA_SE_BRANCHE["gueant_lehalle_glft"]
    assert "morte" in test.lower() or "aucun" in test.lower()
    assert "ferm" in comment.lower() or "mort" in comment.lower()


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. L'INSTALLATION — *deduite de l'arbre. Si on ne sait pas, ON LE DIT.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("arbre,gest", [
    (["pyproject.toml", "src/a.py"], "pip"),
    (["Cargo.toml", "src/main.rs"], "cargo"),
    (["package.json", "index.ts"], "npm"),
    (["go.mod"], "go"),
    (["requirements.txt"], "pip"),
])
def test_l_installation_est_DEDUITE_de_l_arbre(arbre, gest) -> None:
    assert installation(arbre).gestionnaire == gest


def test_sans_manifeste_on_DIT_qu_on_ne_sait_pas_on_n_invente_PAS_de_commande() -> None:
    """*Je ne devine pas une commande d'installation : je dis que je ne sais pas.*"""
    i = installation(["README.md", "notes.txt"])
    assert i.gestionnaire == "INCONNU"
    assert i.commande == "—"
    assert "ne devine pas" in i.note or "Aucun manifeste" in i.note


def test_le_point_d_entree_est_trouve() -> None:
    assert installation(["src/main.py", "pyproject.toml"]).point_d_entree == "src/main.py"


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  5. LE MARKDOWN — *le livrable.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def _entree(verdict: str = "PORT_BEHAVIOR") -> dict:
    f = classer("nkaz001/hftbacktest", licence="MIT", signaux=_SIG_UTILE, n_lignes_de_code=12)
    return {
        "repo": "nkaz001/hftbacktest", "score": 88.0, "etoiles": 4270, "licence": "MIT",
        "verdict": verdict, "pourquoi": f.pourquoi, "trous_combles": f.trous_combles,
        "reserves": f.reserves, "signaux": _SIG_UTILE,
        "installation": installation(["pyproject.toml", "src/main.py"]).as_dict(),
        "lectures": [{"fichier": "hftbacktest/queue.py", "ligne": 42,
                      "code": "chg -= cum_trade_qty", "pourquoi": "FORMULE position_dans_la_file"}],
    }


def test_le_md_explique_POURQUOI_COMMENT_INSTALLER_et_OU_BRANCHER() -> None:
    """Les 4 demandes de Flo, dans un seul fichier."""
    md = dossier_md([_entree()])
    assert "Pourquoi on le garde" in md
    assert "Le trou de NOTRE bot qu'il comble" in md
    assert "Comment l'installer" in md
    assert "Comment le brancher dans NOTRE bot" in md
    assert "pip install -e ." in md
    assert "test obligatoire" in md


def test_le_md_dit_TOUJOURS_ce_qu_il_ne_peut_PAS_prouver() -> None:
    """***Un dossier qui n'a que des certitudes est un dossier qui ment.***"""
    md = dossier_md([_entree()])
    assert "Ce que je ne peux **pas** prouver" in md
    assert "Qu'il gagne de l'argent" in md
    assert "jamais **exécuté**" in md


def test_le_md_rappelle_que_RIEN_ne_bypasse_le_noyau() -> None:
    md = dossier_md([_entree()])
    assert "noyau" in md.lower()
    assert "PaperIntent" in md or "NO_TRADE" in md


def test_le_md_donne_le_MOTIF_de_chaque_REJET() -> None:
    """*Un rejet sans motif est un rejet qu'on ne peut pas contester -- donc pas corriger.*"""
    rejet = {"repo": "x/y", "verdict": "SKIP_WITH_REASON", "score": 0,
             "pourquoi": "il promet sans jamais douter", "signaux": _SIG_MENTEUR}
    md = dossier_md([_entree(), rejet])
    assert "LES ÉCARTÉS" in md
    assert "il promet sans jamais douter" in md


def test_un_corpus_VIDE_donne_un_etat_vide_HONNETE_pas_une_liste_bidon() -> None:
    md = dossier_md([])
    assert "Aucun repo retenu" in md
    assert "pas une panne" in md


def test_le_md_lie_chaque_ligne_a_lire_vers_le_VRAI_fichier() -> None:
    md = dossier_md([_entree()])
    assert "github.com/nkaz001/hftbacktest/blob/HEAD/hftbacktest/queue.py#L42" in md


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  5 bis. 📋 LE PLAN D'ACTION — *chaque tache porte son POURQUOI et son APPORT.*
#
#  Flo : « toutes les taches ultra detaillees, pourquoi on le fait, ce que ca nous apporte,
#          aucune tache laissee de cote, aucun detail oublie »
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_CHAQUE_tache_porte_son_POURQUOI_son_APPORT_et_son_CRITERE() -> None:
    """***Une tache sans critere n'est pas une tache : c'est un souhait.***
    ***Une tache sans « pourquoi » sera abandonnee a la premiere difficulte.***
    """
    taches = plan_d_action("o/r", "PORT_BEHAVIOR", ["kappa_intensite_de_fill"],
                           [{"fichier": "a.py", "ligne": 1, "code": "x", "pourquoi": "FORMULE"}])
    assert taches, "un repo retenu DOIT avoir un plan"
    for t in taches:
        assert t.id, "une tache sans ID peut se perdre"
        assert len(t.pourquoi) > 30, "un « pourquoi » vide sera abandonne : %s" % t.titre
        assert len(t.apport) > 15, "une tache sans apport ne merite pas d'exister : %s" % t.titre
        assert len(t.critere) > 20, "une tache sans critere est un souhait : %s" % t.titre


def test_le_plan_impose_LIRE_avant_de_PORTER() -> None:
    """*Trier ne remplacera jamais lire.* L'ordre n'est pas decoratif."""
    t = plan_d_action("o/r", "PORT_BEHAVIOR", ["kappa_intensite_de_fill"], [])
    titres = [x.titre for x in t]
    i_lire = next(i for i, x in enumerate(titres) if "LIRE" in x)
    i_porter = next(i for i, x in enumerate(titres) if "Porter" in x)
    assert i_lire < i_porter, "on ne porte pas ce qu'on n'a pas lu"


def test_le_plan_contient_TOUJOURS_le_BRANCHEMENT_et_la_MESURE() -> None:
    """🔴 *22 modules livres, 3 branches.* **Un module non branche est un module MORT.**"""
    t = plan_d_action("o/r", "PORT_BEHAVIOR", ["kappa_intensite_de_fill"], [])
    joint = " ".join(x.titre for x in t)
    assert "BRANCHER" in joint, "sans branchement, le module est mort-ne"
    assert "MESURER" in joint, "une idee non mesuree chez nous ne vaut rien"


def test_un_INSPIRE_ONLY_interdit_EXPLICITEMENT_la_copie() -> None:
    t = plan_d_action("o/r", "INSPIRE_ONLY", ["kappa_intensite_de_fill"], [])
    joint = " ".join(x.titre + x.critere for x in t)
    assert "AUCUNE LIGNE" in joint or "aucun bloc" in joint.lower()


def test_un_repo_ECARTE_n_a_AUCUNE_tache() -> None:
    """*On ne fait pas travailler quelqu'un sur ce qu'on a decide d'ecarter.*"""
    assert plan_d_action("o/r", "SKIP_WITH_REASON", [], []) == []


def test_LA_CHECKLIST_reprend_TOUTES_les_taches_aucune_ne_peut_se_perdre() -> None:
    """🔒 **LE TEST QUI GARANTIT « aucune tache laissee de cote ».**

    La checklist est **generee depuis le meme registre** que les fiches.
    *Une liste tenue a la main finit toujours par diverger.*
    """
    md = dossier_md([_entree()])
    attendues = plan_d_action("nkaz001/hftbacktest", "PORT_BEHAVIOR",
                              ["kappa_intensite_de_fill"],
                              [{"fichier": "hftbacktest/queue.py", "ligne": 42,
                                "code": "chg -= cum_trade_qty", "pourquoi": "FORMULE"}],
                              prefixe="T1")
    assert "LA CHECKLIST" in md
    for t in attendues:
        assert "`%s`" % t.id in md, (
            "la tache %s (%s) N'APPARAIT PAS dans la checklist -- **elle peut se perdre**"
            % (t.id, t.titre))
    assert "- [ ]" in md, "une checklist sans case a cocher n'est pas une checklist"


def test_la_checklist_annonce_le_NOMBRE_de_taches() -> None:
    md = dossier_md([_entree()])
    assert "Aucune optionnelle" in md


def test_le_md_BRIEFE_l_agent_sur_les_regles_dures_et_la_MALADIE() -> None:
    """*Un agent qui arrive froid reproduira la maladie s'il ne la connait pas.*"""
    md = dossier_md([_entree()])
    assert "ordre de mission" in md
    assert "capacité présente, un chaînon manquant" in md      # la maladie
    assert "ÉCHEC BLOQUANT" in md                              # pas de module sans test
    assert "−7,97 bps" in md or "-7,97 bps" in md              # le copy-trading mort
    assert "HLP" in md                                         # le benchmark qui juge tout


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  6. 🌐 CHERCHER PARTOUT — *ne pas interroger un index : SUIVRE LE FIL.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

AWESOME = """
# Awesome Quant
- [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) - HFT backtesting
- [mementum/backtrader](https://github.com/mementum/backtrader.git)
- [quantopian/zipline](https://github.com/quantopian/zipline#readme)
See also https://github.com/features/copilot and https://github.com/topics/trading
"""


def test_LE_TROU_le_plus_cher_une_awesome_list_est_une_CARTE_AU_TRESOR() -> None:
    """🔴 *Un `awesome-quant` contient 200 repos SANS TOPIC. On en avait trouve une...

    ...et on ne l'a JAMAIS suivie.* La recherche par topic ne les verra jamais.
    """
    r = liens_de_repos(AWESOME)
    assert "nkaz001/hftbacktest" in r
    assert "mementum/backtrader" in r, "le suffixe .git doit etre retire"
    assert "quantopian/zipline" in r, "l'ancre #readme doit etre retiree"


def test_on_n_avale_PAS_les_pages_GitHub_qui_ne_sont_pas_des_repos() -> None:
    r = liens_de_repos(AWESOME)
    assert not any(x.startswith(("features/", "topics/")) for x in r)


def test_une_awesome_list_est_RECONNUE_comme_telle() -> None:
    assert est_une_liste("someone/awesome-quant", "# Awesome Quant")
    assert not est_une_liste("o/normal-bot", "# A trading bot\nJust a bot.")


def test_les_papiers_cites_sont_recuperes() -> None:
    """*Le code est une implementation ; le papier est le RAISONNEMENT.*"""
    p = papiers("See arxiv.org/abs/1105.3115 and doi 10.1080/14697688.2011.1234")
    assert any("1105.3115" in x for x in p)
    assert any("doi.org" in x for x in p)


def test_une_SOURCE_CITEE_est_une_source_deja_validee_par_quelqu_un() -> None:
    c = citations("This is a port of https://github.com/nkaz001/hftbacktest for Python")
    assert "nkaz001/hftbacktest" in c


@pytest.mark.parametrize("fichier,contenu,attendu", [
    ("requirements.txt", "numpy==1.2\nhftbacktest>=2.0\n# comment\npandas", "hftbacktest"),
    ("package.json", '{"dependencies": {"ccxt": "^4", "lodash": "^4"}}', "ccxt"),
])
def test_les_DEPENDANCES_sont_une_recommandation_d_expert_gratuite(fichier, contenu, attendu):
    """***Le requirements.txt d'un bon repo est une liste de courses validee par quelqu'un.***"""
    d = dependances(fichier, contenu)
    assert attendu in d
    assert "numpy" not in d and "pandas" not in d, "les banales ne sont pas des decouvertes"


def test_un_manifeste_ILLISIBLE_ne_donne_RIEN_jamais_une_devinette() -> None:
    assert dependances("package.json", "{ pas du json") == []


def test_les_requetes_viennent_de_NOS_TROUS_pas_de_mots_a_la_mode() -> None:
    """*On ne cherche pas « trading bot ». On cherche ce qui MANQUE A NOTRE BOT.*"""
    rs = requetes_ciblees()
    assert len(rs) >= 12
    for r in rs:
        assert r["requete"] and r["pourquoi"], "une requete sans motif est une requete au hasard"
    joint = " ".join(r["pourquoi"] for r in rs)
    assert "-7,97" in joint or "7,97" in joint      # le copy-trading mort
    assert "carry" in joint.lower()                 # la seule piste positive
    assert "liquid" in joint.lower()                # la derniere piste non mesuree
