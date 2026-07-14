"""T1 -- TRANCHER SANS LE NOMBRE INVENTE (2026-07-12).

CE QUE CES TESTS DEFENDENT
--------------------------
`part_du_flux = 0.10` etait INVENTE. Aucune mesure ne le soutenait. Tant qu'il pilotait le
resultat, le "$/h" annonce etait une decoration -- et la memoire du projet le disait sans
detour : *"tant qu'il y est, les 11 pistes valent zero."*

La sortie est STRUCTURELLE, pas cosmetique :

    net_bps = capture - frais - selection_adverse        <- ne contient PAS part_du_flux
    pnl_h   = volume x part_du_flux x net_bps / 10 000   <- le contient

**Le SIGNE du verdict ne depend donc pas du nombre invente.** C'est le premier test ci-dessous,
et c'est le plus important du fichier : il prouve qu'on peut trancher KAITO sans jamais ecrire
10 %.

Pour les dollars, on ne devine plus : on BORNE. Le plafond physique (100 % du flux qui nous
atteint) est indepassable. Si meme lui est derisoire, la question est reglee.

Et la place dans la file ne se CHOISIT pas : les trois bornes sont rendues (H-95).

Aucun ordre reel.
"""
from __future__ import annotations

import random

from hl_observer.backtesting.market_making_flow import (
    FENETRE_MIN_OBSERVATION_S,
    MIN_TRADES,
    MIN_TRADES_POUR_CONCLURE,
    encadrer_le_market_making,
    evaluer_market_making,
    ic_bootstrap_mediane,
)

T0 = 1_800_000_000.0


ESPACEMENT_S = 3.0      # DENSE : ~10 trades dans l'horizon de 30 s -- voir la note ci-dessous


def _flux(
    n: int = 1_600,
    *,
    derive_bps: float = 0.0,
    fenetre_s: float | None = None,
    gros_toxiques: bool = False,
    graine: int = 7,
    spread_du_flux_bps: float = 20.0,
) -> list[dict]:
    """Un flux synthetique AVEC UN VRAI CARNET : un mid latent, un spread, les BUY a l'ask et
    les SELL au bid. `derive_bps` = de combien le mid suit l'agresseur (= selection adverse).

    `gros_toxiques` : les GROS trades poussent le mid bien plus fort que les petits -- c'est
    l'hypothese a tester, puisqu'un retail au fond de la file n'est rempli QUE par les gros.

    L'HISTOIRE DE CE FIXTURE (trois corrections, trois lecons)
    ---------------------------------------------------------
    **1re version -- trades espaces de 6 s.** L'horizon adverse fait 30 s : chaque mesure
    englobait ~5 trades suivants. Je croyais que leurs impacts « noyaient » celui du gros
    trade, et j'ai espace les trades a 60 s pour « isoler » l'effet. **C'etait une erreur de
    raisonnement** -- j'y reviens plus bas.

    **2e version -- tous les trades au meme prix.** Un marche sans bid ni ask. Quand le moteur
    est passe a une mesure MID-a-MID (correctif du bid-ask bounce), il n'avait plus rien a
    reconstruire : l'estimateur de mid n'a de sens que si les trades alternent entre deux
    cotes. Trois tests sont tombes -- et c'etait encore le fixture, pas le code.

    **3e version (celle-ci) -- DENSE, avec un vrai carnet.** Le diagnostic a montre que mon
    « isolation » a 60 s produisait un impact mesure valant exactement la MOITIE de l'impact
    injecte : avec un seul trade dans l'horizon, une seule cote du mid se rafraichit. Mon
    fixture ne testait pas un marche -- il testait une pathologie que j'avais fabriquee.

    La verite est l'inverse de mon intuition : les 5 trades suivants ne NOIENT pas le signal,
    **ils SONT le signal.** La perte d'un maker sur 30 s, c'est le deplacement NET du mid sur
    30 s -- trades intermediaires compris. La mediane sur plusieurs centaines de mesures
    retrouve la derive conditionnelle sans peine.

    Espacement 3 s, horizon 30 s -> ~10 trades par fenetre, les deux cotes se rafraichissent.
    C'est un marche qu'on peut mesurer. `n = 1600` : la borne DERRIERE n'en retient que le
    quart (400) -- il en faut 300 pour que le module accepte de conclure.
    """
    rng = random.Random(graine)
    dt = (fenetre_s / n) if fenetre_s else ESPACEMENT_S
    mid = 100.0
    demi = spread_du_flux_bps / 2 / 10_000.0
    out: list[dict] = []
    for i in range(n):
        agresseur = "BUY" if rng.random() < 0.5 else "SELL"
        gros = (i % 4 == 0)                        # 25 % de gros trades
        notionnel = 5_000.0 if gros else 200.0
        d = derive_bps * (3.0 if (gros_toxiques and gros) else 1.0)
        signe = 1.0 if agresseur == "BUY" else -1.0
        out.append({
            "coin": "TEST", "ts": T0 + i * dt,
            "px": mid * (1.0 + signe * demi),      # BUY prend l'ask, SELL tape le bid
            "sz": notionnel / (mid or 1.0), "aggressor": agresseur,
            "notional_usd": notionnel, "snapshot": False,
        })
        mid *= (1.0 + signe * d / 10_000.0)        # le MID suit l'agresseur -> le maker perd
    return out


