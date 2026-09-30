"""V26 L1 — Tests des vetos d'entrée funding sain + edge stable (repo 32).

100 % simulation : aucun ordre réel, aucune I/O réseau, données synthétiques de test
(contexte TEST_FIXTURE — jamais mélangées au PnL live).
"""

from __future__ import annotations

import pathlib

import pytest

from hl_observer.funding import funding_runtime_cache as frc
from hl_observer.signals.v26_entry_vetos import (
    DEFAULT_EDGE_TREND_RECORDER,
    MASTER_FLAG,
    REASON_EDGE_TREND_DOWN,
    REASON_FUNDING_SPIKE,
    REASON_FUNDING_WARMUP,
    EdgeTrendRecorder,
    apply_v26_entry_vetos,
    funding_sanity,
)

ENV_ON = {MASTER_FLAG: "1"}
ENV_OFF = {MASTER_FLAG: "0"}


@pytest.fixture(autouse=True)
def _clean_state():
    DEFAULT_EDGE_TREND_RECORDER.clear()
    frc.clear()
    yield
    DEFAULT_EDGE_TREND_RECORDER.clear()
    frc.clear()


# ---------------------------------------------------------------- funding_sanity

def test_funding_no_feed_is_unknown_never_blocks():
    fs = funding_sanity(None)
    assert fs.ok is None and fs.code is None
    fs2 = funding_sanity([])
    assert fs2.ok is None and fs2.code is None


def test_funding_warmup_refused_when_feed_young():
    fs = funding_sanity([0.0001, 0.0001], min_samples=6)
    assert fs.ok is False and fs.code == REASON_FUNDING_WARMUP


def test_funding_spike_refused():
    rates = [0.0001] * 11 + [0.01]  # dernier taux aberrant vs distribution
    fs = funding_sanity(rates, sigma=2.0, min_samples=6)
    assert fs.ok is False and fs.code == REASON_FUNDING_SPIKE
    assert fs.z_score is not None and abs(fs.z_score) >= 2.0


def test_funding_stable_accepted():
    rates = [0.0001, 0.00011, 0.00009, 0.0001, 0.000105, 0.000095, 0.0001]
    fs = funding_sanity(rates, sigma=2.0, min_samples=6)
    assert fs.ok is True and fs.code is None


# ---------------------------------------------------------------- EdgeTrendRecorder

def test_trend_insufficient_samples_is_none():
    rec = EdgeTrendRecorder()
    for v in (10, 11, 12):
        rec.record("BTC", "LONG", v)
    assert rec.trend("BTC", "LONG") is None  # < lookback => inconnu, ne bloque pas


def test_trend_decreasing_detected():
    rec = EdgeTrendRecorder()
    for v in (30, 28, 26, 18, 15, 12):
        rec.record("BTC", "LONG", v)
    assert rec.trend("BTC", "LONG") == "decreasing"


def test_trend_increasing_and_stable():
    rec = EdgeTrendRecorder()
    for v in (10, 11, 12, 20, 22, 24):
        rec.record("ETH", "SHORT", v)
    assert rec.trend("ETH", "SHORT") == "increasing"
    rec2 = EdgeTrendRecorder()
    for v in (10, 10.5, 10, 10.2, 10.1, 10.3):
        rec2.record("SOL", "LONG", v)
    assert rec2.trend("SOL", "LONG") == "stable"


def test_trend_ignores_nan_inf_and_keys_by_coin_side():
    rec = EdgeTrendRecorder()
    rec.record("BTC", "LONG", float("nan"))
    rec.record("BTC", "LONG", float("inf"))
    rec.record("", "LONG", 10.0)  # coin vide => ignoré
    assert rec.trend("BTC", "LONG") is None
    for v in (30, 28, 26, 18, 15, 12):
        rec.record("BTC", "LONG", v)
    assert rec.trend("BTC", "SHORT") is None  # side différent = série différente


# ---------------------------------------------------------------- apply_v26_entry_vetos

def _feed_decreasing(coin="BTC", side="LONG"):
    # SERIE CORRIGEE (audit 2026-07-11) : elle etait SOUS le plancher d'edge (28 bps), donc le
    # scorer refusait pour EDGE_REMAINING_TOO_LOW et les tests ne mesuraient plus le VETO DE
    # TENDANCE qu'ils pretendent mesurer. Serie desormais HAUTE mais bien DECROISSANTE.
    for v in (90, 86, 82, 78, 74, 71):
        DEFAULT_EDGE_TREND_RECORDER.record(coin, side, v)


def test_master_flag_off_never_blocks_but_records():
    _feed_decreasing()
    out = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=10.0, env=ENV_OFF)
    assert out == []
    # l'observation a bien été enregistrée malgré flag OFF
    assert DEFAULT_EDGE_TREND_RECORDER.trend("BTC", "LONG") == "decreasing"


