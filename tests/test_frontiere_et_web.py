r"""LA FRONTIERE ET LE WEB OUVERT — *il ne doit JAMAIS rester sans chercher.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LES DEUX INQUIETUDES DE FLO ONT LA MEME CAUSE
═══════════════════════════════════════════════════════════════════════════════════════════════

  🔴 « au bout de 10 h il ne saura plus quoi chercher »
  🔴 « plein de termes de recherche avec 0 resultat »

    ***C'est le MEME defaut, vu par ses deux bouts.***

Le moissonneur avait une **LISTE**. Une liste est **FINIE** (elle s'epuise) et **DEVINEE**
(mes mots-cles, pas ceux du terrain).

    au bout de N heures  -> plus rien a chercher
    des la 1re heure     -> des requetes steriles, parce que je les avais INVENTEES

La reponse : **une FRONTIERE**. *Le corpus genere ses propres requetes.*

    ***Un crawler avec une frontiere ne peut PAS etre a court.***

Aucun reseau. Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.research.frontiere import (
    FOND_DE_ROULEMENT,
    Frontiere,
    Piste,
    depuis_commits,
    depuis_dependances,
    extraire,
    fond_de_roulement,
)
from hl_observer.research.web_ouvert import (
    INACCESSIBLES,
    LE_WEB,
    RYTHMES,
    rapport,
    url_openalex,
    url_openalex_cite_par,
)

README = """
# hl-mm
We implement the model of Avellaneda and Stoikov, extended by Gueant Lehalle.
See arxiv.org/abs/1105.3115 for the derivation. Our `qty_ahead` estimator follows
https://github.com/nkaz001/hftbacktest . We compute VPIN on a volume clock and OFI
from the order book. Fill intensity: lambda = A exp(-kappa delta).
Limitations: our GLFT solver assumes zero latency.
"""


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. 🔑 LE CORPUS GENERE SES PROPRES REQUETES.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LE_TEST_QUI_COMPTE_un_README_engendre_des_pistes() -> None:
    """***Un README cite Almgren-Chriss -> nouvelle requete. C'est comme ca qu'on n'est
    jamais a court.***
    """
    p = extraire(README, parent="o/hl-mm")
    r = [x.requete for x in p]

    assert any("1105.3115" in x for x in r), "le PAPIER cite doit engendrer une piste"
    assert any("nkaz001/hftbacktest" in x for x in r), "le REPO cite aussi"
    assert any("Avellaneda" in x for x in r), "le NOM PROPRE ouvre une litterature entiere"
    assert any("GLFT" in x or "VPIN" in x or "OFI" in x for x in r), (
        "les ACRONYMES du metier ouvrent chacun un pan du sujet")
    assert any("qty_ahead" in x for x in r), "un symbole entre backticks est un symbole qui compte"


def test_CHAQUE_piste_porte_sa_PARENTE() -> None:
    """*Une requete dont on ne peut pas dire d'ou elle vient est une requete qu'on ne peut pas
    juger -- et c'est comme ca qu'on se retrouve avec des « 0 resultat » inexplicables.*
    """
    for x in extraire(README, parent="o/hl-mm"):
        assert x.venu_de and x.parent, "piste orpheline : %r" % (x,)
        assert x.genre in ("repo", "code", "papier", "biblio")


def test_LA_LAISSE_un_terme_HORS_SUJET_n_entre_PAS() -> None:
    """***Un crawler sans laisse finit sur des recettes de cuisine.***"""
    p = extraire(
        "The environmental impact of Smith Johnson's cooking recipes. See API and JSON docs.",
        parent="x",
    )
    r = " ".join(x.requete for x in p)
    assert "Smith" not in r, "un nom propre hors de notre domaine ne doit PAS entrer"
    assert "API" not in r and "JSON" not in r, "les acronymes de bruit sont ecartes"


def test_LA_PORTE_DE_DOMAINE_un_texte_SANS_marche_est_MUET() -> None:
    """🔒 **LE GARDE-FOU QUE L'AUDIT M'A FORCE A ECRIRE.**

    L'audit durci (20 textes hors sujet) a trouve **9 fuites** :

        « **Race condition** in a video game... **Deadlock** in the render thread »  -> 4 pistes
        « **Insurance fund** for natural disasters... **collateral** damage »        -> 4 pistes
        « A survey of image compression... **Rate limiting** on the CDN »            -> 1 piste

    Ces motifs sont **legitimes chez nous** -- mais ils existent **aussi** ailleurs.

        ***Un terme d'ingenierie ne devient NOTRE terme que s'il est assis dans un contexte
           de MARCHE.***

    ***On ne raffine pas un filtre : on ferme d'abord la porte.***
    """
    from hl_observer.research.frontiere import dans_notre_domaine

    pieges = (
        "Race condition in a video game rendering loop. Deadlock in the render thread.",
        "Insurance fund for natural disasters: how governments manage collateral damage.",
        "A survey of image compression algorithms. Rate limiting on the CDN.",
        "Supply chain optimization: inventory management and warehouse throughput.",
        "Poker strategy: bet sizing and pot odds. Managing your bankroll and variance.",
        "Database indexing tutorial: B-trees, cache locality and query performance.",
    )
    for p in pieges:
        assert not dans_notre_domaine(p), "la porte laisse passer : %r" % p
        assert extraire(p, parent="x") == [], "🔴 **FUITE** : %r" % p

    # ...et elle laisse passer ce qui est VRAIMENT chez nous
    for vrai in (
        "Deadlock in the order matching engine of the exchange.",
        "The insurance fund of the perpetual exchange absorbs liquidations.",
        "Rate limiting on the exchange API for order submission.",
    ):
        assert dans_notre_domaine(vrai), "la porte refuse ce qui est chez nous : %r" % vrai


def test_le_contexte_decide_pas_le_mot_seul() -> None:
    """*« impact » dans une phrase sur l'impact ecologique n'est PAS notre impact.*"""
    ecolo = extraire("The carbon impact of Smith Johnson's factory.", parent="x")
    nous = extraire("The market impact model of Almgren Chriss for order execution.", parent="x")
    assert not any("Smith" in x.requete for x in ecolo)
    assert any("Almgren" in x.requete for x in nous)


def test_les_DEPENDANCES_engendrent_des_pistes() -> None:
    """*Le `requirements.txt` d'un bon repo est une liste de courses validee par un expert.*"""
    p = depuis_dependances(["hftbacktest", "nautilus_trader"], parent="o/r")
    assert {x.requete for x in p} == {"hftbacktest", "nautilus_trader"}
    assert all(x.genre == "biblio" for x in p)


