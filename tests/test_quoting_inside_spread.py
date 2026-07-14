"""#587 / T1b — coter DANS le spread. Et le detecteur doit MORDRE dans les deux sens.

T1 avait laisse UNE porte ouverte : « et si on se mettait DEVANT la file, en ameliorant le prix
d'un tick ? ». Ce fichier verifie que la mesure qui repond a cette question ne peut ni fabriquer
un edge, ni en cacher un.

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.quoting_inside_spread import (
    COUT_ALLER_RETOUR_BPS,
    MIN_FILLS,
    MIN_SNAPSHOTS,
    MOTIF_CAPTURE_SOUS_LES_FRAIS,
    MOTIF_INSUFFISANT,
    MOTIF_INVENTAIRE,
    MOTIF_PAS_DE_PLACE,
    Snapshot,
    Trade,
    capture_inside_bps,
    estimer_tick,
    evaluer_quoting_inside,
    place_interieure,
)


def _snaps(coin: str, n: int, *, bid: float, ask: float, t0: float = 0.0) -> list[Snapshot]:
    """⚠️ `t0` N'EST PAS UN DETAIL -- il m'a coute un test rouge que j'ai d'abord mis sur le dos
    du mount.

    Quand j'ajoutais les snapshots « qui imposent le tick » avec les MEMES timestamps que le flux
    (0, 1, 2...), il y avait **DEUX carnets differents au meme instant**. `_mid_a` prenait le
    dernier -- le carnet IMMOBILE -- et le markout ne mesurait plus rien.

    *Un jeu de test incoherent produit un resultat parfaitement stable... et parfaitement faux.*
    """
    return [
        Snapshot(ts=t0 + float(i), coin=coin, bid=bid, ask=ask, mid=(bid + ask) / 2.0)
        for i in range(n)
    ]


def _tick_snaps(coin: str, n: int, *, mid: float, tick: float, t0: float = -500.0):
    """Des snapshots qui IMPOSENT le tick, **au MEME niveau de prix** que le reste.

    🔴 2e ROUGE QUE JE ME SUIS INFLIGE. Ma version precedente posait ces snapshots a
    `bid=100.00 / ask=100.01` (mid **100,005**) alors que le flux principal vivait a **100,5**.
    Mon propre decor fabriquait donc un **saut de prix de 49 bps** -- et le garde-fou d'inventaire
    le mesurait fidelement, puis refusait.

    *Le module avait raison. C'est le TEST qui mentait.* On centre donc les snapshots de tick sur
    le meme mid.
    """
    demi = tick / 2.0
    return [
        Snapshot(ts=t0 + float(i), coin=coin, bid=mid - demi, ask=mid + demi, mid=mid)
        for i in range(n)
    ]


def _flux_toxique(coin: str, n: int, *, bid0: float, ask0: float, derive_bps: float):
    """Un flux ou **le CARNET** suit l'agresseur : c'est ca, la selection adverse.

    🔴 ET C'EST LE POINT DU CORRECTIF : la 1re version de ce helper faisait deriver **le prix des
    trades**, pas le carnet. Sur donnees reelles, ca produisait un « adverse » NEGATIF (le prix
    irait en notre faveur !) -- c'etait le **bid-ask bounce**, le faux edge que T1 avait deja
    trouve. On construit donc ici un carnet qui BOUGE, et on mesure le markout dessus.

    Rend (snapshots, trades) coherents entre eux.

    ⚠️ LES AGRESSEURS ARRIVENT EN **RAFALES** (blocs de 20 du meme cote).

    🚩 Ma 1re version alternait BUY/SELL a CHAQUE pas : le mid montait puis redescendait, et la
    selection adverse **s'annulait a zero**. Le test rougissait -- avec raison. Un flux *informe*
    n'alterne pas : **il pousse**. Quelqu'un qui sait achete, encore et encore. C'est ce qui rend
    le flux toxique, et c'est ce qu'il faut simuler pour que le garde-fou ait un sens.
    """
    snaps: list[Snapshot] = []
    trades: list[Trade] = []
    bid, ask = bid0, ask0
    # ⚠️ LA RAFALE DOIT ETRE PLUS LONGUE QUE L'HORIZON DE MARKOUT (30 s), sinon le markout
    # regarde DANS LA RAFALE SUIVANTE (de sens oppose) et la selection adverse s'annule a zero.
    # (2e version rouge de ce helper. Le detail qui fait qu'un test mesure -- ou pas.)
    RAFALE = 60
    for i in range(n):
        t = float(i)
        snaps.append(Snapshot(ts=t, coin=coin, bid=bid, ask=ask, mid=(bid + ask) / 2.0))
        agr = "BUY" if (i // RAFALE) % 2 == 0 else "SELL"      # des RAFALES, pas une alternance
        # le trade se fait au bid ou a l'ask (bounce) -- il ne doit PAS influer sur le markout
        trades.append(Trade(ts=t, coin=coin, px=(ask if agr == "BUY" else bid),
                            notional_usd=100.0, aggressor=agr))
        # LE CARNET suit l'agresseur : voila la vraie information
        k = 1.0 + (derive_bps / 1e4) * (1 if agr == "BUY" else -1)
        bid, ask = bid * k, ask * k
    return snaps, trades


# ============================================================ 1. LE TICK ET LA PLACE


def test_le_tick_est_estime_par_le_PLUS_PETIT_spread_observe():
    """Un spread ne peut pas etre plus petit qu'un tick. C'est une borne HAUTE du tick -- donc une
    estimation CONSERVATRICE de la place : si on se trompe, c'est en NOTRE defaveur."""
    s = _snaps("X", 5, bid=100.0, ask=100.5) + _snaps("X", 5, bid=100.0, ask=100.1)
    assert estimer_tick(s) == pytest.approx(0.1)


