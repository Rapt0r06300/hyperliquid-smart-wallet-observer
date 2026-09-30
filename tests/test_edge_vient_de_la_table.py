"""L'EDGE VIENT DE LA TABLE MESUREE, JAMAIS D'UNE FORMULE (Q1)
   ... ET IL Y AVAIT **DEUX TABLES**, DONT UNE QUI ECRASAIT L'AUTRE (#594/#310, 2026-07-13).

CE QUE CES TESTS DEFENDAIENT DEJA (Q1, 12/07)
--------------------------------------------
`score_realtime_copy_candidate` possedait un verrou d'edge « empirique » qui ne lisait aucune
table : il testait `inputs.edge_is_empirical`, un drapeau a `False` que personne ne calculait.
Le champ cense empecher les edges fabriques etait lui-meme fabrique.

CE QU'ON A TROUVE ENSUITE (#594)
-------------------------------
Le correctif de Q1 avait branche `edge.empirical_edge` -- une table indexee sur le SEUL age du
signal (`runtime/calibration/empirical_edge.json`). Mais `ui/routes.py`, le chemin LIVE, mesurait
DEJA l'edge par la porte Q1 (`edge.edge_source.edge_brut` : table conditionnee sur coin, direction,
age, score du leader, consensus, BORNE BASSE, verrou anti-lookahead) et le passait au scoreur...

... qui le JETAIT pour aller relire l'autre table. **Deux sources de verite ; la plus pauvre
gagnait.** Et la valeur obtenue etait ensuite RE-MULTIPLIEE par `freshness` et `consensus_factor`
-- les features memes sur lesquelles la table conditionne deja.

Sur un edge NEGATIF (et la mesure reelle EST negative), multiplier par une fraicheur DECROISSANTE
rend l'edge MOINS negatif : le vieux signal paraissait MEILLEUR que le frais. Le multiplicateur
cense penaliser l'age le RECOMPENSAIT.

CE QUE CES TESTS DEFENDENT MAINTENANT
-------------------------------------
1. UNE seule porte : `edge.edge_source` (Q1). La table gagne toujours sur `leader_expected_edge_bps`.
2. Pas de cellule mesuree -> REFUS. Deny-by-default, aucun repli silencieux sur la formule.
3. Un appelant ne peut PAS se declarer empirique tout seul.
4. Une table NEGATIVE -> refus, mais pour la BONNE raison (l'edge mesure ne couvre pas les couts).
5. Un echantillon trop maigre -> refus.
6. 🔴 AUCUNE re-ponderation d'un edge MESURE (ni fraicheur, ni consensus, ni consistance, ni biais).
7. 🔴 Le bug de SIGNE : la fraicheur ne doit plus rendre un vieux signal « meilleur » qu'un frais.

Aucun reseau, aucun ordre : tout est en memoire ou dans tmp_path.
"""
from __future__ import annotations

import pytest

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.edge.edge_source import ENV_CHEMIN_TABLE, vider_le_cache
from hl_observer.edge.measured_edge_table import Features, Observation, construire

# 5 000 bps : absurde a dessein. Si le score s'en sert, l'edge NE VIENT PAS de la table.
EDGE_FORMULE_ABSURDE = 5_000.0

COIN = "ETH"
SCORE_LEADER = 90.0        # bande sc4 (>= 85)
CONSENSUS = 3              # bande cw2
TABLE_JUSQU_A_MS = 1_000.0  # les observations sont horodatees ici...
SIGNAL_MS = 9_000_000.0     # ... et le signal arrive BIEN apres -> pas de lookahead


