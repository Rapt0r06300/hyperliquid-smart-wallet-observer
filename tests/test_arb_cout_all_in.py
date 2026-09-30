"""LE COÛT ALL-IN DE L'ARBITRAGE — le forfait qui décidait de tout (P4-2/P4-3, 21/07).

`COUT_AR_BPS = 8.0` était commenté « 2 exécutions HL maker + spread/slippage ~5 ». Un
aller-retour d'arbitrage, c'est **4** exécutions, et le commentaire oubliait les frais de la
seconde venue. Re-pricing des 4 trades réels : +0,0929 $ à 8 bps → **−0,0671 $ à 16 bps**.
Tout le PnL positif tenait dans l'incertitude d'une constante jamais mesurée.
"""
from __future__ import annotations

import pytest

from hl_observer.funding import arb_cout_all_in as c


def test_un_aller_retour_compte_QUATRE_executions_pas_deux():
    """L'erreur d'origine, verrouillée : ouverture ET fermeture, sur CHACUNE des deux venues."""
    d = c.decomposer()
    assert d["executions"] == 4
    assert d["maker"] + d["taker"] == 4
    assert set(d["jambes"]) == {"hl_entree", "hl_sortie", "bin_entree", "bin_sortie"}


def test_les_frais_des_DEUX_venues_sont_comptes():
    d = c.decomposer(mode=c.MODE_TOUT_MAKER)
    assert d["frais_bps"] == pytest.approx(2 * 1.5 + 2 * 2.0)   # 7,0 et non 3,0
    venues = {j["venue"] for j in d["frais_par_jambe"].values()}
    assert venues == {"HL", "BINANCE"}, "oublier une venue, c'est diviser le cout par deux"


def test_le_mode_par_defaut_est_le_CONSERVATEUR():
    """Deny-by-default s'applique aux HYPOTHÈSES comme aux données. 8 bps ne tenait que si les
    4 fills étaient passifs — sur un trade de convergence, c'est-à-dire une course."""
    assert c.MODE_REALISTE == "REALISTE"
    j = c.modes_par_jambe()
    assert j["hl_entree"] == "maker", "on peut attendre pour poser la jambe qu'on choisit"
    assert j["bin_entree"] == "taker", "la couverture doit se completer, sinon on est a nu"


def test_les_trois_modes_sont_ordonnes():
    m = [c.decomposer(mode=x)["cout_aller_retour_bps"]
         for x in (c.MODE_TOUT_MAKER, c.MODE_REALISTE, c.MODE_TOUT_TAKER)]
    assert m[0] < m[1] < m[2]
    assert m == pytest.approx([9.0, 16.0, 23.0])


def test_aucun_poste_de_cout_n_est_fabrique_a_zero():
    """Un zéro fabriqué sur un poste de coût ment toujours dans le sens qui arrange."""
    d = c.decomposer()
    assert d["slippage_bps"] is None and d["slippage_mesure"] is False
    assert "slippage" in d["postes_non_mesures"] and "spread" in d["postes_non_mesures"]
    assert d["spread_bps"] > 0, "sans mesure, une PROVISION explicite — jamais zero"


def test_un_spread_mesure_remplace_la_provision():
    d = c.decomposer(spread_hl_bps=0.4, spread_bin_bps=6.0)
    assert d["spread_mesure"] is True
    # mode REALISTE : seules les 2 jambes Binance sont taker -> 2 x 6,0
    assert d["spread_bps"] == pytest.approx(12.0)
    assert "spread" not in d["postes_non_mesures"]


def test_le_seuil_SUIT_son_cout_au_lieu_d_etre_une_constante():
    """`SEUIL_OUVERTURE_BPS = 15` ne bougeait pas quand le coût bougeait. Un seuil qui ignore
    son coût n'est pas un seuil, c'est une habitude."""
    for mode in (c.MODE_TOUT_MAKER, c.MODE_REALISTE, c.MODE_TOUT_TAKER):
        cout = c.decomposer(mode=mode)["cout_aller_retour_bps"]
        assert c.seuil_dynamique_bps(mode=mode) == pytest.approx(cout + c.MARGE_EXIGEE_BPS)