def test_un_spread_D_UN_SEUL_TICK_n_a_PAS_d_interieur():
    """🔴 LE POINT LE PLUS IMPORTANT DE T1b.

    BTC : `bid 63906 / ask 63907`. Le spread fait **un tick**. Ameliorer les deux cotes d'un tick
    **croiserait le marche**. *Ce n'est pas une question de rendement : c'est une impossibilite
    arithmetique.* On ne peut pas coter « dans » un spread qui n'a pas de dedans.
    """
    assert place_interieure(spread=1.0, tick=1.0) == pytest.approx(-1.0)
    assert capture_inside_bps(spread=1.0, tick=1.0, mid=63906.5) == 0.0

    v = evaluer_quoting_inside("BTC", _snaps("BTC", 60, bid=63906.0, ask=63907.0), [])
    assert v.viable is False
    assert v.motif == MOTIF_PAS_DE_PLACE
    assert v.part_snapshots_avec_place == 0.0


def test_un_spread_LARGE_laisse_de_la_place():
    v_snaps = _snaps("Y", 60, bid=100.0, ask=101.0)          # spread 1.0
    # ... mais un tick de 0,01 -> il reste 0,98 apres avoir donne 2 ticks
    v_snaps += _snaps("Y", 5, bid=100.0, ask=100.01)         # impose le tick = 0,01
    t = estimer_tick(v_snaps)
    assert t == pytest.approx(0.01)
    assert place_interieure(1.0, t) == pytest.approx(0.98)


# ============================================================ 2. LA MORT PAR ARITHMETIQUE


