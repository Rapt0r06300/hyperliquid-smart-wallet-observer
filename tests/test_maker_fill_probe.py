"""MESURER le taux de remplissage maker au lieu de le supposer.

Tout edge mesure ici meurt dans les couts : fast_follow REJETE a tous les horizons <= 300 s meme a
spread NUL, DeepLOB a -4 242 bps net. Le seul levier jamais ouvert est l'entree MAKER. Or
`robustness.maker_adjust_net` et `microstructure_extras.maker_queue_fill_prob` PRENNENT le
`fill_rate` en parametre : personne ne l'avait mesure. D'ou `maker_fill_proven: False` en dur dans
`native_cross_venue_replay` et des cles nommees `..._unproven_fill`.

Ces tests verrouillent les trois choix qui rendent la mesure honnete plutot que flatteuse :

1. on se met DERNIER dans la file (se croire devant fabrique un faux edge maker) ;
2. seul le volume au PRIX OU MIEUX consomme la file ;
3. « je ne sais pas » n'est JAMAIS « rempli » — et le taux porte toujours son denominateur.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import maker_fill_probe as M  # noqa: E402

CARNET = {"coin": "ETH", "bids5": [[100.0, 5.0], [99.0, 8.0]], "asks5": [[101.0, 4.0]]}


def _trade(ts: int, px: float, sz: float) -> dict:
    return {"ts_ms": ts, "px": px, "sz": sz}


# ------------------------------------------------------------------ la file

def test_toute_la_taille_affichee_est_DEVANT_nous():
    """Choix pessimiste assume : surestimer sa place dans la file est LA facon de se mentir."""
    assert M.file_devant(CARNET, 100.0, M.ACHAT) == 5.0
    assert M.file_devant(CARNET, 101.0, M.VENTE) == 4.0


def test_un_niveau_absent_ne_vaut_pas_zero():
    """Zero ferait croire la file vide, donc un remplissage facile. On dit « je ne sais pas »."""
    assert M.file_devant(CARNET, 97.5, M.ACHAT) is None


def test_un_carnet_abime_ne_fait_rien_planter():
    for carnet in ({}, {"bids5": None}, {"bids5": [[None, 1.0], ["x", "y"], [100.0]]}):
        assert M.file_devant(carnet, 100.0, M.ACHAT) is None


# ------------------------------------------------------------------ le volume qui consomme

def test_seul_le_volume_au_prix_OU_MIEUX_consomme_la_file():
    trades = [_trade(10, 100.5, 3.0), _trade(20, 100.0, 2.0), _trade(30, 99.5, 4.0)]
    volume, vus = M.volume_consommateur(trades, prix=100.0, cote=M.ACHAT, debut_ms=0, fin_ms=100)
    assert volume == 6.0          # 100.0 et 99.5 touchent ; 100.5 non
    assert vus == 3               # mais les trois sont bien OBSERVES


def test_le_sens_est_inverse_pour_une_vente_passive():
    trades = [_trade(10, 101.0, 2.0), _trade(20, 100.5, 7.0)]
    volume, _ = M.volume_consommateur(trades, prix=101.0, cote=M.VENTE, debut_ms=0, fin_ms=100)
    assert volume == 2.0


def test_les_trades_hors_fenetre_sont_ignores():
    trades = [_trade(5, 100.0, 9.0), _trade(50, 100.0, 1.0), _trade(500, 100.0, 9.0)]
    volume, vus = M.volume_consommateur(trades, prix=100.0, cote=M.ACHAT, debut_ms=10, fin_ms=100)
    assert (volume, vus) == (1.0, 1)


# ------------------------------------------------------------------ le verdict d'un cas

def test_rempli_quand_le_volume_couvre_la_file_ET_notre_taille():
    trades = [_trade(10, 99.0, 10.0)]
    r = M.sonder_un_cas(carnet=CARNET, trades=trades, prix_passif=100.0, cote=M.ACHAT,
                        debut_ms=0, horizon_ms=1000, taille_voulue=2.0)
    assert r["verdict"] == M.REMPLI
    assert r["volume_necessaire"] == 7.0          # 5 devant + 2 a nous
    assert r["marge"] == 3.0


def test_couvrir_la_file_SANS_couvrir_notre_taille_n_est_PAS_un_remplissage():
    """Sinon on compterait « rempli » un ordre servi a moitie — un edge gratuit et faux."""
    trades = [_trade(10, 100.0, 6.0)]
    r = M.sonder_un_cas(carnet=CARNET, trades=trades, prix_passif=100.0, cote=M.ACHAT,
                        debut_ms=0, horizon_ms=1000, taille_voulue=2.0)
    assert r["verdict"] == M.NON_REMPLI


def test_une_fenetre_SANS_AUCUN_trade_est_NON_MESURABLE_et_pas_non_rempli():
    """LE piege : conclure « non rempli » sur un trou de donnees ferait croire le maker impossible."""
    r = M.sonder_un_cas(carnet=CARNET, trades=[], prix_passif=100.0, cote=M.ACHAT,
                        debut_ms=0, horizon_ms=1000, taille_voulue=1.0)
    assert r["verdict"] == M.NON_MESURABLE
    assert r["motif"] == M.SANS_TRADES


def test_une_fenetre_PLEINE_mais_niveau_jamais_atteint_est_bien_NON_REMPLI():
    """A l'inverse : le marche a traite ailleurs, c'est une VRAIE information."""
    trades = [_trade(10, 100.5, 50.0), _trade(20, 101.0, 50.0)]
    r = M.sonder_un_cas(carnet=CARNET, trades=trades, prix_passif=100.0, cote=M.ACHAT,
                        debut_ms=0, horizon_ms=1000, taille_voulue=1.0)
    assert r["verdict"] == M.NON_REMPLI
    assert r["trades_observes"] == 2


def test_sans_carnet_ou_sans_niveau_on_refuse_de_conclure():
    assert M.sonder_un_cas(carnet=None, trades=[_trade(1, 100.0, 9.0)], prix_passif=100.0,
                           cote=M.ACHAT, debut_ms=0, horizon_ms=10,
                           taille_voulue=1.0)["motif"] == M.SANS_CARNET
    assert M.sonder_un_cas(carnet=CARNET, trades=[_trade(1, 97.0, 9.0)], prix_passif=97.0,
                           cote=M.ACHAT, debut_ms=0, horizon_ms=10,
                           taille_voulue=1.0)["motif"] == M.SANS_NIVEAU


# ------------------------------------------------------------------ l'agregation

def test_les_non_mesurables_n_entrent_dans_AUCUN_numerateur():
    cas = [{"verdict": M.REMPLI}, {"verdict": M.NON_REMPLI},
           {"verdict": M.NON_MESURABLE, "motif": M.SANS_CARNET},
           {"verdict": M.NON_MESURABLE, "motif": M.SANS_TRADES}]
    r = M.taux_de_remplissage(cas)
    assert r["taux"] == 0.5                       # 1 / 2, pas 1 / 4
    assert r["jugeables"] == 2 and r["non_mesurables"] == 2
    assert r["par_motif"] == {M.SANS_CARNET: 1, M.SANS_TRADES: 1}


def test_aucun_cas_jugeable_rend_un_taux_NUL_et_non_zero():
    """None = « on ne sait pas ». 0.0 dirait « jamais rempli », ce qui est une affirmation."""
    r = M.taux_de_remplissage([{"verdict": M.NON_MESURABLE, "motif": M.SANS_CARNET}])
    assert r["taux"] is None and r["mesurable"] is False


def test_la_lecture_REFUSE_de_conclure_sur_trop_peu_de_cas():
    petit = M.taux_de_remplissage([{"verdict": M.REMPLI}] * 3)
    assert "ATTENTION" in M.lecture(petit, minimum_jugeables=30)
    grand = M.taux_de_remplissage([{"verdict": M.REMPLI}] * 40)
    assert "ATTENTION" not in M.lecture(grand, minimum_jugeables=30)
    vide = M.taux_de_remplissage([])
    assert "NON MESURABLE" in M.lecture(vide)


def test_CANARI_aucune_valeur_de_remplissage_ni_de_spread_EN_DUR():
    """La regle n'est pas « ne jamais passer fill_rate » — on le passe desormais, MESURE. La regle
    est : **aucune valeur numerique en dur**. L'appel historique ecrivait `spread_saving_usd=0.20`
    et un `fill_rate` devine ; c'est exactement ce que ce module supprime. Un defaut numerique
    reintroduirait l'hypothese par la petite porte."""
    import ast
    import inspect

    arbre = ast.parse(inspect.getsource(M))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        for mot in noeud.keywords:
            if mot.arg in ("fill_rate", "spread_saving_usd"):
                assert not isinstance(mot.value, ast.Constant), (
                    f"{mot.arg} recoit une CONSTANTE en dur : l'hypothese revient")
    # et aucun parametre de fonction du module ne doit avoir un tel defaut chiffre
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef):
            noms = [a.arg for a in noeud.args.args + noeud.args.kwonlyargs]
            defauts = list(noeud.args.defaults) + [d for d in noeud.args.kw_defaults if d]
            for nom, defaut in zip(noms[-len(defauts):] if defauts else [], defauts):
                if nom in ("taux", "fill_rate", "economie_usd", "spread_saving_usd"):
                    assert not (isinstance(defaut, ast.Constant)
                                and isinstance(defaut.value, (int, float))), (
                        f"{noeud.name}: {nom} a un defaut chiffre")