def test_un_ecart_sous_le_cout_est_refuse_et_dit_ce_qui_manque():
    v = c.verdict(ecart_bps=12.0)
    assert v["autorise"] is False
    assert v["motif"] == "ARB_ECART_SOUS_LE_COUT_ALL_IN_NO_TRADE"
    assert v["manque_bps"] == pytest.approx(7.0)      # seuil 19 − 12
    assert v["marge_nette_bps"] < 0


def test_un_ecart_qui_couvre_tout_passe():
    v = c.verdict(ecart_bps=-25.0)                    # le SIGNE ne change rien à la rentabilité
    assert v["autorise"] is True and v["motif"] == ""
    assert v["marge_nette_bps"] == pytest.approx(9.0)


def test_un_ecart_absent_ne_se_compare_a_rien():
    for e in (None, float("nan"), "20", True):
        assert c.verdict(ecart_bps=e)["autorise"] is False


# ─────────────────── le re-pricing : le résultat survit-il à un coût honnête ? ───────────────────

TRADES_REELS = [
    {"coin": "AAVE", "ecart_entree_bps": -16.44, "ecart_sortie_bps": 2.30},
    {"coin": "RUNE", "ecart_entree_bps": 15.35, "ecart_sortie_bps": 0.22},
    {"coin": "MKR", "ecart_entree_bps": 71.44, "ecart_sortie_bps": 71.44},
    {"coin": "RUNE", "ecart_entree_bps": 15.46, "ecart_sortie_bps": -1.26},
]


def test_le_PnL_de_l_arbitrage_MEURT_avec_un_cout_honnete():
    """LE test. Les 4 trades réels étaient +0,0929 $ sous le forfait de 8 bps. Sous
    l'hypothèse d'exécution réaliste, ils passent en négatif. Le résultat positif était un
    artefact du coût, pas un edge."""
    optimiste = c.repricer(TRADES_REELS, mode=c.MODE_TOUT_MAKER)
    realiste = c.repricer(TRADES_REELS, mode=c.MODE_REALISTE)
    assert optimiste["survit"] is True and optimiste["total_usd"] > 0
    assert realiste["survit"] is False and realiste["total_usd"] < 0
    assert realiste["gagnants"] < optimiste["gagnants"]


def test_le_repricing_traite_le_franchissement_de_zero():
    """AAVE est entré à −16,44 et sorti à +2,30 : l'écart a traversé zéro DANS notre sens.
    La capture vaut alors la somme des valeurs absolues, pas leur différence."""
    r = c.repricer([TRADES_REELS[0]], mode=c.MODE_TOUT_MAKER)
    assert r["lignes"][0]["capture_bps"] == pytest.approx(18.74)


def test_un_trade_sans_ecart_de_sortie_est_ignore_pas_devine():
    r = c.repricer([{"coin": "X", "ecart_entree_bps": 30.0}, "pas un dict", None])
    assert r["trades"] == 0


def test_aucune_execution_reelle():
    assert c.decomposer()["real_execution"] is False
    assert c.verdict(ecart_bps=50.0)["real_execution"] is False


# ─────────────────── un écart figé n'est pas une dislocation ───────────────────

def test_un_ecart_parfaitement_immobile_est_refuse():
    """MKR : 71,44 bps sur **208 observations, écart-type 0,0000** — min = max, jamais un
    mouvement. C'était le plus gros écart de l'univers, donc le seul à franchir le seuil,
    et il a perdu. Un vrai écart de dislocation FLUCTUE : c'est ce qui le rend capturable."""
    v = c.ecart_vivant([71.4431] * 208)
    assert v["vivant"] is False and v["motif"] == c.MOTIF_FIGE
    assert v["ecart_type_bps"] == pytest.approx(0.0)
    assert v["amplitude_bps"] == pytest.approx(0.0)


def test_un_ecart_qui_fluctue_passe():
    v = c.ecart_vivant([8.2, -9.66, 16.31, 3.4, -2.1] * 8)
    assert v["vivant"] is True and v["motif"] == ""
    assert v["ecart_type_bps"] > c.ECART_TYPE_MIN_BPS


