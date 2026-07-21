r"""LES 17 SOURCES ET LE MOTEUR D'IDEES.

═══════════════════════════════════════════════════════════════════════════════════════════════
🔒 LE TEST LE PLUS IMPORTANT DE CE FICHIER
═══════════════════════════════════════════════════════════════════════════════════════════════

Flo a demande d'ecrire dans le .md : *« Claude a deja accepte ces idees, c'est son script. »*

    ✅ **VRAI** : **le FILTRE est de moi.** Ce qui est retenu a passe MON jugement de tri.
                  ***On ne re-debat pas du tri.***

    🔴 **FAUX** : « l'IDEE est acceptee ». **Le filtre dit « ca vaut vingt minutes de lecture ».**
                  Il ne dit **PAS** « ca marche ».

    ***Si le .md disait « Claude a valide ces idees », un agent futur les implementerait SANS
    LES MESURER. C'est exactement comme ca que ce projet s'est fait mal.***

-> `test_le_bloc_de_pre_approbation_NE_DIT_PAS_que_les_idees_MARCHENT` verrouille ca.

Aucun reseau. Aucun ordre reel.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.research.idee import (
    CATALOGUE as IDEES,
    PRE_APPROBATION,
    extraire_idees,
    reconnaitre,
)
from hl_observer.research.sources_plus import (
    CATALOGUE as SOURCES,
    INACCESSIBLES,
    parser,
    rapport,
    url,
)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. 🔒 LA PRE-APPROBATION — *ce que j'ai accepte, et ce que je REFUSE d'ecrire.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_le_bloc_de_pre_approbation_DIT_que_le_FILTRE_est_de_Claude() -> None:
    """✅ **C'est vrai, et je l'assume.** *Le tri n'est pas a re-debattre.*"""
    assert "FILTRE EST DE MOI" in PRE_APPROBATION
    assert "n'est pas à re-débattre" in PRE_APPROBATION
    assert "canari" in PRE_APPROBATION.lower(), (
        "le canari a PROUVE le trieur avant le run -- c'est ce qui fonde la pre-approbation")


def test_le_bloc_de_pre_approbation_NE_DIT_PAS_que_les_idees_MARCHENT() -> None:
    """🔒 **LE TEST QUI COMPTE.**

    ***Si le .md disait « Claude a valide ces idees », un agent futur les implementerait SANS
    LES MESURER.*** C'est exactement comme ca que ce projet s'est fait mal.
    """
    assert "PAS** ACCEPTÉ" in PRE_APPROBATION or "PAS ACCEPTÉ" in PRE_APPROBATION
    assert "Que ces idées MARCHENT" in PRE_APPROBATION
    assert "MESURÉE CHEZ NOUS" in PRE_APPROBATION
    assert "HLP" in PRE_APPROBATION, "le benchmark qui juge tout doit etre rappele"
    assert "600" in PRE_APPROBATION and "UNE survivante" in PRE_APPROBATION, (
        "le taux de base est ECRASANT et doit etre rappele : ~600 idees, 1 survivante")

    # 🔴 aucune formule qui autoriserait a implementer sans mesurer
    interdits = ("idées validées", "idées approuvées", "idées acceptées par Claude",
                 "tu peux implémenter directement", "pas besoin de mesurer")
    bas = PRE_APPROBATION.lower()
    for x in interdits:
        assert x.lower() not in bas, "🔴 formulation DANGEREUSE : %r" % x


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. LES FICHES D'IDEES — quoi · POURQUOI · COMMENT · ce qui la REFUTERAIT.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("m", IDEES, ids=lambda m: m.cle)
def test_CHAQUE_idee_dit_QUOI_POURQUOI_COMMENT_et_le_TEST(m) -> None:
    """Flo : *« il doit expliquer pour chaque idee comment l'implementer et surtout pourquoi »*."""
    assert len(m.quoi) > 25, "une idee sans « quoi » n'est pas une idee"
    assert len(m.pourquoi) > 40, "un « pourquoi » vide sera abandonne a la 1re difficulte"
    assert m.ou, "*une idee sans point d'ancrage est une distraction*"
    assert len(m.comment) > 25, "sans « comment », c'est un voeu"
    assert m.test, "🔒 **pas de module sans test** -- regle CLAUDE.md, ECHEC BLOQUANT"
    assert m.branchement, "*un module non branche est un module MORT*"
    assert m.cout


@pytest.mark.parametrize("m", IDEES, ids=lambda m: m.cle)
def test_CHAQUE_idee_dit_CE_QUI_LA_REFUTERAIT(m) -> None:
    """🔑 ***Une idee qu'aucun resultat ne pourrait tuer n'est pas une idee : c'est une croyance.***"""
    assert len(m.refutation) > 40, "idee non falsifiable : %s" % m.cle