def test_les_VRAIS_champs_des_rubans_sont_reconnus():
    """BUG MESURE LE 14/11 : les rubans de trades portent `received_at_ms` / `exchange_ts_ms` et
    `price` / `size`, PAS `ts_ms` / `px` / `sz`. Ne chercher que `ts_ms` revenait a ignorer
    SILENCIEUSEMENT 100 % des trades d'un ruban de 3,7 Go, et a conclure « aucun trade observe ».
    Un filtre qui ne reconnait pas ses donnees ne dit pas « rien », il dit n'importe quoi."""
    reel = [{"coin": "ETH", "exchange_ts_ms": 1000, "received_at_ms": 1010,
             "price": 99.5, "size": 12.0, "aggressor_side": "SELL"}]
    volume, vus = M.volume_consommateur(reel, prix=100.0, cote=M.ACHAT,
                                        debut_ms=0, fin_ms=2000)
    assert vus == 1 and volume == 12.0


def test_la_RECEPTION_prime_sur_l_heure_d_echange():
    """Choix canonique du projet : l'instant ou nous AURIONS PU agir, pas celui de la venue."""
    trade = [{"exchange_ts_ms": 10, "received_at_ms": 5000, "price": 99.0, "size": 1.0}]
    dans_la_reception, _ = M.volume_consommateur(trade, prix=100.0, cote=M.ACHAT,
                                                 debut_ms=4000, fin_ms=6000)
    hors_reception, _ = M.volume_consommateur(trade, prix=100.0, cote=M.ACHAT,
                                              debut_ms=0, fin_ms=100)
    assert dans_la_reception == 1.0 and hors_reception == 0.0


