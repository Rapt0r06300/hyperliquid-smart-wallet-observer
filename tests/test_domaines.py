r"""LA CARTE DES DOMAINES — *tout ce qu'un bot doit savoir, pas seulement comment gagner.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE FLO A VU, ET QUI ETAIT PLUS GRAVE QU'IL NE LE PENSAIT
═══════════════════════════════════════════════════════════════════════════════════════════════

    *« 14 categories, c'est trop peu. »*

Il avait raison -- mais la vraie faute n'etait pas le **NOMBRE**, c'etait la **NATURE** :

    ***Mes 14 categories couvraient le cote ALPHA (comment gagner).
       Elles ne couvraient presque RIEN du cote SURVIE (comment ne pas mourir).***

    **Et c'est la survie qui tue les bots.**

🔴 **LE TROU QUE CA M'A FAIT TROUVER DANS NOTRE PROPRE BOT : le LEG RISK.**

    ***Notre carry a DEUX jambes. Si le spot passe et pas le perp -- ON EST A NU.***
    C'est-a-dire **exactement** le pari directionnel qu'on a mesure a **-7,97 bps**.
    Jamais cherche, jamais mesure, jamais couvert.

Aucun ordre reel. Aucun reseau.
"""
from __future__ import annotations

import pytest

from hl_observer.research.domaines import (
    ADVERSAIRE,
    ALPHA,
    CODE,
    DOMAINES,
    MACHINE,
    MECANIQUE,
    QUANT,
    SURVIE,
    VERITE,
    familles,
    rapport,
    tous_les_motifs,
    tous_les_sujets,
    toutes_les_requetes,
)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  1. 🔴 LE TROU TROUVE — le LEG RISK.
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LE_LEG_RISK_EST_COUVERT_c_est_le_trou_le_plus_grave_de_notre_bot() -> None:
    """🔴🔴 ***Notre carry a DEUX jambes. Si le spot passe et pas le perp -- ON EST A NU.***

    Et un carry a nu, c'est **exactement** le pari directionnel mesure a **-7,97 bps**.
    *Et le carnet spot de PUMP ne porte que 473 $ : la jambe qui rate, c'est PRECISEMENT
    celle-la.*
    """
    d = next((x for x in DOMAINES if x.cle == "leg_risk"), None)
    assert d is not None, "🔴 le LEG RISK n'est PAS couvert -- c'est notre trou le plus grave"
    assert d.famille == SURVIE
    assert "-7,97" in d.pourquoi_nous or "7,97" in d.pourquoi_nous, (
        "il faut DIRE qu'une jambe a nu = le pari directionnel qu'on a mesure MORT")
    assert "473" in d.pourquoi_nous, (
        "le carnet spot de PUMP ne porte que 473 $ -- c'est LA jambe qui ratera")
    assert d.requetes, "un domaine sans requete ne sera jamais cherche"


def test_le_rapport_ANNONCE_le_trou_du_leg_risk() -> None:
    r = rapport()
    assert "LEG RISK" in r["le_trou_trouve"]
    assert "SURVIE" in r["le_constat"]


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2. LES 5 FAMILLES — *l'alpha n'est qu'UNE des cinq.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fam", [ALPHA, SURVIE, VERITE, MACHINE, ADVERSAIRE, MECANIQUE, CODE,
                                 QUANT])
def test_CHAQUE_famille_a_au_moins_un_domaine(fam: str) -> None:
    f = familles()
    assert fam in f and f[fam], "famille vide : %s" % fam


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2 ter. 🧮 LE SYSTEME QUANTITATIF — *la FINALITE de Flo : un vrai bot quantitatif.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_LA_FINALITE_le_systeme_QUANTITATIF_est_couvert() -> None:
    """🧮 Flo : *« finalite : faire un bot quantitatif »* + *« le maximum de recherches sur les
    systemes quantitatifs »*.

    ***Toutes les autres familles sont des BRIQUES. Celle-ci est la DISCIPLINE qui les assemble.***
    """
    f = familles()
    assert QUANT in f
    cles = {d.cle for d in f[QUANT]}
    for attendu in ("recherche_quant", "combinaison_signaux", "ml_finance",
                    "portfolio_construction", "execution_systeme", "plateformes_quant",
                    "gouvernance_quant"):
        assert attendu in cles, "aspect du systeme quant non couvert : %s" % attendu