def test_l_idee_du_MARKET_MAKING_dit_de_NE_PAS_l_implementer() -> None:
    """🔒 *Le MM est FERME : T1b 0/29 a 100 %% de fill, et HLP -- le MM PAYE -- rend -0,01 %%.*

    ***On ne branche pas une strategie morte.*** Meme si le corpus en est plein.
    """
    m = next(x for x in IDEES if x.cle == "inventaire")
    assert "INSPIRE_ONLY" in m.ou or "nulle part" in m.ou
    assert "Ne PAS l'implémenter" in m.comment
    assert "0/29" in m.comment or "HLP" in m.comment
    assert m.branchement.lower().startswith("aucun")


def test_l_idee_du_QUEUE_MODEL_porte_l_argument_de_DOMINATION() -> None:
    """🔑 *T1b a mesure a 100 %% de fill (la borne HAUTE). Un vrai modele ne peut qu'ABAISSER.*

    ***Si ton modele rend le MM rentable, c'est le MODELE qui est faux.***
    """
    m = next(x for x in IDEES if x.cle == "queue_position")
    assert "0/29" in m.refutation
    assert "FAUX" in m.refutation


def test_l_idee_du_LOOKAHEAD_est_la_PLUS_RENTABLE_et_le_dit() -> None:
    """*Notre coupe train/test FUYAIT : 68 %% de fuite. Le test etait deja dans le train.*"""
    m = next(x for x in IDEES if x.cle == "lookahead")
    assert "68" in m.pourquoi
    assert "premier" in m.branchement.lower() or "rapport qualité/prix" in m.cout


def test_le_carry_est_signale_comme_NOTRE_SEULE_piste_positive() -> None:
    m = next(x for x in IDEES if x.cle == "carry")
    assert "SEULE" in m.pourquoi.upper()
    assert "7,09" in m.pourquoi or "7.09" in m.pourquoi


def test_reconnaitre_relie_un_TEXTE_a_des_idees_ACTIONNABLES() -> None:
    r = reconnaitre("We fit lambda(delta) = A exp(-kappa delta) and measure markout at +10s. "
                    "Purged cross-validation with embargo.")
    assert "kappa_fill" in r
    assert "adverse" in r
    assert "lookahead" in r


def test_extraire_idees_REGROUPE_le_corpus_en_fiches() -> None:
    """*Cent papiers sur le meme sujet ne font pas cent idees : ils font UNE idee, bien etayee.*"""
    corpus = [
        {"titre": "Fill intensity A exp(-kappa d)", "texte": "kappa estimation",
         "lien": "u1", "source": "arxiv"},
        {"titre": "Another kappa paper", "texte": "fill probability model",
         "lien": "u2", "source": "openalex"},
        {"titre": "Purged CV", "texte": "embargo lookahead", "lien": "u3", "source": "arxiv"},
    ]
    idees = extraire_idees(corpus)
    cles = {i.cle for i in idees}
    assert "kappa_fill" in cles and "lookahead" in cles
    k = next(i for i in idees if i.cle == "kappa_fill")
    assert len(k.sources) == 2, "2 papiers sur kappa = **UNE** idee, avec **2 sources**"
    assert idees[0].cle == "kappa_fill", "l'idee la mieux etayee passe en premier"


def test_le_md_d_une_idee_contient_le_COMMENT_et_la_REFUTATION() -> None:
    i = extraire_idees([{"titre": "kappa", "texte": "kappa fill intensity",
                         "lien": "u", "source": "arxiv"}])[0]
    md = "\n".join(i.md())
    assert "Comment" in md and "Test (obligatoire)" in md
    assert "Ce qui la RÉFUTERAIT" in md
    assert "croyance" in md


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. LES 17 SOURCES.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_il_y_a_bien_17_sources_toutes_SANS_CLE() -> None:
    """*Flo : « je ne veux rien de payant ».*"""
    assert len(SOURCES) >= 17
    noms = {s.nom for s in SOURCES}
    for attendu in ("openalex", "arxiv", "semanticscholar", "openreview", "paperswithcode",
                    "pypi", "cratesio", "npm", "hackernews", "stackexchange", "dblp",
                    "zenodo", "softwareheritage", "crossref", "wikipedia", "github",
                    "github_code"):
        assert attendu in noms, "source manquante : %s" % attendu