# ------------------------------------------------------------------ l'economie de spread

def test_l_economie_maker_est_le_DEMI_spread_mesure():
    """L'appel historique utilisait `spread_saving_usd=0.20` EN DUR — une constante qui ne
    correspond a aucun marche, et qui surestime massivement le gain sur un coin a spread serre."""
    # bid 100, ask 101 -> mid 100.5, demi-spread 0.5 -> 0.497 % du notionnel
    gain = M.economie_de_spread(CARNET, notionnel=1000.0)
    assert gain is not None
    assert abs(gain - (0.5 / 100.5) * 1000.0) < 1e-9


def test_un_carnet_incoherent_ne_rend_PAS_une_valeur_par_defaut():
    """Un spread nul ou croise ne doit pas devenir « 0,20 $ » par commodite."""
    for carnet in ({"bids5": [[100.0, 1.0]], "asks5": [[100.0, 1.0]]},   # spread nul
                   {"bids5": [[101.0, 1.0]], "asks5": [[100.0, 1.0]]},   # croise
                   {"bids5": [], "asks5": [[101.0, 1.0]]}):
        assert M.economie_de_spread(carnet, notionnel=1000.0) is None
    assert M.economie_de_spread(CARNET, notionnel=0.0) is None


# ------------------------------------------------------------------ l'encadrement