def test_une_capture_SOUS_LES_FRAIS_est_morte_AVANT_toute_question_de_flux():
    """*Meme rempli a 100 % et sans aucune selection adverse, on perd.* Il n'y a alors rien a
    mesurer : le refus est arithmetique, et il precede toute discussion sur le flux."""
    # spread 2 ticks -> il reste 0 apres avoir donne 2 ticks... mettons 2,5 ticks
    snaps = _snaps("Z", 60, bid=1000.0, ask=1000.25) + _snaps("Z", 5, bid=1000.0, ask=1000.10)
    v = evaluer_quoting_inside("Z", snaps, [])          # noqa: E501
    # tick = 0,10 ; spread 0,25 -> place = 0,05 -> capture = 0,5 bps < 3,0 bps de frais
    assert v.viable is False
    assert v.motif == MOTIF_CAPTURE_SOUS_LES_FRAIS
    assert v.capture_inside_bps < COUT_ALLER_RETOUR_BPS


# ============================================================ 3. DENY-BY-DEFAULT


def test_pas_assez_de_SNAPSHOTS_INSUFFICIENT_DATA():
    v = evaluer_quoting_inside("A", _snaps("A", MIN_SNAPSHOTS - 1, bid=100.0, ask=101.0), [])
    assert v.motif == MOTIF_INSUFFISANT
    assert v.viable is False


def test_capture_qui_passe_les_frais_mais_TROP_PEU_DE_FILLS_ne_conclut_PAS():
    """🔴 LA LECON DE #242, APPLIQUEE D'AVANCE.

    Mon outil de cointegration avait imprime « VIABLE : +95 bps » sur **UN SEUL trade**. Ici, si
    la capture passe les frais mais qu'on n'a pas assez de fills pour mesurer la selection
    adverse, on **ne conclut pas** -- meme si le chiffre est beau.
    """
    s, t = _flux_toxique("B", MIN_FILLS - 5, bid0=100.0, ask0=101.0, derive_bps=0.0)
    s += _tick_snaps("B", 40, mid=100.5, tick=0.01)      # impose le tick, SANS saut de prix
    v = evaluer_quoting_inside("B", s, t)
    assert v.viable is False
    assert v.motif == MOTIF_INSUFFISANT


# ============================================================ 4. 🔴 LE BID-ASK BOUNCE


def test_le_markout_NE_DOIT_PAS_etre_calcule_sur_les_PRIX_DE_TRADE():
    """🔴🔴 LE BUG QUE MON PROPRE OUTIL A COMMIS, ET QUE T1 AVAIT DEJA TROUVE.

    Ici : un carnet **parfaitement immobile**, et des trades qui alternent bid/ask (le bounce).
    Un markout calcule sur les PRIX DE TRADE verrait le prix « monter » quand on achete au bid et
    que le trade suivant tape l'ask -> il annoncerait un edge FABRIQUE d'un demi-spread.

    Sur donnees reelles, ma 1re version a sorti **CASHCAT : adverse = -14,77 bps** (spread
    35,6 -> demi-spread 17,8). Le prix serait alle en NOTRE FAVEUR apres 8 558 fills. Ca n'existe
    pas. *C'etait le bounce, et T1 l'avait deja documente comme « un faux edge de +31 bps ».*

    Avec le markout sur le MID : carnet immobile -> selection adverse **exactement nulle**.
    """
    snaps = [Snapshot(ts=float(i), coin="F", bid=100.0, ask=101.0, mid=100.5)
             for i in range(200)]
    snaps += _tick_snaps("F", 40, mid=100.5, tick=0.01)          # tick, meme niveau de prix
    trades = [
        Trade(ts=float(i), coin="F", px=(101.0 if i % 2 == 0 else 100.0),   # BOUNCE pur
              notional_usd=100.0, aggressor=("BUY" if i % 2 == 0 else "SELL"))
        for i in range(200)
    ]
    v = evaluer_quoting_inside("F", snaps, trades)
    assert v.n_fills_simules >= MIN_FILLS
    assert v.adverse_bps == pytest.approx(0.0, abs=1e-6), (
        "le markout a capte le BID-ASK BOUNCE : adverse=%.3f bps sur un carnet IMMOBILE. "
        "C'est un edge FABRIQUE." % v.adverse_bps
    )