def test_unknown_coin_never_blocks_even_flag_on():
    out = apply_v26_entry_vetos(coin="", side="LONG", edge_remaining_bps=10.0, env=ENV_ON)
    assert out == []


def test_edge_trend_veto_fires_when_authoritative():
    _feed_decreasing()
    out = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=10.0, env=ENV_ON)
    assert REASON_EDGE_TREND_DOWN in out


def test_funding_spike_veto_fires_from_cache():
    for r in [0.0001] * 11 + [0.01]:
        frc.push("BTC", r)
    out = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=50.0, env=ENV_ON)
    assert REASON_FUNDING_SPIKE in out


def test_funding_warmup_veto_fires_from_cache():
    frc.push("BTC", 0.0001)
    frc.push("BTC", 0.0001)
    out = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=50.0, env=ENV_ON)
    assert REASON_FUNDING_WARMUP in out


def test_no_feed_no_history_accepts():
    out = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=50.0, env=ENV_ON)
    assert out == []  # inconnu partout => rien ne bloque (état honnête)


def test_subflags_disable_individually():
    _feed_decreasing()
    for r in [0.0001] * 11 + [0.01]:
        frc.push("BTC", r)
    env = {MASTER_FLAG: "1", "HYPERSMART_V26_EDGE_TREND_VETO": "0"}
    out = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=10.0, env=env)
    assert REASON_EDGE_TREND_DOWN not in out and REASON_FUNDING_SPIKE in out
    env2 = {MASTER_FLAG: "1", "HYPERSMART_V26_FUNDING_VETO": "0"}
    out2 = apply_v26_entry_vetos(coin="BTC", side="LONG", edge_remaining_bps=10.0, env=env2)
    assert REASON_FUNDING_SPIKE not in out2 and REASON_EDGE_TREND_DOWN in out2


# ---------------------------------------------------------------- cache funding

def test_cache_window_and_bad_values():
    frc.push("btc", 0.0001, ts=1_000.0)
    frc.push("BTC", 0.0002, ts=2_000.0)
    frc.push("BTC", float("nan"))
    frc.push("", 0.5)
    assert frc.recent_rates("BTC", window_s=500.0, now=2_100.0) == [0.0002]
    assert frc.sample_count("BTC") == 2  # NaN et coin vide refusés


# ---------------------------------------------------------------- gate unifié V12

def test_copy_decision_new_fields_neutral_by_default():
    from hl_observer.signals.copy_decision import CopyInputs, evaluate_copy_candidate

    base = dict(signal_age_ms=1000, net_edge_bps=50.0, min_edge_bps=15.0)
    d = evaluate_copy_candidate(CopyInputs(**base))
    assert d.accepted is True
    assert "funding_sane" in d.checks_passed and "edge_trend" in d.checks_passed


def test_copy_decision_blocks_on_funding_and_trend():
    from hl_observer.signals.copy_decision import CopyInputs, evaluate_copy_candidate

    base = dict(signal_age_ms=1000, net_edge_bps=50.0, min_edge_bps=15.0)
    d1 = evaluate_copy_candidate(CopyInputs(**base, funding_spike=True))
    assert d1.accepted is False and d1.reason_code == "FUNDING_SPIKE"
    d2 = evaluate_copy_candidate(CopyInputs(**base, funding_warmup=True))
    assert d2.accepted is False and d2.reason_code == "FUNDING_HISTORY_WARMUP"
    d3 = evaluate_copy_candidate(CopyInputs(**base, edge_trend_decreasing=True))
    assert d3.accepted is False and d3.reason_code == "EDGE_TRENDING_DOWN"


def test_taxonomy_codes_registered():
    from hl_observer.signals.no_trade_taxonomy import reason

    for code in ("FUNDING_SPIKE", "FUNDING_HISTORY_WARMUP", "EDGE_TRENDING_DOWN"):
        r = reason(code)
        assert r.reason_code == code and r.blocks_trade is True


# ---------------------------------------------------------------- scorer intégration

def _accepting_inputs(coin=""):
    from hl_observer.copying.realtime_magic_score import RealtimeCopyScoreInput

    return RealtimeCopyScoreInput(
        action_type="OPEN_LONG",
        direction="LONG",
        # FIXTURE CORRIGEE (audit 2026-07-11) : 25 bps -> edge_remaining ~17 bps, SOUS le plancher
        # de 28 bps -> le scorer refusait avec EDGE_REMAINING_TOO_LOW. Le code avait RAISON ; la
        # fixture etait perimee (le plancher d'edge a ete durci depuis). On donne un edge
        # franchement acceptable pour que le test verifie ce qu'il pretend verifier : le VETO,
        # pas le plancher d'edge.
        leader_expected_edge_bps=70.0,
        leader_consistency_factor=1.0,
        signal_age_ms=500,
        consensus_wallets=3,
        liquidity_score=0.9,
        leader_score=90.0,
        leader_reference_price=100.0,
        current_mid=100.0,
        leader_notional_usdt=40.0,
        current_open_exposure_usdt=0.0,
        current_open_positions=0,
        max_open_positions=10,
        coin=coin,
    )