def test_la_RECHERCHE_QUANT_rappelle_que_le_carry_est_ne_de_ce_PROCESSUS() -> None:
    """*Notre carry est ne d'un processus de falsification (~600 idees -> 1) sans qu'on l'ait
    formalise. **Le formaliser, c'est en trouver d'autres.***
    """
    d = next(x for x in DOMAINES if x.cle == "recherche_quant")
    assert "600" in d.pourquoi_nous
    assert "finalit" in d.pourquoi_nous.lower()
    joint = " ".join(d.requetes).lower()
    assert "lopez de prado" in joint, "le manuel de reference du ML financier"


def test_la_COMBINAISON_de_signaux_est_une_piste_QU_ON_N_A_JAMAIS_exploree() -> None:
    """🔴 *On teste chaque idee ISOLEMENT -> on jette tout ce qui n'est pas rentable SEUL.*

    ***Un systeme quant COMBINE des signaux faibles.*** Mais -- *prudence : combiner du bruit
    ne fait que du bruit mieux habille.*
    """
    d = next(x for x in DOMAINES if x.cle == "combinaison_signaux")
    assert "isol" in d.pourquoi_nous.lower()
    assert "bruit" in d.pourquoi_nous.lower(), "il faut RAPPELER le piege : combiner du bruit"


def test_les_PLATEFORMES_quant_on_les_ETUDIE_pas_on_les_reinvente() -> None:
    """🔑 *On a reecrit beaucoup de choses que d'autres ont deja bati ET DURCI.*"""
    d = next(x for x in DOMAINES if x.cle == "plateformes_quant")
    joint = " ".join(d.requetes).lower()
    assert "nautilus" in joint and "freqtrade" in joint
    assert "copier" in d.pourquoi_nous.lower() or "oublié" in d.pourquoi_nous.lower()


def test_le_ML_finance_previent_que_ce_N_EST_PAS_le_ML_normal() -> None:
    """🔴 *Non-stationnaire, ratio signal/bruit minuscule, overfit garanti.*

    *Avant d'en mettre, il faut savoir POURQUOI 90 %% des tentatives echouent -- sinon on ajoute
    une machine a surajuster a un projet qui a deja eu 68 %% de fuite train/test.*
    """
    d = next(x for x in DOMAINES if x.cle == "ml_finance")
    assert "68" in d.pourquoi_nous or "surajust" in d.pourquoi_nous.lower()


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  2 bis. 🧱 NOTRE CODE — *le bot qui execute la strategie est lui-meme une source de pertes.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════

def test_l_ARCHITECTURE_est_couverte_car_la_MALADIE_etait_ARCHITECTURALE() -> None:
    """🔴🔴 ***La maladie du projet, trouvee 18 fois : une capacite presente, un chainon
    manquant, personne qui se plaint.*** **22 modules livres, 3 branches.**

    ***Ce n'etait pas de la malchance : c'etait de l'ARCHITECTURE.*** Et d'autres l'ont
    surement resolu avant nous.
    """
    d = next(x for x in DOMAINES if x.cle == "architecture")
    assert d.famille == CODE
    # insensible a la casse : *un test qui teste ma typographie ne teste pas mon code.*
    bas = d.pourquoi_nous.lower()
    assert "18 fois" in bas
    assert "22 modules" in bas
    joint = " ".join(d.requetes).lower()
    assert "dead code" in joint, "on cherche comment DETECTER un module jamais appele"


def test_la_QUALITE_DU_SIGNAL_est_couverte_signal_age_etait_une_TAUTOLOGIE() -> None:
    """🔴🔴 ***`signal_age` GELAIT quand le flux calait*** -> le bot entrait sur du VIEUX en
    croyant que c'etait frais. **Le voyant de fraicheur etait FABRIQUE.**

    ***Un signal parfait vaut plus qu'une strategie parfaite : une strategie juste sur une
    donnee fausse PERD.***
    """
    d = next(x for x in DOMAINES if x.cle == "qualite_signal")
    assert "TAUTOLOGIE" in d.pourquoi_nous
    assert "souvenir" in d.pourquoi_nous, (
        "*un signal dont on ne peut pas prouver l'age n'est pas un signal : c'est un souvenir*")
    joint = " ".join(d.requetes).lower()
    assert "freshness" in joint or "staleness" in joint


def test_la_PERFORMANCE_rappelle_qu_on_n_a_JAMAIS_profile() -> None:
    """***Optimiser sans profiler, c'est deviner*** -- et deviner est ce que ce projet punit.

    Et la latence n'a **jamais** ete notre probleme (la courbe edge/horizon est PLATE) :
    ***si on optimise, ce doit etre pour une raison MESUREE, pas par reflexe.***
    """
    d = next(x for x in DOMAINES if x.cle == "performance")
    assert "jamais profil" in d.pourquoi_nous.lower()
    assert "PLATE" in d.pourquoi_nous, (
        "il faut RAPPELER que la latence n'a jamais ete notre probleme -- "
        "sinon on va optimiser par reflexe")