def _semer_la_table(racine, monkeypatch, *, markout_bps: float, n: int = 60,
                    ages=(5_000.0, 6_000.0)) -> None:
    """Ecrit une VRAIE table Q1 (celle de la porte unique) et fait pointer le moteur dessus."""
    obs = [
        Observation(
            features=Features(
                strategie="COPY", coin=COIN, direction="LONG",
                signal_age_ms=float(age), leader_score=SCORE_LEADER,
                consensus_wallets=float(CONSENSUS),
            ),
            # +/- 0,5 bps d'ecart : la BORNE BASSE reste tres proche de la moyenne, sinon on
            # testerait la largeur de l'intervalle de confiance, pas le cablage.
            markout_bps=markout_bps + (0.5 if i % 2 else -0.5),
            signal_ms=TABLE_JUSQU_A_MS,
        )
        for age in ages
        for i in range(n)
    ]
    table = construire(obs, horizon_ms=60_000, min_echantillons=30, source="TEST_FIXTURE")
    p = racine / "data" / "reports" / "table_edge_mesuree.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(table.vers_json(), encoding="utf-8")
    monkeypatch.setenv(ENV_CHEMIN_TABLE, str(p))
    vider_le_cache()


@pytest.fixture(autouse=True)
def _racine_isolee(tmp_path, monkeypatch):
    """Chaque test part SANS AUCUNE table -- y compris la TEST_FIXTURE que conftest pose pour
    toute la suite. Ici on teste la PORTE elle-meme : elle doit refuser quand il n'y a rien."""
    monkeypatch.setenv("HYPERSMART_ROOT", str(tmp_path))
    monkeypatch.delenv("HYPERSMART_EDGE_SOURCE", raising=False)
    monkeypatch.delenv(ENV_CHEMIN_TABLE, raising=False)
    vider_le_cache()
    yield tmp_path
    vider_le_cache()


def _signal(**kw) -> RealtimeCopyScoreInput:
    base = dict(
        action_type="OPEN_LONG",
        direction="LONG",
        coin=COIN,
        leader_expected_edge_bps=EDGE_FORMULE_ABSURDE,
        leader_consistency_factor=1.0,
        signal_age_ms=5_500,
        consensus_wallets=CONSENSUS,
        liquidity_score=0.9,
        leader_score=SCORE_LEADER,
        leader_reference_price=100.0,
        current_mid=100.0,
        leader_notional_usdt=100_000.0,
        current_open_exposure_usdt=0.0,
        current_open_positions=0,
        max_open_positions=10,
        signal_ms=SIGNAL_MS,
    )
    base.update(kw)
    return RealtimeCopyScoreInput(**base)  # type: ignore[arg-type]


def test_l_edge_vient_de_la_TABLE_et_pas_de_la_formule(_racine_isolee, monkeypatch) -> None:
    """LE COEUR DE Q1.

    Le signal porte un `leader_expected_edge_bps` de 5 000 bps -- une fiction enorme.
    La table, elle, mesure 60 bps. Si le score reflete 5 000, la formule a gagne.
    """
    _semer_la_table(_racine_isolee, monkeypatch, markout_bps=60.0)
    score = score_realtime_copy_candidate(_signal())

    assert "EDGE_FROM_MEASURED_TABLE" in score.warnings, (
        "le moteur n'a pas consulte la table Q1 -- `edge_source.edge_brut` n'est pas branchee "
        "sur ce chemin, et l'edge redevient une formule inventee"
    )
    assert score.edge_remaining_bps is not None
    assert score.edge_remaining_bps < 200.0, (
        f"edge_remaining = {score.edge_remaining_bps:.1f} bps. La table dit ~60 ; la formule "
        f"disait {EDGE_FORMULE_ABSURDE:.0f}. Un tel chiffre prouve que la FORMULE a servi."
    )


def test_sans_table_on_REFUSE_au_lieu_de_retomber_sur_la_formule(_racine_isolee) -> None:
    """Deny-by-default. L'absence de mesure ne doit JAMAIS rouvrir la porte a la formule."""
    score = score_realtime_copy_candidate(_signal())      # racine vide : aucune table

    assert not score.accepted
    assert any("EDGE" in r for r in score.refusal_reasons), (
        f"aucun motif d'edge dans {score.refusal_reasons} : sans table, le bot doit refuser "
        "explicitement, pas ouvrir sur un nombre invente"
    )
    assert "EDGE_FROM_MEASURED_TABLE" not in score.warnings