def test_trop_peu_d_observations_ne_CONDAMNE_pas():
    """Un écart-type sur 3 points ne dit rien. `None` = on s'abstient de juger — on ne
    condamne pas un coin sur une mesure qui n'existe pas."""
    for h in (None, [], [71.44], [71.44] * 5):
        v = c.ecart_vivant(h)
        assert v["vivant"] is None and v["motif"] == ""


def test_les_valeurs_illisibles_sont_ignorees_pas_comptees_a_zero():
    v = c.ecart_vivant([5.0, "x", None, -3.0, True, 7.0] * 10)
    assert v["observations"] == 30, "seuls les nombres comptent ; un 0 fabrique fausserait sigma"


def test_le_moteur_refuse_bien_un_coin_fige_bout_en_bout(tmp_path, monkeypatch):
    """« mention ≠ porte ». Le coin figé doit être refusé PAR LE TICK, avant le seuil —
    un écart figé est d'autant plus gros qu'il est faux, il passerait tous les seuils."""
    import json
    import time

    from hl_observer.funding import arb_dislocation_paper as p
    t = time.time()
    d = tmp_path / p.VENUES_RELPATH
    d.parent.mkdir(parents=True, exist_ok=True)
    lignes = [json.dumps({"ts": t - i * 60, "coin": "MKR", "ecart_prix_bps": 71.4431,
                          "hl_px": 1.0, "bin_px": 1.0}) for i in range(60)]
    d.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    evts = p.tick(tmp_path, now=t, session_id="TEST")
    assert not [e for e in evts if e["type"] == "OPEN"], (
        "un ecart fige a 71 bps ne doit JAMAIS ouvrir, meme trois fois au-dessus du seuil")


def test_le_moteur_ouvre_bien_un_ecart_VIVANT_au_dessus_du_seuil(tmp_path):
    """Le contraste : la porte de vivacité ne doit pas tout tuer."""
    import json
    import time

    from hl_observer.funding import arb_dislocation_paper as p
    t = time.time()
    d = tmp_path / p.VENUES_RELPATH
    d.parent.mkdir(parents=True, exist_ok=True)
    serie = [30.0, 24.0, 33.0, 21.0, 35.0, 27.0]
    lignes = [json.dumps({"ts": t - i * 60, "coin": "RUNE",
                          "ecart_prix_bps": serie[i % len(serie)],
                          "hl_px": 1.0, "bin_px": 1.0}) for i in range(60)]
    # la mesure la PLUS RECENTE doit etre au-dessus du seuil
    lignes[0] = json.dumps({"ts": t - 1, "coin": "RUNE", "ecart_prix_bps": 30.0,
                            "hl_px": 1.0, "bin_px": 1.0})
    d.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    evts = p.tick(tmp_path, now=t, session_id="TEST")
    assert [e for e in evts if e["type"] == "OPEN"], "un ecart vivant a 30 bps doit ouvrir"


# ─────────────────── LE MOTEUR EST-IL BRANCHÉ DESSUS ? ───────────────────

def test_le_moteur_d_arbitrage_utilise_le_cout_decompose():
    """« mention ≠ porte » : le module ne vaut rien si le moteur garde son forfait."""
    from hl_observer.funding import arb_dislocation_paper as p
    assert p.COUT_AR_BPS == pytest.approx(16.0), "le forfait de 8 bps ne doit plus exister"
    assert p.SEUIL_OUVERTURE_BPS == pytest.approx(19.0), "le seuil doit DERIVER du cout"
    assert p.SEUIL_OUVERTURE_BPS > p.COUT_AR_BPS, "ouvrir sous son cout n'a jamais de sens"


def test_le_seuil_de_sortie_reste_sous_le_seuil_d_entree():
    """Hystérésis : sortir au même seuil qu'on entre, c'est du churn garanti."""
    from hl_observer.funding import arb_dislocation_paper as p
    assert p.SEUIL_SORTIE_BPS < p.SEUIL_OUVERTURE_BPS