def test_les_COMMITS_engendrent_des_pistes() -> None:
    """*Un commit `fix kappa estimation` NOMME un probleme que quelqu'un a RESOLU.*"""
    p = depuis_commits(["fix: kappa estimation on thin order book", "chore: bump"], parent="o/r")
    assert p and "kappa" in p[0].requete
    assert not any("bump" in x.requete for x in p)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. 🔑 LA FRONTIERE NE SE VIDE JAMAIS.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LA_FRONTIERE_GRANDIT_PENDANT_QU_ON_LA_VIDE() -> None:
    """***C'est LE point.*** On depile une piste, elle en engendre d'autres."""
    f = Frontiere()
    f.semer(extraire(README, parent="o/hl-mm"), profondeur=0)
    depart = f.reste()
    assert depart > 0

    p = f.prochaine()
    assert p is not None
    # ce qu'on lit en explorant cette piste engendre... encore des pistes
    #
    # 🔒 NOTE : le texte doit contenir un mot de MARCHE. C'est la **porte de domaine**, ecrite
    #    apres que l'audit ait trouve 9 fuites (« **Deadlock** in the render thread » engendrait
    #    4 pistes !). ***Un terme d'ingenierie ne devient NOTRE terme que dans un contexte de
    #    marche.*** Un texte sans le moindre mot de marche est **muet** pour nous -- et c'est VOULU.
    n = f.semer(extraire(
        "We follow Almgren Chriss and compute the OFI imbalance on the order book "
        "to improve execution in this market.",
        parent=p.requete), profondeur=1)
    assert n > 0, "explorer une piste doit en engendrer d'autres -- sinon on s'epuise"


def test_UN_FOND_DE_ROULEMENT_pour_qu_il_ne_reste_JAMAIS_sans_chercher() -> None:
    """🎓 Flo : *« il ne doit jamais rester sans chercher ou travailler »*.

    Si la frontiere se vide **vraiment**, on retombe sur **la litterature qu'on aurait du lire** :
    les categories entieres de q-fin, **les COURS**, les **revues**.
    *Un moissonneur qui a fini son plan et qui n'a pas lu q-fin.TR n'a rien fini.*
    """
    f = fond_de_roulement()
    assert len(f) >= 15
    joint = " ".join(x.requete + " " + x.venu_de for x in f)
    assert "q-fin.TR" in joint, "toute la litterature « Trading & Market Microstructure »"
    assert "lecture notes" in joint, "🎓 **les COURS** que Flo demande"
    assert "survey" in joint or "review" in joint, (
        "🎓 une REVUE = 100 papiers deja digeres par quelqu'un dont c'est le metier")


def test_une_frontiere_VIDE_peut_toujours_etre_RE_ENSEMENCEE() -> None:
    f = Frontiere()
    assert f.prochaine() is None            # vide au depart
    assert f.semer(fond_de_roulement()) > 0  # ...mais jamais a court
    assert f.prochaine() is not None


def test_les_pistes_LOURDES_passent_en_premier() -> None:
    """*Un papier cite pese plus qu'un acronyme vu en passant.*"""
    f = Frontiere()
    f.semer([Piste("leger", "papier", "acronyme", "x", 0.5),
             Piste("lourd", "papier", "papier cite", "x", 2.0)])
    assert f.prochaine().requete == "lourd"