# ============================================================ 5. LE DETECTEUR MORD DANS LES 2 SENS


def test_une_selection_adverse_FORTE_tue_meme_une_grosse_capture():
    """Le flux nous punit : **le CARNET** suit l'agresseur. Meme avec une capture genereuse, on
    perd."""
    s, t = _flux_toxique("C", 200, bid0=100.0, ask0=101.0, derive_bps=60.0)
    s += _tick_snaps("C", 40, mid=100.5, tick=0.01)
    v = evaluer_quoting_inside("C", s, t)
    assert v.n_fills_simules >= MIN_FILLS
    assert v.adverse_bps > 0, "la selection adverse doit COUTER (le mid part contre nous)"
    assert v.viable is False


def test_un_flux_SANS_information_laisse_la_capture_survivre():
    """🚩 Le garde-fou doit pouvoir dire OUI, sinon il ne mesure rien -- il refuse par principe.

    Carnet immobile = aucune information dans le flux -> la capture doit survivre. Si ce test
    echoue, le module refuse TOUT par construction : il serait VERT et AVEUGLE.
    """
    s, t = _flux_toxique("D", 200, bid0=100.0, ask0=101.0, derive_bps=0.0)
    s += _tick_snaps("D", 40, mid=100.5, tick=0.01)
    v = evaluer_quoting_inside("D", s, t)
    assert v.n_fills_simules >= MIN_FILLS
    assert v.capture_inside_bps > COUT_ALLER_RETOUR_BPS
    assert v.viable is True, (
        "sur un flux SANS information, coter dans le spread doit rapporter. Ce module refuse "
        "tout par construction -- il ne mesure rien."
    )


def test_l_hypothese_de_remplissage_est_la_PLUS_GENEREUSE_possible():
    """On suppose qu'on prend **100 % des agresseurs** (on est seul, au meilleur prix).
    *Si ca ne paie pas MEME LA, ca ne paiera nulle part.* C'est la seule facon d'obtenir un
    « non » qui vaille quelque chose."""
    s, t = _flux_toxique("E", 100, bid0=100.0, ask0=101.0, derive_bps=0.0)
    s += _tick_snaps("E", 40, mid=100.5, tick=0.01)
    v = evaluer_quoting_inside("E", s, t)
    assert v.n_fills_simules >= 90, (
        "l'hypothese de remplissage n'est pas a 100 %% : le « non » qu'on obtiendrait serait "
        "attaquable (« vous n'avez pas assez de fills »)"
    )


# ============================================================ 6. 🔴 LE RISQUE D'INVENTAIRE


