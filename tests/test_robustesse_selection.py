"""ROBUSTESSE DE SÉLECTION (PBO / CSCV) — ce qui rend la recherche EXTRÊME sûre. On VERROUILLE :
un vrai gagnant (bon sur tous les blocs) → PBO≈0 ROBUSTE ; du bruit (chaque config brille sur UN
bloc) → PBO élevé SUR_AJUSTE ; données maigres → INSUFFISANT (jamais un faux 0). Aucun réseau."""
from __future__ import annotations

from hl_observer.backtesting import robustesse_selection as R


def test_un_vrai_gagnant_bon_sur_TOUS_les_blocs_a_un_PBO_bas():
    M = [[1.0] * 8, [0.0] * 8, [0.0] * 8, [0.0] * 8]   # config 0 domine partout
    r = R.pbo_cscv(M)
    assert r["pbo"] is not None and r["pbo"] < 0.10
    assert r["verdict"] == "ROBUSTE" and r["n_blocs"] == 8


def test_du_BRUIT_chaque_config_brille_sur_UN_bloc_a_un_PBO_eleve():
    # M[i][b] = 1 si i==b : la meilleure EN IS a justement son pic DANS l'IS -> nulle en OOS.
    M = [[1.0 if i == b else 0.0 for b in range(8)] for i in range(8)]
    r = R.pbo_cscv(M)
    assert r["pbo"] is not None and r["pbo"] > 0.5
    assert r["verdict"] == "SUR_AJUSTE"


def test_donnees_maigres_INSUFFISANT_jamais_un_faux_zero():
    assert R.pbo_cscv([[1.0, 2.0, 3.0, 4.0]])["pbo"] is None        # 1 seule config
    assert R.pbo_cscv([[1.0, 2.0], [3.0, 4.0]])["pbo"] is None      # 2 blocs (< 4)
    assert "INSUFFISANT" in R.pbo_cscv([])["verdict"]


def test_le_seuil_de_bruit_grandit_avec_le_nombre_d_essais():
    peu = R.seuil_bruit_multiple_testing(10, 1.0)
    beaucoup = R.seuil_bruit_multiple_testing(2000, 1.0)
    assert 0.0 < peu < beaucoup                       # plus d'essais -> barre plus haute
    assert R.seuil_bruit_multiple_testing(1, 1.0) == R.seuil_bruit_multiple_testing(2, 1.0)


def test_verdict_combine_un_gagnant_qui_ne_bat_pas_le_bruit_n_est_PAS_robuste():
    genuine = [[1.0] * 8, [0.0] * 8, [0.0] * 8]
    # PBO bas MAIS le net du gagnant (1,0) est sous le seuil de bruit de 500 essais (~3,5σ)
    r = R.verdict_robustesse(genuine, 500, net_gagnant=1.0, sigma_null=1.0)
    assert r["bat_le_bruit"] is False and r["robuste"] is False and r["verdict"] == "SUR_AJUSTE"
    # le MÊME gagnant avec un net franc (10) passe les deux tests
    r2 = R.verdict_robustesse(genuine, 500, net_gagnant=10.0, sigma_null=1.0)
    assert r2["robuste"] is True and r2["verdict"] == "ROBUSTE"


def test_verdict_deny_by_default_sur_matrice_insuffisante():
    r = R.verdict_robustesse([[1.0] * 8], 100, net_gagnant=10.0, sigma_null=1.0)
    assert r["robuste"] is False and r["verdict"] == "INSUFFISANT"


def test_le_bruit_reste_sur_ajuste_meme_avec_un_gros_net():
    M = [[1.0 if i == b else 0.0 for b in range(8)] for i in range(8)]
    r = R.verdict_robustesse(M, 50, net_gagnant=999.0, sigma_null=1.0)
    assert r["robuste"] is False            # un gros net ne sauve pas une procedure qui sur-ajuste