def test_OPENREVIEW_EST_LA_MEILLEURE_SOURCE_et_on_dit_pourquoi() -> None:
    """🔑 ***Un rapport de relecture est de la CRITIQUE INSTITUTIONNALISEE.***

    *Un relecteur est PAYE en reputation pour trouver ce qui cloche.* C'est notre signal
    « aveu de limite » -- **mais ecrit par un ADVERSAIRE EXPERT, a l'echelle industrielle.**
    """
    o = next(s for s in SOURCES if s.nom == "openreview")
    assert o.fiabilite == max(s.fiabilite for s in SOURCES), (
        "OpenReview doit etre la source la PLUS fiable")
    assert "relecture" in o.pourquoi.lower()
    assert "payé pour dire non" in o.pourquoi or "payé en réputation" in o.pourquoi

    # on teste **le SENS**, pas un mot precis. *Un test qui cherche un mot teste ma prose,
    # pas mon code.*
    lm = rapport()["la_meilleure"]
    assert "OpenReview" in lm
    assert "relecture" in lm.lower()
    assert "aveu" in lm.lower(), (
        "c'est notre signal « aveu de limite » -- mais ecrit par un ADVERSAIRE EXPERT")


def test_PAPERSWITHCODE_relie_le_papier_au_CODE() -> None:
    """*Un papier SANS code est une affirmation. Un papier AVEC son implementation est verifiable.*"""
    p = next(s for s in SOURCES if s.nom == "paperswithcode")
    assert "affirmation" in p.pourquoi.lower() or "vérifiable" in p.pourquoi.lower()


def test_ON_DIT_qu_il_n_y_a_AUCUN_moteur_web_gratuit() -> None:
    """🔴 ***Je ne fais pas semblant d'avoir un acces web generique.***"""
    r = rapport()
    assert "google / bing" in r["inaccessibles"]
    assert "semblant" in r["franchise"].lower()
    assert "payant" in r["franchise"].lower()


@pytest.mark.parametrize("nom", [s.nom for s in SOURCES if s.nom not in ("github", "github_code")])
def test_CHAQUE_source_sait_fabriquer_son_URL(nom: str) -> None:
    u = url(nom, "market making")
    assert u and u.startswith("http"), "source sans URL : %s" % nom


def test_une_source_INCONNUE_rend_None_on_ne_devine_PAS() -> None:
    assert url("source_qui_nexiste_pas", "x") is None


def test_CHAQUE_source_respecte_un_RYTHME() -> None:
    """*Se faire bannir = MOINS de donnees, pas plus.*"""
    for s in SOURCES:
        assert s.rythme > 0, "source sans rythme : %s" % s.nom
    assert next(s for s in SOURCES if s.nom == "arxiv").rythme >= 3.0, (
        "arXiv demande 3 s entre deux appels. **On obeit.**")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. LE PARSING — *une liste VIDE si illisible, JAMAIS du faux.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_OPENALEX_reconstruit_le_resume_depuis_l_index_INVERSE() -> None:
    """*On le RECONSTRUIT ; on ne l'invente pas.*"""
    d = json.dumps({"results": [{
        "display_name": "Optimal market making",
        "id": "https://openalex.org/W1",
        "cited_by_count": 120,
        "abstract_inverted_index": {"We": [0], "model": [1], "kappa": [2]},
    }]})
    out = parser("openalex", d)
    assert out and out[0][0] == "Optimal market making"
    assert out[0][1] == "We model kappa", "le resume doit etre RECONSTRUIT dans le bon ordre"
    assert out[0][3] == 120


def test_OPENREVIEW_extrait_LA_CRITIQUE_pas_le_resume() -> None:
    """🔑 *Le tresor, c'est **ce que le relecteur reproche**, pas ce que l'auteur promet.*"""
    d = json.dumps({"notes": [{
        "forum": "abc",
        "content": {
            "title": {"value": "A market making paper"},
            "weaknesses": {"value": "The authors ignore transaction costs entirely."},
            "review": {"value": "The backtest appears to be in-sample."},
        },
    }]})
    out = parser("openreview", d)
    assert out
    corps = out[0][1]
    assert "ignore transaction costs" in corps, "la CRITIQUE doit remonter"
    assert "in-sample" in corps


@pytest.mark.parametrize("nom", ["openalex", "openreview", "semanticscholar", "crossref",
                                 "dblp", "zenodo", "pypi", "cratesio", "npm",
                                 "hackernews", "stackexchange", "wikipedia", "arxiv"])
def test_un_payload_ILLISIBLE_ne_donne_RIEN_jamais_du_faux(nom: str) -> None:
    """*Une liste vide est honnete. Une devinette ne l'est pas.*"""
    assert parser(nom, "{ pas du json") == []
    assert parser(nom, "") == []