def test_les_TESTS_rappellent_que_la_COUVERTURE_ne_prouve_RIEN() -> None:
    """*La couverture dit « execute », jamais « VERIFIE ».* Notre mutation testing : **62,5 %%**."""
    d = next(x for x in DOMAINES if x.cle == "tests_qualite")
    assert "62,5" in d.pourquoi_nous
    assert "exécuté" in d.pourquoi_nous or "execute" in d.pourquoi_nous.lower()
    assert "mutation testing" in " ".join(d.requetes).lower()


def test_le_NUMERIQUE_rappelle_le_PIEGE_D_UNITE() -> None:
    """🔴 ***Comparer deux nombres qui ne sont pas dans la meme unite FABRIQUE un edge fantome.***

    8 h vs 1 h -> un faux **38 %% APR**. « 150 millions » -> **1 425 000** (facteur 105).
    """
    d = next(x for x in DOMAINES if x.cle == "numerique")
    assert "38" in d.pourquoi_nous
    assert "1 425 000" in d.pourquoi_nous or "105" in d.pourquoi_nous


def test_la_SURVIE_est_aussi_fournie_que_l_ALPHA() -> None:
    """***C'est la survie qui tue les bots, pas l'absence d'alpha.***

    Si la famille SURVIE a deux fois moins de domaines que l'ALPHA, **on est encore en train de
    ne chercher que comment gagner.**
    """
    f = familles()
    assert len(f[SURVIE]) >= len(f[ALPHA]) * 0.7, (
        "la SURVIE (%d domaines) est sous-representee face a l'ALPHA (%d). "
        "**On cherche encore surtout comment gagner.**" % (len(f[SURVIE]), len(f[ALPHA])))


def test_la_MECANIQUE_de_l_exchange_est_couverte() -> None:
    """🔴 *On a passe deux jours a decouvrir que les FRAIS n'etaient pas ce qu'on croyait,
    que le funding etait HORAIRE, que `BadAloPx` REJETTE au lieu de passer taker.*

    ***Chacune de ces decouvertes a change un chiffre qui decidait de CHAQUE trade.
    Et aucune n'etait une strategie : c'etait la MECANIQUE.***
    """
    f = familles()
    cles = {d.cle for d in f[MECANIQUE]}
    for attendu in ("mecanique_frais", "mecanique_ordres", "mecanique_marge",
                    "mecanique_funding", "mecanique_matching", "mecanique_api"):
        assert attendu in cles, "mecanique non couverte : %s" % attendu


def test_la_mecanique_des_ORDRES_rappelle_BadAloPx() -> None:
    """*Un post-only qui croiserait est REJETE, PAS execute en taker.* On croyait l'inverse."""
    d = next(x for x in DOMAINES if x.cle == "mecanique_ordres")
    assert "BadAloPx" in d.pourquoi_nous
    assert "REJET" in d.pourquoi_nous.upper()


def test_la_mecanique_du_FUNDING_rappelle_le_piege_d_unite() -> None:
    """🔴 *8 h vs 1 h -- le faux 38 %% APR.*

    ***Comparer deux nombres qui ne sont pas dans la meme unite FABRIQUE un edge fantome.***
    """
    d = next(x for x in DOMAINES if x.cle == "mecanique_funding")
    assert "38" in d.pourquoi_nous
    assert "unit" in d.pourquoi_nous.lower()


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  3. LES DOMAINES QUI MANQUAIENT VRAIMENT
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cle,pourquoi", [
    ("sizing", "on size a 500 $ FIXE -- aucune theorie. *Un edge positif avec un mauvais sizing "
               "ruine quand meme.*"),
    ("drawdown", "HLP, notre benchmark, a un drawdown de **70,6 %%**. *Un APR sans son drawdown "
                 "est la moitie d'un chiffre.*"),
    ("correlation", "PURR + HYPE = **la meme venue**. Si HL tousse, **les deux tombent ensemble**."),
    ("protocole", "notre carry SUPPOSE que Hyperliquid fonctionne"),
    ("collateral", "notre marge est en USDC -- *un depeg liquide la jambe perp*"),
    ("regimes", "BERA et STABLE ont BASCULE. *Un edge mesure sur 365 j n'est pas eternel.*"),
    ("flux", "**on a eu des STALLS** -- le flux s'est tu et le bot a decide sur du vieux"),
    ("observabilite", "le panneau SECURITE avait un voyant vert **SOUDE**"),
    ("adversaire", "on raisonne comme si le marche etait un decor. **Il est peuple.**"),
    ("crowding", "le carry HL est une idee **PUBLIQUE**"),
    ("statistique", "**~600 idees testees** -> a 5 %%, on trouve **30 decouvertes par hasard**"),
    ("donnees", "**biais du survivant** : on ne mesure que les coins qui existent ENCORE"),
    ("prediction_funding", "notre SEULE piste positive -- *on la prend en aveugle*"),
])
def test_le_domaine_manquant_est_maintenant_couvert(cle: str, pourquoi: str) -> None:
    d = next((x for x in DOMAINES if x.cle == cle), None)
    assert d is not None, "🔴 domaine NON couvert : %s (%s)" % (cle, pourquoi)
    assert d.requetes, "domaine sans requete = domaine jamais cherche : %s" % cle
    assert len(d.pourquoi_nous) > 50, "un « pourquoi NOUS » vide = un domaine qu'on abandonnera"


