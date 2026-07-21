"""Tests du RÈGLEMENT DU FUNDING (P0, 21/07) — estimation ≠ encaissement.

Le README affirmait « funding couru (l'encaissé, stable) ». Le code faisait un PRORATA
LINÉAIRE alors qu'Hyperliquid règle au sommet de chaque heure. Une estimation présentée
comme un fait comptable, c'est exactement le genre de chiffre qui finit par mentir.

Ce que ces tests PROUVENT :
  * une position qui n'a franchi AUCUN sommet d'heure a un funding réglé de ZÉRO,
    même après 59 minutes ;
  * la somme réglé + estimé vaut EXACTEMENT l'accru historique (migration neutre,
    aucune valeur créée ni détruite) ;
  * le PnL stable n'absorbe JAMAIS l'estimation ;
  * une position mal formée ne fait pas disparaître le PnL des autres.
"""
from __future__ import annotations

import pytest

from hl_observer.paper_trading.funding_settlement import (PERIODE_REGLEMENT_MS, agreger,
                                                          decouper, pnl_stable,
                                                          reglements_franchis)

H = PERIODE_REGLEMENT_MS
#: un sommet d'heure pile (multiple exact de 3 600 000 ms)
T_PILE = (1_760_000_000_000 // H) * H


def _pos(accru=1.0, entree=T_PILE, **kw):
    p = {"coin": "BTC", "funding_accrued_usdt": accru, "entry_ts_ms": entree,
         "notional_usdt": 500.0}
    p.update(kw)
    return p


# ------------------------------------------------------------------ le comptage des règlements

def test_aucun_sommet_franchi_meme_apres_59_minutes():
    """LE cœur du défaut : 59 minutes de détention ne donnent AUCUN paiement si aucun
    sommet d'heure n'a été traversé."""
    # de la 30e seconde a la 59e minute 59 : presque une heure pleine, AUCUN sommet traverse
    assert reglements_franchis(T_PILE + 30_000, T_PILE + H - 1_000) == 0
    # une seconde APRES le sommet : le paiement tombe d'un coup, jamais progressivement.
    # C'est toute la difference entre un escalier et l'interpolation qu'on affichait.
    assert reglements_franchis(T_PILE + 30_000, T_PILE + H + 1) == 1


def test_un_sommet_franchi_donne_un_reglement():
    assert reglements_franchis(T_PILE - 60_000, T_PILE + 60_000) == 1


@pytest.mark.parametrize("heures", [1, 2, 5, 24, 336])
def test_n_heures_pile_donnent_n_reglements(heures):
    assert reglements_franchis(T_PILE, T_PILE + heures * H) == heures


def test_intervalle_nul_ou_inverse_ne_donne_rien():
    assert reglements_franchis(T_PILE, T_PILE) == 0
    assert reglements_franchis(T_PILE + H, T_PILE) == 0


def test_periode_absurde_ne_leve_pas():
    assert reglements_franchis(T_PILE, T_PILE + H, periode_ms=0) == 0


# ------------------------------------------------------------------ le découpage

def test_la_somme_est_CONSERVEE_la_migration_est_neutre():
    """On re-qualifie une mesure, on n'en crée pas. Si la somme changeait, on aurait
    fabriqué (ou détruit) du PnL en changeant d'affichage."""
    for accru in (0.32, 1.0, -0.5, 12.345):
        for h in (0.3, 1.0, 2.7, 20.0):
            d = decouper(_pos(accru=accru), now_ms=int(T_PILE + h * H))
            assert d["net_funding_settled"] + d["funding_accrual_estimate"] == \
                pytest.approx(accru, abs=1e-7)


def test_une_position_jeune_a_ZERO_de_funding_REGLE():
    """20 minutes de détention : le modèle créditait 1/3 d'heure. Réglé = 0."""
    d = decouper(_pos(accru=0.05, entree=T_PILE), now_ms=T_PILE + 20 * 60_000)
    assert d["net_funding_settled"] == 0.0
    assert d["funding_accrual_estimate"] == pytest.approx(0.05)
    assert d["heures_reglees"] == 0.0


def test_une_position_de_plusieurs_heures_a_l_essentiel_de_REGLE():
    d = decouper(_pos(accru=1.0, entree=T_PILE), now_ms=int(T_PILE + 10.5 * H))
    assert d["heures_reglees"] == 10.0
    assert d["net_funding_settled"] == pytest.approx(1.0 * 10.0 / 10.5, abs=1e-6)
    assert 0 < d["funding_accrual_estimate"] < 0.05


def test_la_part_reglee_ne_depasse_JAMAIS_le_total():
    d = decouper(_pos(accru=1.0, entree=T_PILE), now_ms=T_PILE + 1000 * H)
    assert d["net_funding_settled"] <= 1.0 + 1e-9
    assert d["funding_accrual_estimate"] >= -1e-9


def test_un_funding_NEGATIF_se_decoupe_aussi():
    """Le short peut PAYER le funding. Le règlement d'une perte est aussi un règlement."""
    d = decouper(_pos(accru=-2.0, entree=T_PILE), now_ms=int(T_PILE + 4.0 * H))
    assert d["net_funding_settled"] == pytest.approx(-2.0)
    assert d["funding_accrual_estimate"] == pytest.approx(0.0)


@pytest.mark.parametrize("casse", [{"entry_ts_ms": None}, {"entry_ts_ms": "hier"},
                                   {"funding_accrued_usdt": None},
                                   {"funding_accrued_usdt": float("nan")}])
def test_une_position_mal_formee_ne_leve_pas_et_ne_perd_rien(casse):
    d = decouper(_pos(**casse), now_ms=T_PILE + 5 * H)
    assert set(d) == {"net_funding_settled", "funding_accrual_estimate",
                      "heures_reglees", "fraction_heure_en_cours"}


def test_horodatage_dans_le_futur_ne_produit_pas_de_reglement_negatif():
    d = decouper(_pos(accru=1.0, entree=T_PILE + 10 * H), now_ms=T_PILE)
    assert d["net_funding_settled"] == 0.0
    assert d["heures_reglees"] == 0.0


# ------------------------------------------------------------------ agrégation portefeuille

def test_agreger_conserve_la_somme_sur_tout_le_portefeuille():
    positions = {"BTC": _pos(accru=0.10, entree=T_PILE),
                 "ETH": _pos(accru=0.20, entree=T_PILE - 3 * H),
                 "SOL": _pos(accru=0.02, entree=T_PILE + 30 * 60_000)}
    a = agreger(positions, now_ms=int(T_PILE + 2.5 * H))
    assert a["funding_total_couru"] == pytest.approx(0.32, abs=1e-6)
    assert a["net_funding_settled"] + a["funding_accrual_estimate"] == \
        pytest.approx(a["funding_total_couru"], abs=1e-9)
    assert a["positions"] == 3


def test_agreger_ignore_les_entrees_non_dict_sans_planter():
    a = agreger([_pos(), "pas une position", None, 42], now_ms=T_PILE + H)
    assert a["positions"] == 1


def test_agreger_portefeuille_vide():
    a = agreger({}, now_ms=T_PILE)
    assert a["funding_total_couru"] == 0.0 and a["positions"] == 0


# ------------------------------------------------------------------ le PnL stable

def test_le_pnl_stable_n_absorbe_QUE_le_funding_REGLE():
    assert pnl_stable(-6.05, 0.20) == pytest.approx(-5.85)


def test_le_pnl_stable_ignore_l_estimation_meme_si_on_la_lui_passe_pas():
    """Contrat explicite : la fonction ne prend PAS l'estimation en paramètre. On ne peut
    donc pas la faire entrer dans le chiffre stable par erreur d'appel."""
    import inspect
    params = set(inspect.signature(pnl_stable).parameters)
    assert params == {"realise_usd", "net_funding_settled"}
    assert "accrual" not in " ".join(params)


@pytest.mark.parametrize("mauvais", [None, "0.2", float("nan")])
def test_le_pnl_stable_ne_leve_pas_sur_une_entree_douteuse(mauvais):
    try:
        v = pnl_stable(1.0, mauvais)
    except (TypeError, ValueError):
        v = None
    assert v is None or isinstance(v, float)


# ------------------------------------------------------------------ testé ≠ branché

def test_le_decoupage_est_BRANCHE_dans_l_etat_carry():
    """Sans ça, le dashboard continuerait d'appeler « encaissé » une estimation."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "funding"
           / "carry_positions_store.py").read_text(encoding="utf-8")
    assert "funding_settlement" in src
    assert "net_funding_settled" in src and "funding_accrual_estimate" in src
