"""LE POLLER DE CARNET SONDAIT UNE LISTE VIDE (2026-07-11).

LE BUG, ET IL A NEUTRALISE TOUT LE RESTE :

    l2_snapshot_cache._loop  ->  DEFAULT_EDGE_TREND_RECORDER.coins()  ->  []
                                 ^
                                 remplie par `record_edge_observation()`,
                                 qui n'est appelee NULLE PART dans le code.

Consequence : le carnet L2 n'etait JAMAIS recupere. Donc `live_costs_for()` ne trouvait jamais
rien. Donc spread/slippage/profondeur retombaient sur des CONSTANTES (6 bps, 6 bps, 50 000 $) --
identiques pour BTC et pour un meme coin illiquide -- alors meme que le flag
HYPERSMART_V26_LIVE_BOOK_COSTS etait a 1.

Le flag etait allume. Le code etait cable. Et rien ne se passait, **parce qu'une liste vide ne
fait pas de bruit.**

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.collection import coin_universe as cu

T0 = 1_800_000.0


@pytest.fixture(autouse=True)
def _propre():
    cu.clear()
    yield
    cu.clear()


# ------------------------------------------------------------------ LE contrat

def test_an_observed_coin_becomes_pollable():
    """LE TEST QUI COMPTE : voir un signal sur un marche doit suffire a le faire sonder."""
    cu.note_coin("BTC", now_s=T0)
    assert cu.coins(now_s=T0) == ["BTC"]
    assert cu.is_empty(now_s=T0) is False


def test_an_EMPTY_universe_is_LOUD_not_silent():
    """LA LECON DU BUG. Un registre vide doit DIRE qu'il est vide, et dire ce que ca casse."""
    h = cu.health(now_s=T0)
    assert h["vide"] is True
    assert h["n_coins"] == 0
    assert "constantes" in h["consequence_si_vide"]
    assert "carnet" in h["consequence_si_vide"].lower()


def test_the_most_RECENT_coins_come_first():
    """Le poller est borne (20 coins). Il doit sonder ce qui bouge MAINTENANT, pas l'histoire."""
    cu.note_coin("OLD", now_s=T0)
    cu.note_coin("NEW", now_s=T0 + 100)
    assert cu.coins(limit=1, now_s=T0 + 100) == ["NEW"]


def test_a_stale_coin_drops_off_the_radar():
    """Un marche plus vu depuis 15 min n'est plus d'interet : le sonder gaspille du reseau."""
    cu.note_coin("BTC", now_s=T0)
    assert cu.coins(now_s=T0 + cu.TTL_S - 1) == ["BTC"]
    assert cu.coins(now_s=T0 + cu.TTL_S + 1) == []


def test_the_registry_is_BOUNDED():
    """Sans borne, on finirait par sonder 300 marches toutes les 30 s."""
    for i in range(cu.MAX_COINS + 50):
        cu.note_coin(f"C{i}", now_s=T0 + i)
    assert len(cu.coins(limit=10_000, now_s=T0 + cu.MAX_COINS + 60)) <= cu.MAX_COINS


def test_when_full_the_OLDEST_are_dropped_never_the_newest():
    for i in range(cu.MAX_COINS):
        cu.note_coin(f"C{i}", now_s=T0 + i)
    cu.note_coin("FRAIS", now_s=T0 + 10_000)
    assert "FRAIS" in cu.coins(limit=cu.MAX_COINS, now_s=T0 + 10_000)


# ------------------------------------------------------------------ robustesse

def test_an_empty_coin_is_never_registered():
    assert cu.note_coin("", now_s=T0) is False
    assert cu.note_coin("   ", now_s=T0) is False
    assert cu.is_empty(now_s=T0) is True


def test_coins_are_normalised():
    cu.note_coin("btc", now_s=T0)
    assert cu.coins(now_s=T0) == ["BTC"]


def test_note_coins_accepts_a_batch():
    assert cu.note_coins(["BTC", "ETH", ""], now_s=T0) == 2
    assert set(cu.coins(now_s=T0)) == {"BTC", "ETH"}


def test_health_never_claims_a_real_execution():
    assert cu.health(now_s=T0)["real_execution"] is False


# =============================================================================================
# LA SELECTION DES COINS A SONDER — une liste vide ne doit JAMAIS eteindre la collecte
# =============================================================================================
#
# FAIT CONSTATE : le funding s'enregistre (funding.jsonl, 2,4 Mo) mais AUCUN carnet L2 n'a jamais
# ete ecrit — meme flag, meme mecanisme, meme process. La difference : le poller de funding sonde
# TOUS les marches ; le poller de carnet ne sondait qu'une liste... qui s'est trouvee vide.
#
# On ne devine pas POURQUOI elle etait vide. On rend la collecte incapable de s'eteindre en
# silence : collecter des octets n'est pas ouvrir une position. Le deny-by-default protege les
# ORDRES, pas les DONNEES.

from hl_observer.collection.l2_snapshot_cache import (  # noqa: E402
    DEFAUT_COINS,
    DEFAUT_COINS_ENV,
    coins_a_sonder,
)


class _RecorderVide:
    def coins(self):
        return []


class _RecorderAvecCoins:
    def coins(self):
        return ["ARB", "OP"]