def test_un_appelant_ne_peut_PLUS_se_declarer_empirique_tout_seul(_racine_isolee) -> None:
    """LE BUG HISTORIQUE : un `edge_is_empirical=True` ecrit en dur ouvrait les vannes.

    Meme en le declarant True, sans table il ne se passe rien : l'empiricite se DERIVE de la
    mesure, elle ne se DECLARE pas.
    """
    score = score_realtime_copy_candidate(_signal(edge_is_empirical=True))

    assert not score.accepted, (
        "un appelant s'est declare empirique et a ete cru sur parole. C'est exactement le trou "
        "par lequel le 3e edge fabrique est entre."
    )


def test_une_table_NEGATIVE_refuse_mais_pour_la_BONNE_raison(_racine_isolee, monkeypatch) -> None:
    """La vraie mesure est NEGATIVE. Le signal doit etre refuse -- non pas parce que le cablage
    est mort, mais parce que l'edge MESURE ne couvre pas les couts.

    Un refus par cablage mort se repare ; un refus par edge negatif est un FAIT du marche.
    Confondre les deux, c'est ce qui a coute la journee du 12/07.
    """
    _semer_la_table(_racine_isolee, monkeypatch, markout_bps=-2.17)
    score = score_realtime_copy_candidate(_signal())

    assert "EDGE_FROM_MEASURED_TABLE" in score.warnings, "la table DOIT avoir ete lue"
    assert not score.accepted
    assert score.edge_remaining_bps is not None and score.edge_remaining_bps < 0, (
        "avec un edge mesure NEGATIF et des couts positifs, l'edge restant doit etre negatif"
    )
    assert "EDGE_NOT_EMPIRICAL_NO_TRADE" not in score.refusal_reasons, (
        "le motif ne doit plus etre 'pas de mesure' -- la mesure EXISTE, elle est simplement "
        "mauvaise. Le bot doit dire la verite sur POURQUOI il refuse."
    )


def test_un_echantillon_trop_maigre_est_refuse(_racine_isolee, monkeypatch) -> None:
    """Une cellule sous le minimum d'echantillons n'est pas une mesure : c'est du bruit."""
    _semer_la_table(_racine_isolee, monkeypatch, markout_bps=60.0, n=5)     # 10 obs < min 30
    score = score_realtime_copy_candidate(_signal())

    assert not score.accepted
    assert "EDGE_FROM_MEASURED_TABLE" not in score.warnings


# ================================================== #594 : LE DOUBLE-COMPTAGE, ET LE BUG DE SIGNE


def test_un_edge_MESURE_n_est_PAS_re_pondere(_racine_isolee, monkeypatch) -> None:
    """🔴 #594 -- LE DOUBLE-COMPTAGE.

    La table conditionne DEJA sur (age, score du leader, consensus). La re-multiplier par
    `freshness x consensus_factor x consistency` compte ces memes features DEUX FOIS.

    Test : deux signaux IDENTIQUES sauf le consensus et la consistance. Tant qu'ils tombent dans
    la MEME cellule, l'edge brut retenu doit etre le MEME. Si le consensus_factor se re-appliquait,
    l'edge remaining bougerait sans qu'aucune mesure n'ait change.
    """
    _semer_la_table(_racine_isolee, monkeypatch, markout_bps=60.0)

    a = score_realtime_copy_candidate(_signal(leader_consistency_factor=1.0))
    b = score_realtime_copy_candidate(_signal(leader_consistency_factor=0.4))

    assert a.edge_remaining_bps is not None and b.edge_remaining_bps is not None
    assert abs(a.edge_remaining_bps - b.edge_remaining_bps) < 1e-6, (
        "l'edge MESURE a ete re-pondere par `leader_consistency_factor` : "
        f"{a.edge_remaining_bps:.4f} vs {b.edge_remaining_bps:.4f}. Une mesure ne se corrige pas "
        "par un coefficient invente -- c'est ainsi qu'un 5e edge fabrique renaitrait."
    )