# ============================================================ LE TEST QUI COMPTE

def test_le_verdict_ne_depend_PAS_du_nombre_invente():
    """LA PROPRIETE CENTRALE DE T1.

    `part_du_flux` (10 %, invente) fait varier le $/h... et RIEN d'autre. Le `net_bps` -- le
    seul chiffre qui decide si le market making a un edge -- est identique.

    Si ce test tombe, c'est que le nombre invente s'est reintroduit dans la decision.
    """
    trades = _flux(derive_bps=0.4)

    a = evaluer_market_making("TEST", trades, spread_bps=20.0, part_du_flux=0.10)
    b = evaluer_market_making("TEST", trades, spread_bps=20.0, part_du_flux=0.80)

    assert a.pnl_net_bps == b.pnl_net_bps, (
        "le net par aller-retour a bouge avec une hypothese de FILE : "
        "le nombre invente est revenu dans la decision"
    )
    assert a.pnl_par_h_usd != b.pnl_par_h_usd, (
        "les dollars devraient dependre de la part du flux -- sinon le modele ne modelise rien"
    )


def test_encadrer_ne_prend_AUCUNE_hypothese_de_file():
    """Le nouveau verdict n'a meme pas de parametre `part_du_flux` : on ne peut PAS l'inventer."""
    import inspect

    params = inspect.signature(encadrer_le_market_making).parameters
    assert "part_du_flux" not in params, (
        "l'hypothese de file est reapparue dans la signature -- c'est exactement ce qu'on a retire"
    )
    v = encadrer_le_market_making("TEST", _flux(derive_bps=0.2), spread_bps=20.0)
    assert "AUCUNE" in v.as_dict()["hypothese_de_file"]


# ============================================================ les 3 bornes (H-95)

def test_les_trois_bornes_sont_toutes_rendues():
    v = encadrer_le_market_making("TEST", _flux(derive_bps=0.2), spread_bps=20.0)
    assert [b.nom for b in v.bornes] == ["DEVANT", "MILIEU", "DERRIERE"]


def test_derriere_est_plus_severe_quand_les_gros_trades_sont_toxiques():
    """LE COEUR DU CORRECTIF : un retail est DERRIERE dans la file. Il n'est rempli que par les
    gros trades -- et les gros trades sont les plus informes. Sa selection adverse est donc PIRE
    que la mediane du flux.

    Mesurer l'adverse sur TOUS les trades publics, c'est se donner la place d'un MM pro.
    """
    v = encadrer_le_market_making(
        "TEST", _flux(derive_bps=0.3, gros_toxiques=True), spread_bps=20.0
    )
    devant = next(b for b in v.bornes if b.nom == "DEVANT")
    derriere = next(b for b in v.bornes if b.nom == "DERRIERE")
    assert devant.adverse_bps is not None and derriere.adverse_bps is not None
    assert derriere.adverse_bps > devant.adverse_bps, (
        "la borne DERRIERE devrait subir PLUS de selection adverse que DEVANT quand les gros "
        "trades poussent le prix : sinon on se raconte la place d'un market maker professionnel"
    )
    assert v.verdict == derriere.verdict, "le verdict du marche doit etre celui de la borne REALISTE"


