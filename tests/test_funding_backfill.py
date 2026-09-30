"""#606 -- backfill du funding realise.

Ce que ces tests gardent :
  * **la deduplication** : un funding compte 2 fois = un carry qui rend le DOUBLE. C'est
    exactement le genre de faux edge que ce projet fabrique quand on ne regarde pas ;
  * **deny-by-default** : un enregistrement illisible est JETE, jamais devine (pas de 0 invente,
    qui ferait croire a un funding nul) ;
  * **la couverture COMPTE les trous** et rend `None` plutot qu'un chiffre invente ;
  * l'unite reste le taux **HORAIRE** (HL paie a l'heure) -- cf. le piege 8h/1h de la meme soiree.
"""
from __future__ import annotations

import pytest

from hl_observer.collection.funding_backfill import (
    HEURES_PAR_REQUETE,
    INTERVALLE_FUNDING_MS,
    MS_PAR_HEURE,
    PointFunding,
    couverture,
    dedupliquer,
    funding_cumule_bps,
    parser_funding,
    plan_de_requetes,
)

T0 = 1_700_000_000_000


def _payload(n: int, *, coin: str = "BTC", taux: str = "0.0000125", pas_h: int = 1) -> list[dict]:
    return [{"coin": coin, "fundingRate": taux, "premium": "0.0001",
             "time": T0 + i * pas_h * MS_PAR_HEURE} for i in range(n)]


# ── le plan de requetes ────────────────────────────────────────────────────────────────────────
def test_le_plan_couvre_tout_sans_demander_le_futur() -> None:
    fin = T0 + 1200 * MS_PAR_HEURE
    f = plan_de_requetes(debut_ms=T0, fin_ms=fin, heures_par_requete=500)
    assert len(f) == 3
    assert f[0][0] == T0
    assert f[-1][1] == fin, "la derniere fenetre ne doit JAMAIS depasser la fin demandee"
    for a, b in zip(f, f[1:]):
        assert a[1] == b[0], "aucun trou entre deux fenetres"


@pytest.mark.parametrize("debut,fin", [(T0, T0), (T0 + 1, T0), (0, 0)])
def test_un_intervalle_vide_ou_inverse_ne_produit_AUCUNE_requete(debut: int, fin: int) -> None:
    assert plan_de_requetes(debut_ms=debut, fin_ms=fin) == []


def test_le_pas_par_defaut_est_declare() -> None:
    assert HEURES_PAR_REQUETE == 500
    assert INTERVALLE_FUNDING_MS == MS_PAR_HEURE   # HL paie toutes les HEURES


# ── deny-by-default ────────────────────────────────────────────────────────────────────────────
def test_un_enregistrement_illisible_est_JETE_jamais_devine() -> None:
    pts = parser_funding("BTC", [
        {"coin": "BTC", "fundingRate": "0.0000125", "time": T0},
        {"coin": "BTC", "time": T0 + MS_PAR_HEURE},                    # pas de taux
        {"coin": "BTC", "fundingRate": "0.00001"},                     # pas de time
        {"coin": "BTC", "fundingRate": "abc", "time": T0 + 2 * MS_PAR_HEURE},
        {"coin": "BTC", "fundingRate": "0.00001", "time": -5},         # time absurde
        "pas un objet",
    ])
    assert len(pts) == 1, "un 0 invente ferait croire a un funding NUL. On jette."
    assert pts[0].funding == 0.0000125


def test_un_premium_illisible_ne_tue_pas_le_point() -> None:
    pts = parser_funding("BTC", [{"fundingRate": "0.0000125", "premium": "xx", "time": T0}])
    assert len(pts) == 1 and pts[0].premium is None


@pytest.mark.parametrize("payload", [None, {}, "x", 42, []])
def test_payload_malforme_ne_leve_pas_et_ne_fabrique_rien(payload: object) -> None:
    assert parser_funding("BTC", payload) == []


# ── 🔴 LA DEDUPLICATION : un funding compte deux fois = un carry qui rend le DOUBLE ────────────
def test_les_fenetres_qui_se_chevauchent_ne_DOUBLENT_PAS_le_funding() -> None:
    a = parser_funding("BTC", _payload(10))
    b = parser_funding("BTC", _payload(10))          # meme fenetre, redemandee
    fusion = dedupliquer(a + b)
    assert len(fusion) == 10, "un (coin, time) ne doit exister QU'UNE fois"

    # Et le funding cumule ne doit pas doubler.
    assert funding_cumule_bps(fusion) == pytest.approx(10 * 0.125)
    assert funding_cumule_bps(a + b) == pytest.approx(20 * 0.125)   # <- le bug, s'il revenait


def test_la_dedup_ne_melange_pas_deux_coins_au_meme_instant() -> None:
    pts = dedupliquer([PointFunding("BTC", T0, 0.0000125),
                       PointFunding("ETH", T0, 0.0000200)])
    assert len(pts) == 2


# ── la couverture : compter les trous, et dire « rien » quand il n'y a rien ────────────────────
def test_la_couverture_compte_les_TROUS() -> None:
    pts = parser_funding("BTC", _payload(5)) + parser_funding("BTC", [
        {"coin": "BTC", "fundingRate": "0.0000125", "time": T0 + 10 * MS_PAR_HEURE},
    ])
    c = couverture(dedupliquer(pts), coin="BTC")
    assert c is not None
    assert c.n_points == 6
    assert c.n_trous == 5, "5 heures manquantes entre h+4 et h+10"
    assert c.heures == pytest.approx(10.0)


def test_une_couverture_parfaite_n_a_AUCUN_trou() -> None:
    c = couverture(parser_funding("BTC", _payload(240)), coin="BTC")
    assert c is not None and c.n_trous == 0
    assert c.jours == pytest.approx(239 / 24.0, abs=0.01)


def test_couverture_rend_None_plutot_qu_un_chiffre_invente() -> None:
    assert couverture([], coin="BTC") is None
    assert couverture(parser_funding("BTC", _payload(1)), coin="BTC") is None   # 1 point != serie


def test_couverture_ignore_les_autres_coins() -> None:
    pts = parser_funding("BTC", _payload(5)) + parser_funding("ETH", _payload(50, coin="ETH"))
    c = couverture(dedupliquer(pts), coin="BTC")
    assert c is not None and c.n_points == 5


# ── l'unite : HORAIRE (le piege 8h/1h de la meme soiree) ───────────────────────────────────────
def test_le_taux_reste_HORAIRE_et_le_bps_est_coherent() -> None:
    p = PointFunding("BTC", T0, 0.0000125)
    assert p.bps_h == pytest.approx(0.125), (
        "HL paie a l'HEURE. Ne JAMAIS confondre avec le taux 8 h des CEX "
        "(cf. funding_cross_venue : 0.0001/8h == 0.0000125/1h)."
    )


def test_funding_cumule_sur_30_jours_est_la_somme_des_taux_horaires() -> None:
    pts = parser_funding("BTC", _payload(720))          # 30 jours
    assert funding_cumule_bps(pts) == pytest.approx(720 * 0.125)   # 90 bps