def test_la_FRAICHEUR_ne_doit_PLUS_rendre_un_VIEUX_signal_MEILLEUR_qu_un_FRAIS(
    _racine_isolee, monkeypatch
) -> None:
    """🔴 #594 -- LE BUG DE SIGNE, ET C'EST LE PLUS VICIEUX.

    L'ancien code faisait `edge_remaining = edge_mesure * freshness - couts`, avec
    `freshness` qui DECROIT avec l'age. Sur un edge POSITIF, cela penalise bien les vieux
    signaux. Mais la mesure reelle est NEGATIVE -- et multiplier un negatif par un facteur
    qui decroit le rend MOINS negatif :

        -2,17 x 0,92 = -1,99   (signal FRAIS -> edge "pire")
        -2,17 x 0,31 = -0,67   (signal VIEUX -> edge "meilleur")

    Le multiplicateur cense PENALISER l'age le RECOMPENSAIT. Ici on verifie qu'a table egale,
    un signal vieux n'obtient JAMAIS un meilleur edge restant qu'un signal frais.
    """
    _semer_la_table(_racine_isolee, monkeypatch, markout_bps=-2.17,
                    ages=(5_000.0, 6_000.0, 20_000.0))

    frais = score_realtime_copy_candidate(_signal(signal_age_ms=5_500))
    vieux = score_realtime_copy_candidate(_signal(signal_age_ms=20_000))

    assert frais.edge_remaining_bps is not None and vieux.edge_remaining_bps is not None
    assert vieux.edge_remaining_bps <= frais.edge_remaining_bps + 1e-6, (
        "un signal de 20 s obtient un MEILLEUR edge restant qu'un signal de 5,5 s "
        f"({vieux.edge_remaining_bps:.4f} > {frais.edge_remaining_bps:.4f}) : le multiplicateur "
        "de fraicheur inverse le signe de la penalite sur un edge negatif."
    )


def test_la_DEUXIEME_table_ne_doit_plus_ecraser_la_PORTE_UNIQUE(_racine_isolee, monkeypatch) -> None:
    """🔴 #310 -- DEUX SOURCES DE VERITE, ET LA PLUS PAUVRE GAGNAIT.

    `runtime/calibration/empirical_edge.json` (indexee sur le SEUL age) ecrasait la table Q1
    (conditionnee sur coin x age x score x consensus, borne basse, anti-lookahead).

    On seme ici une table Q1 a 60 bps ET une calibration `empirical_edge` a -999 bps. Si le
    score refletait -999, la 2e table serait encore branchee.
    """
    _semer_la_table(_racine_isolee, monkeypatch, markout_bps=60.0)

    cal = _racine_isolee / "empirical_edge.json"
    cal.write_text(
        '{"measured_at":"2026-07-11T00:00:00+00:00","source":"TEST_FIXTURE","horizon_ms":30000,'
        '"min_sample_size":200,"bands":[{"age_min_ms":0,"age_max_ms":300000,"edge_bps":-999.0,'
        '"sample_size":1000,"horizon_ms":30000}],"real_execution":false}',
        encoding="utf-8",
    )
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(cal))

    score = score_realtime_copy_candidate(_signal())

    assert score.edge_remaining_bps is not None
    assert score.edge_remaining_bps > -100.0, (
        f"edge_remaining = {score.edge_remaining_bps:.1f} : la 2e table (empirical_edge, -999 bps) "
        "a ecrase la porte unique Q1 (+60 bps). Deux sources de verite coexistent encore."
    )
    assert "EDGE_FROM_CALIBRATION" not in score.warnings, (
        "le scoreur consulte encore `empirical_edge` -- la porte n'est plus unique"
    )