def test_le_plafond_de_dollars_est_indepassable():
    """Le PnL max/h suppose qu'on capture 100 % du flux qui nous atteint. C'est impossible --
    donc le vrai chiffre est FORCEMENT plus bas. Un plafond, pas une prevision."""
    v = encadrer_le_market_making("TEST", _flux(derive_bps=0.0), spread_bps=40.0)
    derriere = next(b for b in v.bornes if b.nom == "DERRIERE")
    devant = next(b for b in v.bornes if b.nom == "DEVANT")
    assert derriere.volume_atteignable_par_h_usd <= devant.volume_atteignable_par_h_usd, (
        "on ne peut pas etre atteint par PLUS de flux en etant plus loin dans la file"
    )


# ============================================================ l'intervalle de confiance

def test_un_signe_qui_tient_dans_le_bruit_est_declare_INCONCLUSIF():
    """UN EDGE QUI TIENT DANS SON INTERVALLE DE CONFIANCE N'EST PAS UN EDGE.

    C'est le mecanisme qui nous a fait croire a des edges inexistants : lire un signe dans du
    bruit. Ici, le spread couvre tout juste les frais -> le net est ~0 -> l'IC traverse zero ->
    le verdict doit le DIRE, pas trancher.
    """
    v = encadrer_le_market_making("TEST", _flux(derive_bps=0.0, graine=3), spread_bps=6.02)
    derriere = next(b for b in v.bornes if b.nom == "DERRIERE")
    assert derriere.net_ic_bas is not None and derriere.net_ic_haut is not None
    if derriere.net_ic_bas <= 0 <= derriere.net_ic_haut:
        assert "INCONCLUSIF" in derriere.verdict


def test_un_marche_franchement_perdant_est_declare_perdant():
    """Symetrie : le gate ne dit pas "inconclusif" a tout. Une selection adverse ecrasante
    doit produire un PERDANT net, IC compris.

    (Ce test demandait au depart 3 bps de derive contre 10 de spread : net ~ -1 bps, avec un IC
    de +/-1,5. Le moteur repondait INCONCLUSIF -- **et il avait raison** : un edge de -1 bps
    noye dans +/-1,5 de bruit n'est pas un PERDANT prouve, c'est un signe illisible. J'ai
    corrige le TEST, pas le moteur. On ne deplace pas le poteau quand la mesure repond juste.)
    """
    v = encadrer_le_market_making("TEST", _flux(derive_bps=8.0), spread_bps=6.0)
    derriere = next(b for b in v.bornes if b.nom == "DERRIERE")
    assert derriere.net_bps is not None and derriere.net_bps < 0
    assert "PERDANT" in derriere.verdict


def test_l_ic_bootstrap_est_deterministe_et_encadre_la_mediane():
    vals = [1.0, -2.0, 3.0, -1.0, 0.5, 2.5, -3.0, 4.0, 0.0, 1.5] * 30
    m1, b1, h1 = ic_bootstrap_mediane(vals)
    m2, b2, h2 = ic_bootstrap_mediane(vals)
    assert (m1, b1, h1) == (m2, b2, h2), "un IC non deterministe rendrait l'audit irreproductible"
    assert b1 <= m1 <= h1


# ============================================================ toxicite par cote (H-111)

def test_la_toxicite_est_mesuree_PAR_COTE():
    """H-111 : le bid et l'ask n'ont pas la meme toxicite. Les confondre, c'est moyenner
    un cote sain avec un cote empoisonne -- et rater les deux."""
    v = encadrer_le_market_making("TEST", _flux(derive_bps=0.3), spread_bps=20.0)
    d = v.as_dict()
    assert "adverse_cote_buy_bps" in d and "adverse_cote_sell_bps" in d


# ============================================================ deny-by-default

def test_sans_assez_de_trades_on_ne_conclut_PAS():
    v = encadrer_le_market_making("TEST", _flux(n=MIN_TRADES - 5), spread_bps=20.0)
    assert v.bornes == ()
    assert "rien a mesurer" in v.verdict or "FLUX QUASI NUL" in v.verdict