def test_la_STATISTIQUE_rappelle_le_probleme_des_TESTS_MULTIPLES() -> None:
    """🔴🔴 ***On a teste ~600 idees. A 5 %%, on trouve 30 « decouvertes » par PUR HASARD.***

    ***Notre unique survivant (le carry) est-il LE VRAI ou LE CHANCEUX ? On ne le sait pas.***
    """
    d = next(x for x in DOMAINES if x.cle == "statistique")
    assert "600" in d.pourquoi_nous
    assert "hasard" in d.pourquoi_nous.lower()
    joint = " ".join(d.requetes).lower()
    assert "multiple testing" in joint
    assert "deflated sharpe" in joint


def test_le_MARKET_MAKING_dit_qu_on_cherche_ce_qui_nous_donne_TORT() -> None:
    """*On ne cherche PAS a le ressusciter : on cherche ce qui nous donnerait tort.*"""
    d = next(x for x in DOMAINES if x.cle == "market_making")
    assert "0/29" in d.pourquoi_nous
    assert "tort" in d.pourquoi_nous.lower()


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  4. CHAQUE DOMAINE EST **CHERCHABLE** ET **RECONNAISSABLE**
# ═══════════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("d", DOMAINES, ids=lambda d: d.cle)
def test_chaque_domaine_a_des_REQUETES_et_des_MOTIFS(d) -> None:
    assert d.requetes, "sans requete, il ne sera **jamais cherche** : %s" % d.cle
    assert d.motifs, "sans motif, la frontiere sera **AVEUGLE** a ce sujet : %s" % d.cle
    assert len(d.quoi) > 20
    assert len(d.pourquoi_nous) > 40, (
        "*un « pourquoi » vide sera abandonne a la 1re difficulte* : %s" % d.cle)


def test_les_motifs_des_domaines_ENTRENT_dans_la_laisse_de_la_frontiere() -> None:
    """🔒 *Sans ca, la frontiere serait AVEUGLE a tout ce qui ne parle pas d'alpha.*"""
    from hl_observer.research.frontiere import PERTINENCE

    m = tous_les_motifs()
    manquants = [x for x in m if x not in PERTINENCE]
    assert not manquants, (
        "🔴 %d motif(s) de domaine ne sont PAS dans la laisse -> la frontiere ne les verra "
        "jamais : %s" % (len(manquants), manquants[:5]))


def test_les_requetes_des_domaines_ENTRENT_dans_le_plan_du_moissonneur() -> None:
    """🔒 *Un domaine defini mais pas branche est un domaine MORT.* (22 modules, 3 branches.)"""
    from hl_observer.research.moissonneur_sujets import TEXTE

    for q, cle, _p in toutes_les_requetes():
        assert q in TEXTE, "🔴 la requete du domaine `%s` n'est PAS dans le plan : %r" % (cle, q)


def test_les_sujets_des_domaines_ENTRENT_dans_les_SUJETS() -> None:
    from hl_observer.research.moissonneur_sujets import SUJETS

    for s in tous_les_sujets():
        assert s in SUJETS, "sujet de domaine non branche : %s" % s


def test_on_couvre_BEAUCOUP_plus_que_14_choses() -> None:
    """Flo : *« 14 sujets, c'est trop peu »*."""
    r = rapport()
    assert r["n_domaines"] >= 38, "on doit couvrir bien plus que les 14 d'avant"
    assert r["n_requetes"] >= 180, "%d requetes, c'est trop peu" % r["n_requetes"]
    assert len(r["par_famille"]) >= 8, "8 familles : alpha, survie, verite, machine, "\
                                       "adversaire, mecanique, notre code, **systeme quant**"