def test_un_marche_qui_BOUGE_PLUS_que_la_capture_est_un_PARI_pas_du_MARKET_MAKING():
    """🔴🔴 LA PORTE QUE MA 1re VERSION AVAIT OUBLIEE -- ET QUI CHANGE LE VERDICT.

    Ma 1re passe annoncait **« CASHCAT : +34,94 bps net, VIABLE »**. J'allais te l'annoncer.
    Puis j'ai regarde QUI survivait :

      * **CASHCAT** -- le coin que notre propre zone morte FUNDING_JAMBE_NUE designe nommement
        comme **« le marche le plus dangereux »** : il bouge de **219 bps/h** ;
      * **KAITO** -- celui que T1 avait deja etudie, et qui s'etait revele un mirage.

    Capturer 35 bps de spread sur un coin qui bouge de 219 bps EN UNE HEURE, ce n'est pas du
    market making : ***c'est un pari directionnel avec un coupon.*** C'est la phrase EXACTE qu'on
    avait ecrite pour refuser le funding sur jambe nue. **Le meme piege, sous un autre nom.**

    Un MM ne gagne pas le spread : il gagne le spread **moins la variance de l'inventaire qu'il
    est force de porter**. Sans ce terme, **tout marche volatil parait genereux** -- et c'est
    PRECISEMENT pour ca que son spread est large. *Le spread n'est pas un cadeau : c'est le prix
    du risque.*
    """
    # spread genereux (100 bps), mais le mid part en fleche : +30 bps toutes les 60 s
    snaps: list[Snapshot] = []
    trades: list[Trade] = []
    bid, ask = 100.0, 101.0
    for i in range(400):
        snaps.append(Snapshot(ts=float(i), coin="MEME", bid=bid, ask=ask, mid=(bid + ask) / 2.0))
        agr = "BUY" if (i // 60) % 2 == 0 else "SELL"
        trades.append(Trade(ts=float(i), coin="MEME", px=(ask if agr == "BUY" else bid),
                            notional_usd=50.0, aggressor=agr))
        k = 1.0 + 0.0030 * (1 if agr == "BUY" else -1)      # 30 bps par pas : un vrai memecoin
        bid, ask = bid * k, ask * k
    snaps += _tick_snaps("MEME", 40, mid=100.5, tick=0.01)     # tick, sans saut de prix

    v = evaluer_quoting_inside("MEME", snaps, trades)
    assert v.vol_detention_bps > v.capture_inside_bps, (
        "le decor du test est faux : le prix doit bouger PLUS que la capture"
    )
    assert v.viable is False
    assert v.motif == MOTIF_INVENTAIRE


def test_un_marche_CALME_avec_un_spread_large_reste_VIABLE():
    """🚩 Le garde-fou doit pouvoir dire OUI. Sinon il ne mesure rien : il refuse par principe.

    Un carnet immobile avec un spread large : la capture existe, l'inventaire ne coute rien.
    C'est le cas theorique ou le market making PAIE. S'il ne passe pas, mon module est VERT et
    AVEUGLE.
    """
    snaps = [Snapshot(ts=float(i), coin="CALME", bid=100.0, ask=101.0, mid=100.5)
             for i in range(300)]
    snaps += _tick_snaps("CALME", 40, mid=100.5, tick=0.01)      # MEME mid : aucun saut
    trades = [
        Trade(ts=float(i), coin="CALME", px=(101.0 if i % 2 == 0 else 100.0),
              notional_usd=50.0, aggressor=("BUY" if i % 2 == 0 else "SELL"))
        for i in range(300)
    ]
    v = evaluer_quoting_inside("CALME", snaps, trades)
    assert v.vol_detention_bps == pytest.approx(0.0, abs=1e-6)
    assert v.viable is True, (
        "sur un marche calme au spread large, coter dans le spread DOIT rapporter. Ce module "
        "refuse tout par construction -- il ne mesure rien."
    )


def test_GARDE_FOU_le_fichier_de_test_n_a_pas_ete_TRONQUE():
    """🚩 CE TEST EXISTE PARCE QUE J'AI TRONQUE CE FICHIER AVEC MON PROPRE PATCH.

    J'ai lance un `python` **depuis le sandbox** pour patcher ce fichier. Le mount **tronque en
    LECTURE** : le script a lu une copie coupee, et l'a **reecrite par-dessus l'original**.
    La moitie des tests a disparu -- silencieusement.

    Ma propre memoire le documente depuis le 12/07 : *« le mount tronque aussi en LECTURE ;
    en cas de desaccord, `Read` natif a raison, pas bash. »* Je l'ai lu, ecrit, et refait.

    **Regle : ne JAMAIS reecrire un fichier du projet depuis le sandbox.**
    """
    import ast
    import pathlib
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    ast.parse(src)                                    # leve SyntaxError si le fichier est coupe
    for nom in (
        "test_l_hypothese_de_remplissage_est_la_PLUS_GENEREUSE_possible",
        "test_un_marche_CALME_avec_un_spread_large_reste_VIABLE",
        "test_le_markout_NE_DOIT_PAS_etre_calcule_sur_les_PRIX_DE_TRADE",
    ):
        assert nom in src, "test disparu -> fichier tronque : %s" % nom