def test_une_rafale_n_est_pas_un_debit():
    """CASHCAT : 86 trades en 14 secondes -> le modele annonçait 9,5 M$/h. Une rafale n'est
    pas un debit. La fenetre minimale reste opposable."""
    v = encadrer_le_market_making(
        "TEST", _flux(n=400, fenetre_s=FENETRE_MIN_OBSERVATION_S / 30.0), spread_bps=20.0
    )
    assert v.bornes == ()
    assert "rafale" in v.verdict or "FENETRE" in v.verdict


def test_le_snapshot_n_est_pas_du_flux():
    """A la souscription, Hyperliquid renvoie l'HISTORIQUE. Le compter comme du temps reel
    fabrique du volume qui n'existe pas."""
    trades = _flux(n=MIN_TRADES_POUR_CONCLURE + 100)
    for t in trades:
        t["snapshot"] = True
    v = encadrer_le_market_making("TEST", trades, spread_bps=20.0)
    assert v.bornes == ()
    assert "SNAPSHOT" in v.verdict


def test_aucun_verdict_ne_pretend_a_une_execution_reelle():
    v = encadrer_le_market_making("TEST", _flux(derive_bps=0.2), spread_bps=20.0)
    assert v.as_dict()["real_execution"] is False
    for b in v.bornes:
        assert b.as_dict()["real_execution"] is False


# ============================================================ LE VERROU DE FILE
#
# LE VERROU QUI A TUE LE SEUL CANDIDAT POSITIF DU PROJET (2026-07-12).
#
# CASHCAT sortait "CANDIDAT : net +7,7 bps [+6,1 ; +10,0], plafond 373 $/h" -- premier resultat
# positif jamais produit. La physique du carnet l'a demoli en une ligne :
#
#     profondeur au meilleur prix : 2 577 $   (mediane de 382 releves)
#     trade median : 90 $   |   p99 : 1 452 $
#     trades qui balayent 2 577 $ : **9 sur 4 641 = 0,19 %**
#
# La borne DERRIERE supposait 1 032 fills. La realite en donne **9**. Et 9 < MIN_TRADES (30) :
# sur le flux qui nous atteint VRAIMENT, on ne peut meme pas MESURER la selection adverse.
#
# Un edge dans une file qu'on n'atteint pas n'est pas un edge : c'est une decoration.

def test_une_file_infranchissable_INTERDIT_le_verdict_CANDIDAT():
    """Le cas CASHCAT, en synthetique : du flux, un beau spread, un markout favorable...
    et une profondeur devant nous que presque aucun trade ne balaye."""
    trades = _flux(n=1_600, derive_bps=0.2)          # notionnels : 200 $ et 5 000 $

    # sans le verrou : un CANDIDAT bien propre
    sans = encadrer_le_market_making("TEST", trades, spread_bps=40.0)
    assert "CANDIDAT" in sans.verdict, "le fixture doit produire un candidat AVANT le verrou"

    # avec 50 000 $ poses devant nous : AUCUN trade (max 5 000 $) ne balaye la file
    avec = encadrer_le_market_making(
        "TEST", trades, spread_bps=40.0, profondeur_devant_usd=50_000.0
    )
    assert "CANDIDAT" not in avec.verdict, (
        "un marche dont AUCUN trade ne balaye la file a ete declare CANDIDAT : "
        "on promet un edge sur des fills qui n'arriveront jamais -- %r" % avec.verdict
    )
    assert "FILE_NON_FRANCHISSABLE" in avec.verdict
    assert avec.bornes == (), "aucune borne ne doit etre calculee quand la file est fermee"


def test_une_file_franchissable_laisse_passer_le_verdict():
    """Symetrie : le verrou n'interdit pas tout. Une file mince laisse le verdict se prononcer."""
    trades = _flux(n=1_600, derive_bps=0.2)
    v = encadrer_le_market_making(
        "TEST", trades, spread_bps=40.0, profondeur_devant_usd=150.0   # tous les trades passent
    )
    assert "FILE_NON_FRANCHISSABLE" not in v.verdict
    assert v.bornes, "les bornes doivent etre calculees quand la file est franchissable"