def test_scorer_unchanged_when_flag_off(monkeypatch):
    monkeypatch.delenv(MASTER_FLAG, raising=False)
    from hl_observer.copying.realtime_magic_score import score_realtime_copy_candidate

    _feed_decreasing()
    s = score_realtime_copy_candidate(_accepting_inputs(coin="BTC"))
    assert s.accepted is True  # défaut OFF => comportement V25 inchangé


def test_scorer_rejects_on_trend_when_flag_on(monkeypatch):
    monkeypatch.setenv(MASTER_FLAG, "1")
    from hl_observer.copying.realtime_magic_score import score_realtime_copy_candidate

    _feed_decreasing()
    s = score_realtime_copy_candidate(_accepting_inputs(coin="BTC"))
    assert s.accepted is False and REASON_EDGE_TREND_DOWN in s.refusal_reasons


def test_scorer_coin_unknown_stays_accepting_even_flag_on(monkeypatch):
    monkeypatch.setenv(MASTER_FLAG, "1")
    from hl_observer.copying.realtime_magic_score import score_realtime_copy_candidate

    _feed_decreasing()
    s = score_realtime_copy_candidate(_accepting_inputs(coin=""))
    assert s.accepted is True  # sans coin, veto inerte (jamais de faux blocage)


# ---------------------------------------------------------------- sécurité

def test_no_real_trade_surface_in_new_modules():
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "hl_observer"
    for rel in ("signals/v26_entry_vetos.py", "funding/funding_runtime_cache.py"):
        text = (root / rel).read_text(encoding="utf-8")
        for forbidden in ("requests", "httpx", "aiohttp", "websocket", "/exchange", "private_key", "sign("):
            assert forbidden not in text, f"{rel} contient une surface interdite: {forbidden}"


# ---------------------------------------------------------------- poller funding (opt-in)

def test_poller_flag_off_is_noop():
    from hl_observer.funding import funding_poller as fp

    assert fp.ensure_started(env={}) is False  # pas de flag => pas de thread, pas de réseau


def test_poller_parse_and_poll_once_with_mock():
    from hl_observer.funding import funding_poller as fp

    payload = [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": ""}]},
        [{"funding": "0.0000125"}, {"funding": "-0.0002"}, {"funding": "0.1"}],
    ]
    pairs = fp.parse_meta_and_asset_ctxs(payload)
    assert pairs == [("BTC", 0.0000125), ("ETH", -0.0002)]  # nom vide ignoré

    import json as _json

    def fake_opener(url, body, timeout):
        assert _json.loads(body.decode()) == {"type": "metaAndAssetCtxs"}
        return _json.dumps(payload).encode()

    n = fp.poll_once(opener=fake_opener)
    assert n == 2
    assert frc.sample_count("BTC") == 1 and frc.sample_count("ETH") == 1


def test_poller_bad_payload_pushes_nothing():
    from hl_observer.funding import funding_poller as fp

    assert fp.parse_meta_and_asset_ctxs({"weird": 1}) == []
    assert fp.poll_once(opener=lambda u, b, t: b"not json") == 0
    assert frc.sample_count("BTC") == 0


# ---------------------------------------------------------------------------------------------
# VERROU EDGE EMPIRIQUE (2026-07-11) -- POURQUOI CES TESTS FORCENT UN FLAG.
#
# Ces tests verifient la MECANIQUE (scorer, CLI, persistance UI). Pour cela, il faut qu'une
# position s'ouvre. Or depuis le 2026-07-11, le moteur REFUSE par defaut un edge qui n'a jamais
# touche un prix : l'ancienne formule (`dominance * 45 + bonus`) fabriquait un nombre en bps sans
# regarder le marche une seule fois.
#
# On active donc `HYPERSMART_REQUIRE_EMPIRICAL_EDGE=0` : mode A/B ASSUME, PAS la production.
# Le defaut reste le REFUS -- garde par `tests/test_empirical_edge.py`.
# ---------------------------------------------------------------------------------------------
import pytest as _pytest_ab


@_pytest_ab.fixture(autouse=True)
def _mode_ab_edge_non_empirique(monkeypatch):
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