def test_sans_mesure_l_encadrement_REFUSE_de_calculer():
    """C'est tout l'objet du module : supprimer les deux hypotheses, pas les deplacer."""
    r = M.encadrement_maker([1.0, -1.0], taux=None, economie_usd=0.5)
    assert r["mesurable"] is False and r["raison"] == "TAUX_OU_ECONOMIE_NON_MESURES"
    assert M.encadrement_maker([1.0], taux=0.5, economie_usd=None)["mesurable"] is False


def test_la_borne_BASSE_est_toujours_pire_que_la_HAUTE():
    """`adverse=True` garde les PIRES trades : les gagnants filent avant que le passif soit
    touche. L'appel historique n'utilisait QUE `adverse=False`, la version flatteuse."""
    trades = [5.0, 3.0, -1.0, -4.0, 2.0, -2.0, 1.0, -3.0]
    r = M.encadrement_maker(trades, taux=0.5, economie_usd=0.1)
    assert r["mesurable"] is True
    assert r["basse"]["somme"] <= r["haute"]["somme"]


def test_le_verdict_distingue_les_TROIS_cas():
    gagnants = M.encadrement_maker([10.0] * 6, taux=0.5, economie_usd=0.1)
    assert gagnants["verdict"] == "POSITIF_MEME_AU_PIRE"
    perdants = M.encadrement_maker([-10.0] * 6, taux=0.5, economie_usd=0.1)
    assert perdants["verdict"] == "NEGATIF_DANS_LES_DEUX_CAS"


def test_l_instant_de_remplissage_est_celui_du_FRANCHISSEMENT():
    """Le markout se mesure A PARTIR DU FILL. Le mesurer depuis le depot de l'ordre melangerait
    l'attente — pendant laquelle on ne porte AUCUN risque — avec la derive post-remplissage, et
    ferait paraitre toxique un ordre simplement reste longtemps dans le carnet."""
    trades = [_trade(10, 100.0, 2.0), _trade(20, 100.0, 2.0), _trade(30, 100.0, 5.0)]
    # file devant = 5, taille voulue = 1 -> besoin 6 -> franchi au 3e trade (cumul 9)
    r = M.sonder_un_cas(carnet=CARNET, trades=trades, prix_passif=100.0, cote=M.ACHAT,
                        debut_ms=0, horizon_ms=1000, taille_voulue=1.0)
    assert r["verdict"] == M.REMPLI
    assert r["instant_remplissage_ms"] == 30


def test_un_cas_NON_REMPLI_n_a_pas_d_instant():
    r = M.sonder_un_cas(carnet=CARNET, trades=[_trade(10, 100.0, 1.0)], prix_passif=100.0,
                        cote=M.ACHAT, debut_ms=0, horizon_ms=1000, taille_voulue=1.0)
    assert r["verdict"] == M.NON_REMPLI and r["instant_remplissage_ms"] is None


def test_la_PREMIERE_place_ne_doit_consommer_QUE_notre_taille():
    """LE levier qui retourne le signe : sur le perp BTC d'Hyperliquid a 5 s, le remplissage maker
    moyen marque -0,48 bp mais la PREMIERE PLACE +0,32 bp — un ecart de ~0,8 bp. Comparer les deux
    bras est l'experience qui dit si le signe negatif vient du fait de coter au touch, ou seulement
    d'y coter EN DERNIER."""
    trades = [_trade(10, 100.0, 1.5)]          # 1.5 consomme : insuffisant en dernier, assez devant
    dernier = M.sonder_un_cas(carnet=CARNET, trades=trades, prix_passif=100.0, cote=M.ACHAT,
                              debut_ms=0, horizon_ms=1000, taille_voulue=1.0, place=M.DERNIER)
    premier = M.sonder_un_cas(carnet=CARNET, trades=trades, prix_passif=100.0, cote=M.ACHAT,
                              debut_ms=0, horizon_ms=1000, taille_voulue=1.0, place=M.PREMIER)
    assert dernier["verdict"] == M.NON_REMPLI       # besoin 5 + 1 = 6 > 1.5
    assert premier["verdict"] == M.REMPLI          # besoin 0 + 1 = 1 <= 1.5
    assert premier["place"] == M.PREMIER


def test_le_defaut_reste_le_PIRE_cas():
    """Un defaut optimiste transformerait chaque oubli d'argument en edge imaginaire."""
    import inspect
    signature = inspect.signature(M.sonder_un_cas)
    assert signature.parameters["place"].default == M.DERNIER