def test_le_flux_qui_balaye_la_file_se_compte_juste():
    from hl_observer.backtesting.market_making_flow import flux_qui_balaye_la_file

    trades = [
        {"notional_usd": 100.0}, {"notional_usd": 3_000.0},
        {"notional_usd": 50.0}, {"notional_usd": 9_000.0},
        {"notional_usd": 5_000.0, "snapshot": True},        # un snapshot n'est PAS du flux
    ]
    n, usd = flux_qui_balaye_la_file(trades, 2_500.0)
    assert n == 2 and usd == 12_000.0

    assert flux_qui_balaye_la_file(trades, 0.0) == (0, 0.0), (
        "une profondeur nulle ou negative ne doit rien affirmer"
    )


# ============================================================ LA BORNE QUI SE DEGRADAIT EN SILENCE
#
# BUG DE PRODUCTION TROUVE LE 2026-07-12 (par un diagnostic, pas par un test -- d'ou ces tests).
#
# `retenus = [t for t in pertes if t.notionnel >= _quantile(notionnels, 0.75)]`
#
# Mesure reelle : 1 198 trades a EXACTEMENT 200 $ et 399 a 5 000 $.
#   -> `_quantile(.., 0.75)` = **200 $**
#   -> `notionnel >= 200` retient **100 % des trades**
#   -> la borne DERRIERE devenait la borne DEVANT, **sans un mot**.
#
# On imprimait trois bornes. Il n'y en avait qu'une, la plus OPTIMISTE, portant trois noms.

def _flux_avec_atome(n: int = 1_600) -> list[dict]:
    """75 % des trades a EXACTEMENT 200 $, 25 % a 5 000 $ -- l'atome qui cassait le seuil."""
    return _flux(n=n, derive_bps=0.3, gros_toxiques=True)


def test_la_borne_DERRIERE_ne_retient_PAS_tout_le_monde():
    """Le test que le bug attendait. `n >= quantile(0.75)` retenait 100 % des trades."""
    from hl_observer.backtesting.market_making_flow import selection_par_rang
    from hl_observer.backtesting.market_making_flow import _pertes_maker

    pertes = _pertes_maker(_flux_avec_atome())
    assert len(pertes) > 300, "flux trop pauvre pour ce test"

    tous, _ = selection_par_rang(pertes, 0.0)
    quart, seuil = selection_par_rang(pertes, 0.75)

    assert len(quart) < len(tous) * 0.30, (
        "la borne DERRIERE retient %d/%d trades (%.0f %%) : elle s'est degradee en DEVANT. "
        "Trois bornes affichees, un seul chiffre derriere."
        % (len(quart), len(tous), 100.0 * len(quart) / len(tous))
    )
    assert seuil > 1_000.0, "le seuil effectif devrait etre celui des GROS trades"


def test_les_bornes_de_file_ne_rendent_PAS_le_meme_chiffre():
    """Signature du bug : DEVANT et DERRIERE rendaient un adverse identique au centieme pres.
    Deux hypotheses de file opposees qui tombent d'accord, c'est qu'une seule est calculee."""
    v = encadrer_le_market_making("TEST", _flux_avec_atome(), spread_bps=20.0)
    devant = next(b for b in v.bornes if b.nom == "DEVANT")
    derriere = next(b for b in v.bornes if b.nom == "DERRIERE")

    assert devant.n_fills != derriere.n_fills, (
        "DEVANT et DERRIERE retiennent le MEME nombre de fills (%d) : la selection ne "
        "selectionne rien" % devant.n_fills
    )
    assert derriere.adverse_bps is not None and devant.adverse_bps is not None
    assert derriere.adverse_bps > devant.adverse_bps, (
        "DERRIERE (%.2f) devrait etre PLUS toxique que DEVANT (%.2f) quand les gros trades "
        "poussent le prix" % (derriere.adverse_bps, devant.adverse_bps)
    )


# ============================================================ UN MARCHE TROP LENT NE SE MESURE PAS

def test_un_flux_trop_LENT_refuse_de_rendre_un_chiffre():
    """DENY-BY-DEFAULT SUR LA DENSITE (2026-07-12).

    Un mid reconstruit depuis le flux n'est un mid QUE si les deux cotes sont fraiches. Sur un
    marche qui traite une fois par minute, l'horizon de 30 s ne contient qu'UN trade : une seule
    cote se rafraichit, et l'impact mesure vaut la MOITIE du vrai.

    Un biais de facteur 2 **dans le sens optimiste** : le market making paraissait deux fois
    moins toxique qu'il ne l'est. Mieux vaut ZERO chiffre qu'un chiffre flatteur.
    """
    lent = _flux(n=1_600, derive_bps=3.0, fenetre_s=1_600 * 90.0)   # un trade toutes les 90 s
    v = encadrer_le_market_making("LENT", lent, spread_bps=20.0)

    assert "NON MESURABLE" in v.verdict or "INSUFFISANT" in v.verdict, (
        "un marche a 1 trade / 90 s a rendu un verdict (%r) alors que son mid ne peut pas "
        "etre reconstruit a un horizon de 30 s" % v.verdict
    )