def test_the_book_poller_NEVER_polls_nothing():
    """LE TEST QUI COMPTE. Tout est vide -> on collecte quand meme un socle.
    Sinon le carnet n'existe pas, les couts sont des constantes, et on ne le sait pas."""
    cu.clear()
    out = coins_a_sonder(limit=20, universe=cu, recorder=_RecorderVide(), env={})
    assert out == list(DEFAUT_COINS)
    assert out, "une liste vide eteindrait la collecte en silence — c'est le bug"


def test_observed_coins_take_priority_over_the_fallback():
    # horloge REELLE : `coins_a_sonder` interroge le registre avec time.time(). Un coin note avec
    # un T0 fictif ancien serait (a juste titre) expire par le TTL.
    import time as _t

    cu.clear()
    cu.note_coin("SOL", now_s=_t.time())
    out = coins_a_sonder(limit=20, universe=cu, recorder=_RecorderAvecCoins(), env={})
    assert out == ["SOL"], "les marches reellement observes passent d'abord"


def test_the_edge_recorder_is_the_second_source_not_the_only_one():
    cu.clear()
    out = coins_a_sonder(limit=20, universe=cu, recorder=_RecorderAvecCoins(), env={})
    assert out == ["ARB", "OP"]


def test_the_fallback_list_is_configurable():
    cu.clear()
    out = coins_a_sonder(limit=20, universe=cu, recorder=_RecorderVide(),
                         env={DEFAUT_COINS_ENV: "HYPE, kPEPE ,BTC"})
    assert out == ["HYPE", "KPEPE", "BTC"]


def test_the_limit_is_respected_and_duplicates_removed():
    import time as _t

    cu.clear()
    cu.note_coins(["BTC", "btc", "ETH"], now_s=_t.time())
    out = coins_a_sonder(limit=1, universe=cu, recorder=_RecorderVide(), env={})
    assert len(out) == 1


def test_a_broken_source_never_kills_the_collection():
    """Une source qui leve ne doit pas eteindre le poller : elle doit ceder la place au socle."""
    class _Casse:
        def coins(self, **_):
            raise RuntimeError("boom")

    out = coins_a_sonder(limit=5, universe=_Casse(), recorder=_Casse(), env={})
    assert out == list(DEFAUT_COINS)


# =============================================================================================
# BALAYAGE COMPLET DU CARNET (2026-07-12)
# =============================================================================================
#
# PREMIERE MESURE REELLE, 270 releves : spread median Hyperliquid = 0,30 bps.
# BTC 0,16 · SOL 0,13 · ETH 0,56. Et l'aller-retour maker/maker coute 3,0 bps
# (chez HL le maker PAIE 1,5 bps -- pas de rebate avant les tiers institutionnels).
#
# Sur les majors, les frais sont 10 a 20x le spread : le market making y est arithmetiquement
# mort. Les seuls spreads exploitables vus (WLD 3,23 · LIT 2,32) sont sur des marches FINS.
#
# Pour savoir s'il EXISTE un marche assez large, il faut voir les ~230 marches, pas 8. D'ou le
# balayage rotatif : `lim` coins par cycle, et on avance. Zero requete de plus par cycle.

from hl_observer.collection.l2_snapshot_cache import (  # noqa: E402
    BALAYAGE_FLAG,
    _curseur,
    _tranche_rotative,
)


def test_the_sweep_eventually_covers_EVERY_market():
    """LE TEST QUI COMPTE. Si le balayage oublie un marche, c'est peut-etre LE seul dont le
    spread depasse les frais -- et on ne le saurait jamais."""
    univers = [f"C{i}" for i in range(230)]
    _curseur[0] = 0
    vus = set()
    for _ in range(20):                      # 20 cycles x 30 coins > 230
        vus.update(_tranche_rotative(univers, 30))
    assert vus == set(univers), f"{len(set(univers) - vus)} marches jamais sondes"


def test_the_sweep_advances_it_does_not_re_poll_the_same_head():
    """Un balayage qui repart de zero a chaque cycle ne verrait jamais que les 30 premiers."""
    univers = [f"C{i}" for i in range(100)]
    _curseur[0] = 0
    a = _tranche_rotative(univers, 30)
    b = _tranche_rotative(univers, 30)
    assert a != b
    assert not (set(a) & set(b)), "les deux premieres tranches ne doivent pas se recouvrir"


def test_the_sweep_wraps_around_cleanly():
    univers = ["A", "B", "C"]
    _curseur[0] = 0
    assert _tranche_rotative(univers, 2) == ["A", "B"]
    assert _tranche_rotative(univers, 2) == ["C", "A"]


def test_the_sweep_never_asks_for_more_than_the_universe():
    univers = ["A", "B"]
    _curseur[0] = 0
    assert _tranche_rotative(univers, 50) == ["A", "B"]


def test_an_empty_universe_never_crashes():
    _curseur[0] = 0
    assert _tranche_rotative([], 10) == []


def test_the_sweep_is_OFF_unless_the_flag_is_set():
    """Sonder 230 marches est un choix explicite, pas un defaut silencieux."""
    assert BALAYAGE_FLAG == "HYPERSMART_V26_BOOK_SWEEP_ALL"
