"""#583 (`position_stacking`) + #325 (baseline IMMUABLE).

🔴 ***Un backtest qui empile ce que le live refuse ne mesure pas la meme strategie.***
Il mesure une strategie **plus grosse, plus concentree, plus risquee** -- et il l'appelle
« notre strategie ». C'est la famille de bugs de ce projet : *une contrainte presente d'un cote,
absente de l'autre, et personne qui se plaint.*
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.backtest_live_parity import (
    MAX_POSITIONS_PAR_COIN,
    MOTIF_BASELINE_CHANGEE,
    MOTIF_CONCENTRATION,
    MOTIF_DEJA_UNE_POSITION,
    MOTIF_EXPOSITION,
    MOTIF_OK,
    MOTIF_TROP_DE_POSITIONS,
    Position,
    comparer,
    le_live_accepterait,
    rejouer_sans_empilement,
    sceller,
)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #583 — LE BACKTEST EMPILE-T-IL ?
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_live_REFUSE_une_2e_position_sur_le_meme_coin() -> None:
    ok, m = le_live_accepterait("BTC", 500.0, long=True,
                                positions_ouvertes=[Position("BTC", 500.0, True)], capital=5000.0)
    assert not ok and m == MOTIF_DEJA_UNE_POSITION
    assert MAX_POSITIONS_PAR_COIN == 1


def test_le_backtest_qui_EMPILE_est_demasque() -> None:
    """🔴 **LE TEST QUI COMPTE.** 10 signaux BTC d'affilee : le live n'en prend **QU'UN**."""
    c = rejouer_sans_empilement([("BTC", 500.0, True)] * 10, capital=5000.0)
    assert c.acceptes == 1
    assert c.refus_deja_une_position == 9
    assert c.part_empilee == pytest.approx(0.90)
    d = c.as_dict()
    assert "LE BACKTEST MENTAIT" in d["verdict"]
    assert "90 %" in d["verdict"]


def test_un_backtest_HONNETE_ne_declenche_PAS_l_alerte() -> None:
    c = rejouer_sans_empilement(
        [("BTC", 300.0, True), ("ETH", 300.0, True), ("SOL", 300.0, True)], capital=5000.0)
    assert c.refuses == 0
    assert "essentiellement les memes trades" in c.as_dict()["verdict"]


def test_le_cap_TOTAL_de_positions_est_applique() -> None:
    ouv = [Position("C%d" % i, 100.0, True) for i in range(5)]
    ok, m = le_live_accepterait("NEW", 100.0, long=True,
                                positions_ouvertes=ouv, capital=100_000.0)
    assert not ok and m == MOTIF_TROP_DE_POSITIONS


def test_l_exposition_NETTE_est_regardee_pas_le_BRUT() -> None:
    """🔴 Le gate historique ne voyait que le BRUT. Un long + un short se COMPENSENT."""
    # 2 positions opposees : le NET est nul -> une 3e passe
    ouv = [Position("BTC", 5000.0, True), Position("ETH", 5000.0, False)]
    ok, _ = le_live_accepterait("SOL", 500.0, long=True,
                                positions_ouvertes=ouv, capital=10_000.0)
    assert ok, "long + short se compensent : le NET n'est pas depasse"

    # ... mais 2 positions du MEME cote saturent le net
    ouv2 = [Position("BTC", 5000.0, True), Position("ETH", 5000.0, True)]
    ok2, m2 = le_live_accepterait("SOL", 5000.0, long=True,
                                  positions_ouvertes=ouv2, capital=10_000.0)
    assert not ok2 and m2 == MOTIF_EXPOSITION


def test_la_CONCENTRATION_se_mesure_contre_le_CAPITAL_pas_contre_le_LIVRE() -> None:
    """🔴 BUG TROUVE PAR CE TEST : je mesurais la part contre le LIVRE COURANT.

    Consequence : la **toute premiere** position vaut 100 % du livre -> **toujours refusee**.
    ***Le bot n'aurait jamais ouvert un seul trade.***
    *Un garde-fou qui refuse TOUT n'est pas prudent : il est CASSE.*
    (On a deja eu 3 verrous MORTS qui garantissaient 0 trade par arithmetique.)
    """
    # la 1re position (10 % du capital) DOIT passer
    ok, _ = le_live_accepterait("BTC", 500.0, long=True,
                                positions_ouvertes=[], capital=5000.0)
    assert ok, "la premiere position ne peut pas etre refusee pour 'concentration'"

    # ... mais 70 % du capital sur un seul coin, non
    ok2, m2 = le_live_accepterait("BTC", 7000.0, long=True,
                                  positions_ouvertes=[], capital=10_000.0)
    assert not ok2 and m2 == MOTIF_CONCENTRATION


def test_un_capital_nul_n_ouvre_RIEN() -> None:
    ok, _ = le_live_accepterait("BTC", 500.0, long=True, positions_ouvertes=[], capital=0.0)
    assert not ok


def test_un_signal_normal_passe() -> None:
    ok, m = le_live_accepterait("BTC", 500.0, long=True,
                                positions_ouvertes=[], capital=5000.0)
    assert ok and m == MOTIF_OK


# ════════════════════════════════════════════════════════════════════════════════════════════
# #325 — LA BASELINE IMMUABLE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_une_baseline_scellee_se_compare_a_elle_meme() -> None:
    b = sceller({"n": 100}, {"seuil": 30}, {"pnl": -64.0, "sharpe": 0.1}, le="2026-07-14")
    r = comparer(b, {"n": 100}, {"seuil": 30}, {"pnl": -50.0, "sharpe": 0.2})
    assert r["valide"]
    assert r["deltas"]["pnl"] == pytest.approx(14.0)


def test_si_les_DONNEES_ont_change_la_baseline_CRIE() -> None:
    """🔴 *Sans ca, chaque « amelioration » se compare a un passe qui a BOUGE.*"""
    b = sceller({"n": 100}, {"seuil": 30}, {"pnl": -64.0}, le="2026-07-14")
    r = comparer(b, {"n": 200}, {"seuil": 30}, {"pnl": 0.0})     # donnees changees !
    assert not r["valide"]
    assert r["motif"] == MOTIF_BASELINE_CHANGEE
    assert "un passe qui a bouge" in r["detail"]


def test_si_la_CONFIG_a_change_la_baseline_CRIE_aussi() -> None:
    b = sceller({"n": 100}, {"seuil": 30}, {"pnl": -64.0}, le="2026-07-14")
    r = comparer(b, {"n": 100}, {"seuil": 5}, {"pnl": 999.0})    # config changee !
    assert not r["valide"] and r["motif"] == MOTIF_BASELINE_CHANGEE