def test_un_flux_DENSE_lui_se_mesure():
    """Symetrie : le gate de densite ne refuse pas tout. Un marche liquide se mesure."""
    v = encadrer_le_market_making("DENSE", _flux(derive_bps=0.3), spread_bps=20.0)
    derriere = next(b for b in v.bornes if b.nom == "DERRIERE")
    assert derriere.adverse_bps is not None, "un flux dense doit rendre une mesure"


# ============================================================ LE BID-ASK BOUNCE N'EST PAS UN EDGE
#
# LE FAUX EDGE LE PLUS DANGEREUX DE LA SOIREE (2026-07-12).
#
# La 1re version mesurait le markout contre **le prix du trade suivant**. Sur les VRAIES donnees
# de CASHCAT elle a sorti :
#
#     selection adverse : -15,7 bps   (le prix irait EN NOTRE FAVEUR apres nous avoir remplis !)
#     net               : +31,4 bps  [IC +29,7 ; +32,7]
#     verdict           : "CANDIDAT REEL -- plafond 1 071 $/h"
#
# Un edge positif, un IC qui ne traverse pas zero, sur des donnees reelles. Tout etait faux.
#
# Le chiffre le criait : le demi-spread de CASHCAT vaut 17,75 bps, et -15,7 ~ -(spread/2).
# C'est du BID-ASK BOUNCE : le prix des trades oscille MECANIQUEMENT entre le bid et l'ask.
# Le spread etait compte DEUX FOIS -- une fois dans la capture, une fois dans ce faux markout.
#
# Ces tests fabriquent un marche SANS AUCUNE INFORMATION : le mid ne bouge jamais, seuls les
# trades sautent du bid a l'ask. La bonne reponse est ZERO. Toute autre reponse est un artefact.

def _marche_sans_information(n: int = 1_600, *, spread_bps: float = 40.0) -> list[dict]:
    """Un marche PARFAITEMENT neutre : le mid ne bouge JAMAIS. Seuls les trades rebondissent
    entre le bid et l'ask. Un maker n'y gagne ni n'y perd un centime d'information."""
    rng = random.Random(11)
    mid = 100.0
    demi = mid * spread_bps / 2 / 10_000.0
    out = []
    for i in range(n):
        achete = rng.random() < 0.5
        out.append({
            "coin": "NEUTRE", "ts": T0 + i * ESPACEMENT_S,
            "px": mid + demi if achete else mid - demi,     # ask ou bid, RIEN d'autre
            "sz": 1.0, "aggressor": "BUY" if achete else "SELL",
            "notional_usd": 5_000.0 if i % 4 == 0 else 200.0, "snapshot": False,
        })
    return out


def test_le_bid_ask_bounce_ne_produit_AUCUN_edge():
    """LE TEST LE PLUS IMPORTANT DU FICHIER.

    Sur un marche ou le mid ne bouge JAMAIS, la selection adverse doit valoir ZERO -- et le net
    doit valoir exactement `capture - frais`, pas un bps de plus.

    Si ce test tombe, c'est qu'on a recommence a mesurer le markout sur le prix des trades :
    on compte le spread deux fois et on fabrique un edge de +30 bps a partir de rien.
    """
    v = encadrer_le_market_making("NEUTRE", _marche_sans_information(), spread_bps=40.0)
    derriere = next(b for b in v.bornes if b.nom == "DERRIERE")

    assert derriere.adverse_bps is not None
    assert abs(derriere.adverse_bps) < 1.0, (
        "selection adverse de %+.1f bps sur un marche SANS information : c'est le bid-ask "
        "bounce qu'on mesure, pas un edge. Le markout doit se prendre du MID au MID."
        % derriere.adverse_bps
    )
    # capture (20) - frais (3) = 17. Rien de plus ne doit apparaitre.
    assert abs(derriere.net_bps - 17.0) < 1.5, (
        "net de %+.1f bps alors que capture - frais = 17,0 : %.1f bps sortis de nulle part "
        "(le spread compte deux fois)." % (derriere.net_bps, derriere.net_bps - 17.0)
    )