def test_ON_NE_RE_CHERCHE_PAS_ce_qu_on_a_deja_vu() -> None:
    f = Frontiere()
    p = [Piste("a", "papier", "x", "x")]
    assert f.semer(p) == 1
    assert f.semer(p) == 0, "le quota est notre ressource rare : on ne paie pas deux fois"


def test_ANTI_DERIVE_la_profondeur_est_BORNEE() -> None:
    """🔒 ***Un crawler sans laisse derive.*** Une piste ne peut pas engendrer a l'infini."""
    f = Frontiere()
    assert f.semer([Piste("trop_loin", "papier", "x", "x")],
                   profondeur=f.PROFONDEUR_MAX + 1) == 0


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. 🔴 LES STERILES — *Flo : « plein de termes avec 0 resultat ».*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LES_STERILES_SONT_COMPTES_ET_PUBLIES_pas_caches() -> None:
    """🔑 *Ce sont, pour la plupart, des mots-cles que J'AVAIS DEVINES.*

    Les publier, c'est **avouer lesquels de mes mots-cles etaient du vent** -- et c'est
    precisement pourquoi les requetes doivent etre **EXTRAITES DU TERRAIN**, pas inventees.
    """
    f = Frontiere()
    bon = Piste("kappa fill intensity", "papier", "x", "x")
    mauvais = Piste("mon mot-cle devine", "papier", "x", "x")
    f.semer([bon, mauvais])
    f.noter(bon, 12)
    f.noter(mauvais, 0)

    d = f.as_dict()
    assert any(x["requete"] == "mon mot-cle devine" for x in d["requetes_STERILES"])
    assert any(x["requete"] == "kappa fill intensity" for x in d["requetes_FECONDES"])
    assert "devin" in d["pourquoi_les_steriles"].lower(), (
        "on doit DIRE que les steriles viennent de MES devinettes")


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. 🌐 LE WEB OUVERT — *et la franchise sur ce qu'on N'A PAS.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_ON_DIT_qu_il_n_existe_AUCUN_moteur_de_recherche_gratuit() -> None:
    """🔴 ***Je ne fais pas semblant d'avoir un acces web generique.***

    Google et Bing exigent une cle **payante**. Flo : « je ne veux rien de payant ».
    """
    r = rapport()
    assert "google" in r["inaccessibles"] or "google / bing" in r["inaccessibles"]
    assert "payant" in r["franchise"].lower()
    assert "semblant" in r["franchise"].lower()


def test_TOUTES_les_sources_retenues_sont_SANS_CLE_donc_GRATUITES() -> None:
    """*Flo : « je ne veux rien de payant ».*"""
    assert all(s.sans_cle for s in LE_WEB)
    noms = {s.nom for s in LE_WEB}
    assert {"openalex", "arxiv", "semanticscholar", "hackernews", "stackexchange"} <= noms


def test_OPENALEX_donne_ce_qu_un_MOTEUR_ne_donnerait_PAS_le_graphe_de_citations() -> None:
    """🔑 ***Un moteur de recherche nous donnerait des blogs.
       OpenAlex nous donne CE QUE LE METIER A RETENU.***
    """
    o = next(s for s in LE_WEB if s.nom == "openalex")
    assert "citation" in o.pourquoi.lower()
    assert o.fiabilite >= 1.3, "c'est notre meilleure source"

    u = url_openalex_cite_par("https://openalex.org/W123")
    assert "cites:W123" in u, "on doit pouvoir demander : **QUI CITE ce papier ?**"
    assert "cited_by_count:desc" in url_openalex("market making")


def test_LES_COURS_que_Flo_demande_sont_dans_le_fond_de_roulement() -> None:
    """🎓 *« des cours avances sur les bots »* -> les **lecture notes** et les **revues**."""
    r = rapport()
    assert "cours" in r["les_cours_que_flo_veut"].lower()
    joint = " ".join(q for _g, q, _p in FOND_DE_ROULEMENT)
    assert "lecture notes" in joint


def test_ON_RESPECTE_le_rythme_de_CHAQUE_source() -> None:
    """*Se faire bannir = MOINS de donnees, pas plus.*"""
    for s in LE_WEB:
        assert s.nom in RYTHMES, "source sans rythme documente : %s" % s.nom
    assert RYTHMES["arxiv"] >= 3.0, "arXiv demande 3 s entre deux appels. **On obeit.**"
    assert RYTHMES["github_code"] >= 6.0, "/search/code est bien plus severe"


@pytest.mark.parametrize("nom", [n for n, _ in INACCESSIBLES])
def test_chaque_source_INACCESSIBLE_dit_POURQUOI(nom: str) -> None:
    """*Une source qu'on n'a pas lue n'est pas une source vide -- et il faut dire laquelle.*"""
    assert dict(INACCESSIBLES)[nom]
