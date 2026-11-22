"""Famille V (dépôt dans les vaults) : la mesure du déposant, gardée AVANT d'être lue.

Chaque test tient une erreur qui fabriquerait un rendement : lire au-delà du verrou, prendre un
point postérieur à la borne, compter un dépôt comme un gain, perdre la perte finale d'un vault
fermé, choisir un vault sur une information future, oublier la part du leader, ignorer les
vaults dont on ne connaît pas l'issue.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import goal2_commun as G  # noqa: E402
import goal2_depot_vaults as D  # noqa: E402
import goal2_vaults_matrice as M  # noqa: E402

P = M.SEMAINE_MS            # la periode de la grille (28 jours)
K0 = 700                    # une borne quelconque, loin du verrou
H = 3_600_000


def _pt(k: float, valeur, pnl, avance_h: float = 2.0):
    """Un point publie `avance_h` heures AVANT la borne k (comme les vrais points)."""
    return (int(k * P) - int(avance_h * H), valeur, pnl)


# ---------------------------------------------------------------- matrice
def test_rien_au_dela_du_verrou_n_entre_dans_la_matrice() -> None:
    assert M.BORNE_MS == G.SEGMENTS["execution"][0]
    courbe = [(M.BORNE_MS - 5, 1.0, 0.0), (M.BORNE_MS, 2.0, 0.0), (M.BORNE_MS + P, 3.0, 0.0)]
    assert [p[1] for p in M.tronquer(courbe)] == [1.0]


def test_la_valeur_a_une_borne_n_est_jamais_posterieure_ni_perimee() -> None:
    ts = np.array([K0 * P - 2 * H, K0 * P + 1 * H, (K0 + 1) * P - 9 * 24 * H], dtype=np.int64)
    val = np.array([100.0, 999.0, 50.0])
    bornes = np.array([K0 * P, (K0 + 1) * P], dtype=np.int64)
    v = M.aux_bornes(ts, val, bornes)
    assert v[0] == 100.0                      # le point de +1 h existe, mais il est APRES la borne
    assert np.isnan(v[1])                     # le dernier point connu a 9 jours : perime, pas prolonge


def _matrice(courbes: dict) -> dict:
    return M.construire(courbes)


def test_un_depot_n_est_pas_un_gain_et_une_cloture_garde_la_perte_reelle() -> None:
    m = _matrice({
        "stable": [_pt(K0, 100_000, 0), _pt(K0 + 1, 101_000, 1_000), _pt(K0 + 2, 102_000, 2_000)],
        "depot": [_pt(K0, 100_000, 0), _pt(K0 + 1, 203_000, 3_000), _pt(K0 + 2, 203_000, 3_000)],
        "ferme": [_pt(K0, 100_000, 0), _pt(K0 + 1, 0.0, -20_000), _pt(K0 + 2, 0.0, -20_000)],
    })
    i = {v: n for n, v in enumerate(m["vaults"])}
    assert m["ret"][i["stable"], 0] == pytest.approx(0.01, rel=1e-3)
    # 3 000 de gain, 100 000 deposes en cours de periode : capital moyen 150 000 -> 2 %, pas 103 %
    assert m["ret"][i["depot"], 0] == pytest.approx(0.02)
    # ferme apres -20 000 sur 100 000 : -20 % (Dietz aurait dit -33 %)
    assert m["ret"][i["ferme"], 0] == pytest.approx(-0.20) and m["cloture"][i["ferme"], 0]
    assert np.isnan(m["ret"][i["ferme"], 1])             # un vault vide n'a plus de rendement
    assert not m["cloture"][i["stable"]].any()


def test_hors_cloture_la_matrice_egale_le_module_du_depot() -> None:
    from hl_observer.backtesting.copy_vault_persistence import PersistenceConfig, period_returns

    rng = np.random.default_rng(7)
    courbe, valeur, pnl = [], 50_000.0, 0.0
    for k in range(K0, K0 + 12):
        courbe.append(_pt(k, valeur, pnl))
        gain, flux = rng.normal(0, 800), rng.normal(0, 3_000)
        pnl += gain
        valeur += gain + flux
    m = _matrice({"v": courbe})
    reference = period_returns(courbe, period_days=28,
                               config=PersistenceConfig(min_capital_usd=1e-9, stale_fraction=7.5 / 28))
    assert len(reference) == 10                        # le module s'arrete une borne plus tot
    position = {int(k): j for j, k in enumerate(m["semaines"])}
    for k, cellule in reference.items():
        assert m["ret"][0, position[k]] == pytest.approx(cellule["ret"], rel=1e-9)
    # ... et la matrice connait en plus la derniere periode, close par un point publie 2 h avant sa borne
    assert len(m["semaines"]) == 11 and np.isfinite(m["ret"][0, -1])


# ---------------------------------------------------------------- strategies
def _poids(valeurs, passe, ages):
    return D.poids_des_strategies(np.array(valeurs, float), np.array(passe, float), np.array(ages, float),
                                  seuil_usd=10_000.0)


def test_l_eligibilite_se_juge_sur_la_valeur_de_debut() -> None:
    passe = np.zeros((12, D.HISTORIQUE))
    valeurs = [50_000.0] * 10 + [9_999.0, np.nan]
    w = _poids(valeurs, passe, [100.0] * 12)
    assert (w["V0"][:10] > 0).all() and w["V0"][10] == 0 and w["V0"][11] == 0
    assert w["V0"].sum() == pytest.approx(1.0) and w["V1"].sum() == pytest.approx(1.0)


def test_la_qualite_prend_les_anciens_gros_et_calmes_le_temoin_l_inverse() -> None:
    n = 20
    ages = np.linspace(30, 900, n)                    # le vault 19 est le plus ancien
    valeurs = np.linspace(20_000, 2_000_000, n)       # ... et le plus gros
    alternance = np.array([1.0, -1.0] * (D.HISTORIQUE // 2))
    passe = np.array([(0.20 - 0.009 * i) * alternance for i in range(n)])   # ... et le plus calme, exactement
    w = _poids(valeurs, passe, ages)
    assert set(np.flatnonzero(w["V2"])) == {16, 17, 18, 19}
    assert set(np.flatnonzero(w["V3"])) == {0, 1, 2, 3}
    assert w["V2"].sum() == pytest.approx(1.0) and w["V0h"].sum() == pytest.approx(1.0)


def test_un_vault_sans_historique_complet_n_entre_pas_dans_la_selection() -> None:
    passe = np.random.default_rng(1).normal(0, 0.05, (12, D.HISTORIQUE))
    passe[0, 2] = np.nan                               # une periode inconnue dans son historique
    w = _poids([1e6] * 12, passe, [999.0] + [100.0] * 11)
    assert w["V0"][0] > 0                              # il reste dans le panier general
    assert w["V0h"][0] == 0 and w["V2"][0] == 0 and w["V4"][0] == 0


def test_la_part_du_leader_ne_frappe_que_les_gains() -> None:
    net = D.net_du_deposant(np.array([0.10, -0.10, 0.0]))
    assert net == pytest.approx([0.09, -0.10, 0.0])


def test_un_vault_retenu_dont_l_issue_est_inconnue_est_compte_et_coute_au_pire_cas() -> None:
    poids = np.array([0.5, 0.5, 0.0])
    r = np.array([0.10, np.nan, 0.50])
    brut, net, inconnus = D.rendement_du_panier(poids, r)
    assert inconnus == 1 and brut == pytest.approx(0.10) and net == pytest.approx(0.09)
    brut_p, net_p, _ = D.rendement_du_panier(poids, r, pessimiste=True)
    assert brut_p == pytest.approx(0.5 * 0.10 + 0.5 * -1.0) and net_p == pytest.approx(0.5 * 0.09 - 0.5)


def test_repli_maximal_et_alpha_beta() -> None:
    assert D.repli_maximal(np.array([0.10, -0.50, 0.10])) == pytest.approx(-0.50)
    b = np.random.default_rng(5).normal(0, 0.1, 60)
    ab = D.alpha_beta(0.01 + 0.5 * b, b)
    assert ab["alpha"] == pytest.approx(0.01, abs=1e-9) and ab["beta"] == pytest.approx(0.5, abs=1e-9)


def test_la_validation_ne_se_lit_pas_sans_strategie_figee(monkeypatch, capsys) -> None:
    def _interdit(*_a, **_k):
        raise AssertionError("la matrice a ete lue alors que la validation devait etre refusee")

    monkeypatch.setattr(M, "matrice", _interdit)
    assert D.main(["--segment", "validation"]) == 2
    assert D.main(["--segment", "validation", "--strategie-figee", "V0", "--sans-registre"]) == 2
    assert "REFUS" in capsys.readouterr().err


@pytest.mark.parametrize("critere", ["anciennete", "taille", "calme"])
def test_chaque_critere_de_qualite_joue_dans_le_bon_sens(critere) -> None:
    """Un seul critère varie à la fois : sinon un signe inversé passerait inaperçu."""
    n = 20
    alternance = np.array([1.0, -1.0] * (D.HISTORIQUE // 2))
    ages, valeurs = np.full(n, 300.0), np.full(n, 100_000.0)
    passe = np.array([0.05 * alternance for _ in range(n)])
    if critere == "anciennete":
        ages = np.linspace(30, 900, n)
    elif critere == "taille":
        valeurs = np.linspace(20_000, 2_000_000, n)
    else:
        passe = np.array([(0.20 - 0.009 * i) * alternance for i in range(n)])
    w = D.poids_des_strategies(valeurs, passe, ages, seuil_usd=10_000.0)
    assert set(np.flatnonzero(w["V2"])) == {16, 17, 18, 19}, critere
    assert set(np.flatnonzero(w["V3"])) == {0, 1, 2, 3}, critere


def test_les_extremes_persistants_prennent_le_meilleur_sharpe_passe() -> None:
    n = 20
    alternance = np.array([1.0, -1.0] * (D.HISTORIQUE // 2))
    passe = np.array([0.001 * i + 0.05 * alternance for i in range(n)])     # moyenne croissante, meme dispersion
    w = D.poids_des_strategies(np.full(n, 100_000.0), passe, np.full(n, 300.0), seuil_usd=10_000.0)
    assert set(np.flatnonzero(w["V4"])) == {18, 19}


# ---------------------------------------------------------------- HLP (V5)
def _reponse_hlp(bornes_k, valeurs, pnls) -> dict:
    pts_v = [[int(k * P) - 2 * H, str(v)] for k, v in zip(bornes_k, valeurs)]
    pts_p = [[int(k * P) - 2 * H, str(x)] for k, x in zip(bornes_k, pnls)]
    return {"portfolio": [["allTime", {"accountValueHistory": pts_v, "pnlHistory": pts_p, "vlm": "0"}]]}


def test_la_courbe_hlp_passe_par_le_lecteur_du_depot() -> None:
    import goal2_hlp as HLP

    c = HLP.courbe(_reponse_hlp([K0, K0 + 1, K0 + 2], [1e6, 1.01e6, 1.02e6], [0, 1e4, 2e4]))
    assert [round(p[1]) for p in c] == [1_000_000, 1_010_000, 1_020_000]
    assert [round(p[2]) for p in c] == [0, 10_000, 20_000]
    m = M.construire({HLP.HLP: c})
    assert m["ret"][0] == pytest.approx([0.01, 1e4 / 1.01e6], rel=1e-6)


def test_le_prospectif_ne_compte_que_les_periodes_commencees_apres_le_gel(capsys) -> None:
    import goal2_hlp as HLP

    k = HLP.PROSPECTIF_K
    assert k * P >= HLP.GEL_MS > (k - 1) * P                 # la premiere borne APRES le gel
    # trois points : un AVANT le gel (gain enorme, doit etre ignore), deux apres
    c = HLP.courbe(_reponse_hlp([k - 1, k, k + 1], [1e6, 2e6, 2.02e6], [0, 1e6, 1.02e6]))
    assert HLP.prospectif(c, enregistrer=False) == 0
    sortie = capsys.readouterr().out
    assert "periodes closes : 1 " in sortie and "MORE_DATA" in sortie      # 1 periode, pas 2 ; pas de verdict


def test_sans_cache_ni_lecture_hlp_est_refuse(tmp_path, monkeypatch) -> None:
    import goal2_hlp as HLP

    monkeypatch.setattr(HLP, "BRUT", tmp_path / "absent.json")
    assert HLP.main(["--sans-registre"]) == 2
    assert HLP.main(["--segment", "validation", "--sans-registre"]) == 2


def test_quatre_periodes_prospectives_gagnantes_ne_font_pas_une_preuve(capsys) -> None:
    """Sous le minimum pré-enregistré (6 périodes), aucun verdict — même si tout est positif."""
    import goal2_hlp as HLP

    k = HLP.PROSPECTIF_K
    bornes = [k + i for i in range(5)]
    c = HLP.courbe(_reponse_hlp(bornes, [1e6 * 1.02 ** i for i in range(5)],
                                [1e6 * (1.02 ** i - 1) for i in range(5)]))
    HLP.prospectif(c, enregistrer=False)
    sortie = capsys.readouterr().out
    assert "periodes closes : 4 " in sortie and "MORE_DATA" in sortie and "PROVEN" not in sortie


# ---------------------------------------------------------------- depot papier HLP
def test_le_depot_papier_entre_au_dernier_point_connu_jamais_dans_le_passe() -> None:
    import goal2_hlp as HLP

    lignes = HLP.marquer([(1000, 5e8, 1e7), (2000, 5.1e8, 1.2e7), (3000, None, 1.3e7)], None)
    assert len(lignes) == 1 and lignes[0]["type"] == "DEPOT"
    assert lignes[0]["ts_ms"] == 2000 and lignes[0]["capital_usd"] == 100.0      # le point incomplet est ignore


def test_une_marque_ne_lit_que_les_points_posterieurs_et_un_depot_d_autrui_n_est_pas_un_gain() -> None:
    import goal2_hlp as HLP

    depot = {"ts_ms": 2000, "valeur_vault": 1_000_000.0, "pnl_vault": 0.0, "capital_usd": 100.0}
    points = [(1000, 9e5, -5e4),                 # ANTERIEUR au depot : ne doit rien changer
              (2000, 1_000_000.0, 0.0),          # le point du depot lui-meme
              (3000, 1_010_000.0, 10_000.0),     # +1 % de gain, aucun flux
              (4000, 2_010_000.0, 10_000.0)]     # 1 000 000 deposes par d'autres : gain nul
    lignes = HLP.marquer(points, depot)
    assert [x["ts_ms"] for x in lignes] == [3000, 4000]
    assert lignes[0]["capital_usd"] == pytest.approx(101.0)
    assert lignes[1]["capital_usd"] == pytest.approx(101.0)
    assert HLP.marquer(points, lignes[-1]) == []                                  # rien de nouveau : rien d'ecrit