def test_le_mid_estime_ne_rebondit_PAS_avec_les_trades():
    """La serie de mids doit etre PLATE sur un marche neutre -- c'est tout l'objet du correctif."""
    from hl_observer.backtesting.market_making_flow import serie_de_mids

    mids = [m for _, m in serie_de_mids(_marche_sans_information(n=200))]
    assert mids, "aucun mid estime"
    assert max(mids) - min(mids) < 1e-6, (
        "le 'mid' bouge alors que le marche est neutre : il suit les trades, donc il rebondit"
    )


# ============================================================ UN TROU N'EST PAS UNE FENETRE
#
# Bug trouve le 2026-07-12 EN REGARDANT L'UI : les fichiers `trades*.jsonl` contiennent
# PLUSIEURS sessions d'ecoute, separees par des heures. Consequences, et elles ne sont pas
# cosmetiques :
#   * la "fenetre d'observation" affichee valait 8 h alors qu'on n'avait ecoute que 40 min ;
#   * le verrou des 30 min etait donc franchi par une ILLUSION ;
#   * pire : a l'horizon de 30 s, un trade juste avant un trou voyait son "prix apres" pris
#     8 HEURES plus tard. La selection adverse devenait le bruit d'une nuit.

def test_trois_sessions_separees_ne_font_pas_une_fenetre_continue():
    """20 min + 20 min + 20 min, separees par 4 h : ça fait 1 h d'observation, pas 8 h."""
    from hl_observer.backtesting.market_making_flow import fenetre_continue_s

    ts: list[float] = []
    for depart in (0.0, 4 * 3600.0, 8 * 3600.0):
        ts += [depart + i * 10.0 for i in range(120)]      # 120 x 10 s = 20 min

    assert fenetre_continue_s(ts) == 3 * 1190.0            # 3 segments de 19 min 50 s
    assert ts[-1] - ts[0] > 8 * 3600.0                     # l'ecart brut, lui, ment


def test_la_selection_adverse_ne_traverse_JAMAIS_un_trou():
    """LE BUG DANGEREUX. Un trade juste avant un trou de 8 h ne doit PAS voir son 'prix 30 s
    apres' pris de l'autre cote du trou -- ce serait le bruit d'une nuit, pas son impact.

    Ici : une session DENSE de 20 min a prix plat, puis 8 h de silence, puis une reprise a un
    prix DOUBLE. Si le garde-fou saute, les derniers trades de la 1re session mesurent
    +10 000 bps d'adverse. Il ne doit rien en rester.

    (Ce fixture etait a l'origine 400 achats a 60 s d'intervalle -- un marche sans vendeur et
    sans debit. Il ne pouvait donc plus rien mesurer une fois le gate de densite pose. Un
    marche a sens unique n'est pas un marche : c'est une file d'attente.)
    """
    from hl_observer.backtesting.market_making_flow import _pertes_maker

    def _burst(depart: float, mid: float, n: int) -> list[dict]:
        demi = mid * 20.0 / 2 / 10_000.0                    # spread 20 bps
        return [{"coin": "T", "ts": depart + i * 3.0,       # DENSE : 1 trade / 3 s
                 "px": mid + (demi if i % 2 == 0 else -demi),
                 "aggressor": "BUY" if i % 2 == 0 else "SELL",
                 "notional_usd": 500.0} for i in range(n)]

    trades = _burst(0.0, 100.0, 400)                        # 20 min a prix plat
    trades += _burst(400 * 3.0 + 8 * 3600.0, 200.0, 400)    # +8 h, prix x2

    pertes = [p for p, _, _ in _pertes_maker(trades)]
    assert pertes, "il doit rester des mesures VALIDES a l'interieur de la session"
    assert max(pertes) < 100.0, (
        "une perte enorme a ete mesuree A TRAVERS le trou : le 'mid 30 s apres' a ete pris "
        "8 heures plus tard. C'est du bruit de nuit, pas de la selection adverse."
    )
