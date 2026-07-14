from __future__ import annotations

from typer.testing import CliRunner

from hl_observer.cli import app
from hl_observer.opportunities.fresh_opportunity import (
    find_fresh_opportunities,
    format_fresh_opportunity_report,
)
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import MarketSnapshot, PositionDeltaModel, TopWallet
from hl_observer.utils.time import now_ms


def _leader(wallet: str, score: float = 92.0, *, selected_at_ms: int = 10_000) -> TopWallet:
    return TopWallet(
        wallet_address=wallet,
        rank=1,
        source="test",
        score=score,
        selected_at_ms=selected_at_ms,
        status="selected",
    )


def _delta(
    wallet: str,
    *,
    coin: str = "HYPE",
    delta_type: str = "open_long",
    ms: int = 10_000,
    price: float = 25.0,
    notional: float = 50_000.0,
) -> PositionDeltaModel:
    is_short = "short" in delta_type.lower()
    return PositionDeltaModel(
        wallet_address=wallet,
        coin=coin,
        previous_side=None,
        new_side="short" if is_short else "long",
        previous_size=0.0,
        current_size=-1.0 if is_short else 1.0,
        new_size=-1.0 if is_short else 1.0,
        delta_size=1.0,
        delta_notional_usdc=notional,
        action=delta_type.upper(),
        exchange_ts=ms,
        side="short" if is_short else "long",
        price=price,
        fill_size=1.0,
        delta_type=delta_type,
        confidence_score=0.96,
        detected_at_ms=ms,
        delta_hash=f"{wallet}:{coin}:{delta_type}:{ms}",
    )


def test_fresh_opportunity_accepts_multi_wallet_same_coin_direction_cluster(monkeypatch) -> None:
    # EDGE FABRIQUE (2026-07-11) : `_expected_edge_bps` = score x 0,55 + wallets x 9
    # + notional/25000 + tightness x 10. Aucune constante mesuree : ce nombre n'a JAMAIS
    # touche un prix. Par DEFAUT le bot le refuse desormais (deny-by-default).
    # Ces tests exercent l'ANCIEN chemin -> mode A/B EXPLICITE, jamais le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    # 🚩 CORRIGE LE 13/07 (G2) : le commentaire ci-dessus disait « mode A/B EXPLICITE », mais il
    # posait l'ANCIEN flag. Le verrou de Q1 s'appelle `HYPERSMART_EDGE_SOURCE` -- et il vaut
    # `table` par defaut. Ces tests refusaient donc TOUS depuis Q1, et personne ne l'a vu : je
    # n'avais lance que des tests cibles, jamais la suite complete. La suite complete, elle,
    # ne ment pas. Ces tests exercent le CLUSTERING, pas l'edge : on assume le mode formule ici.
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    wallet_c = "0x" + "c" * 40

    report = find_fresh_opportunities(
        [
            _delta(wallet_a, ms=10_000),
            _delta(wallet_b, ms=11_500),
            _delta(wallet_c, coin="BTC", delta_type="open_short", ms=11_600),
        ],
        [_leader(wallet_a, 96), _leader(wallet_b, 90), _leader(wallet_c, 95)],
        now_timestamp_ms=12_000,
        current_mids={"HYPE": 25.0, "BTC": 70_000},
        active_window_ms=20_000,
        consensus_window_ms=4_000,
        min_wallets=2,
    )
    text = format_fresh_opportunity_report(report)

    assert report.groups_seen == 1
    assert report.accepted_for_simulation == 1
    assert report.opportunities[0].coin == "HYPE"
    assert report.opportunities[0].direction == "LONG"
    assert report.opportunities[0].wallet_count == 2
    assert report.opportunities[0].decision == "ACCEPT_LOCAL_SIMULATION"
    assert report.opportunities[0].edge_remaining_bps is not None
    assert "real_orders_created=0" in text
    assert "simulation_positions_are_virtual=true" in text


def test_fresh_opportunity_rejects_stale_and_single_wallet_clusters(monkeypatch) -> None:
    # EDGE FABRIQUE (2026-07-11) : `_expected_edge_bps` = score x 0,55 + wallets x 9
    # + notional/25000 + tightness x 10. Aucune constante mesuree : ce nombre n'a JAMAIS
    # touche un prix. Par DEFAUT le bot le refuse desormais (deny-by-default).
    # Ces tests exercent l'ANCIEN chemin -> mode A/B EXPLICITE, jamais le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    # 🚩 CORRIGE LE 13/07 (G2) : le commentaire ci-dessus disait « mode A/B EXPLICITE », mais il
    # posait l'ANCIEN flag. Le verrou de Q1 s'appelle `HYPERSMART_EDGE_SOURCE` -- et il vaut
    # `table` par defaut. Ces tests refusaient donc TOUS depuis Q1, et personne ne l'a vu : je
    # n'avais lance que des tests cibles, jamais la suite complete. La suite complete, elle,
    # ne ment pas. Ces tests exercent le CLUSTERING, pas l'edge : on assume le mode formule ici.
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40

    report = find_fresh_opportunities(
        [
            _delta(wallet_a, ms=1_000),
            _delta(wallet_b, ms=11_000),
        ],
        [_leader(wallet_a), _leader(wallet_b)],
        now_timestamp_ms=30_000,
        current_mids={"HYPE": 25.0},
        active_window_ms=5_000,
        consensus_window_ms=4_000,
        min_wallets=2,
    )

    assert report.groups_seen == 0
    assert report.accepted_for_simulation == 0
    assert dict(report.rejection_reasons)["STALE_SIGNAL"] == 2


def test_fresh_opportunity_uses_trade_age_not_audit_window_for_acceptance(monkeypatch) -> None:
    # EDGE FABRIQUE (2026-07-11) : `_expected_edge_bps` = score x 0,55 + wallets x 9
    # + notional/25000 + tightness x 10. Aucune constante mesuree : ce nombre n'a JAMAIS
    # touche un prix. Par DEFAUT le bot le refuse desormais (deny-by-default).
    # Ces tests exercent l'ANCIEN chemin -> mode A/B EXPLICITE, jamais le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    # 🚩 CORRIGE LE 13/07 (G2) : le commentaire ci-dessus disait « mode A/B EXPLICITE », mais il
    # posait l'ANCIEN flag. Le verrou de Q1 s'appelle `HYPERSMART_EDGE_SOURCE` -- et il vaut
    # `table` par defaut. Ces tests refusaient donc TOUS depuis Q1, et personne ne l'a vu : je
    # n'avais lance que des tests cibles, jamais la suite complete. La suite complete, elle,
    # ne ment pas. Ces tests exercent le CLUSTERING, pas l'edge : on assume le mode formule ici.
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40

    report = find_fresh_opportunities(
        [
            _delta(wallet_a, ms=10_000),
            _delta(wallet_b, ms=11_000),
        ],
        [_leader(wallet_a, 96), _leader(wallet_b, 94)],
        now_timestamp_ms=50_000,
        current_mids={"HYPE": 25.0},
        active_window_ms=120_000,
        consensus_window_ms=4_000,
        min_wallets=2,
        risk_config=RealtimeCopyRiskConfig(max_signal_age_ms=15_000),
    )

    assert report.groups_seen == 1
    assert report.accepted_for_simulation == 0
    assert report.opportunities[0].decision == "REJECT_NO_TRADE"
    assert "STALE_SIGNAL" in report.opportunities[0].refusal_reasons


def test_fresh_opportunity_requires_realtime_mid_for_portfolio_simulation(monkeypatch) -> None:
    # EDGE FABRIQUE (2026-07-11) : `_expected_edge_bps` = score x 0,55 + wallets x 9
    # + notional/25000 + tightness x 10. Aucune constante mesuree : ce nombre n'a JAMAIS
    # touche un prix. Par DEFAUT le bot le refuse desormais (deny-by-default).
    # Ces tests exercent l'ANCIEN chemin -> mode A/B EXPLICITE, jamais le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    # 🚩 CORRIGE LE 13/07 (G2) : le commentaire ci-dessus disait « mode A/B EXPLICITE », mais il
    # posait l'ANCIEN flag. Le verrou de Q1 s'appelle `HYPERSMART_EDGE_SOURCE` -- et il vaut
    # `table` par defaut. Ces tests refusaient donc TOUS depuis Q1, et personne ne l'a vu : je
    # n'avais lance que des tests cibles, jamais la suite complete. La suite complete, elle,
    # ne ment pas. Ces tests exercent le CLUSTERING, pas l'edge : on assume le mode formule ici.
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40

    report = find_fresh_opportunities(
        [
            _delta(wallet_a, ms=10_000),
            _delta(wallet_b, ms=11_000),
        ],
        [_leader(wallet_a, 96), _leader(wallet_b, 94)],
        now_timestamp_ms=12_000,
        current_mids={},
        active_window_ms=20_000,
        consensus_window_ms=4_000,
        min_wallets=2,
    )

    assert report.groups_seen == 1
    assert report.accepted_for_simulation == 0
    assert report.opportunities[0].current_mid is None
    assert report.opportunities[0].current_mid_source == "leader_reference_fallback"
    assert "CURRENT_MID_REQUIRED_FOR_LOCAL_SIMULATION" in report.opportunities[0].refusal_reasons


def test_fresh_opportunity_allows_leader_mid_fallback_for_fresh_signal_when_flag_set(monkeypatch) -> None:
    # EDGE FABRIQUE (2026-07-11) : `_expected_edge_bps` = score x 0,55 + wallets x 9
    # + notional/25000 + tightness x 10. Aucune constante mesuree : ce nombre n'a JAMAIS
    # touche un prix. Par DEFAUT le bot le refuse desormais (deny-by-default).
    # Ces tests exercent l'ANCIEN chemin -> mode A/B EXPLICITE, jamais le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    # 🚩 CORRIGE LE 13/07 (G2) : le commentaire ci-dessus disait « mode A/B EXPLICITE », mais il
    # posait l'ANCIEN flag. Le verrou de Q1 s'appelle `HYPERSMART_EDGE_SOURCE` -- et il vaut
    # `table` par defaut. Ces tests refusaient donc TOUS depuis Q1, et personne ne l'a vu : je
    # n'avais lance que des tests cibles, jamais la suite complete. La suite complete, elle,
    # ne ment pas. Ces tests exercent le CLUSTERING, pas l'edge : on assume le mode formule ici.
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    # Flo 2026-07-10: un signal TRES frais sans mid allMids doit pouvoir entrer via le prix leader
    # quand le flag est actif (la degradation de copie reste facturee, le gate liquidite filtre).
    monkeypatch.setenv("HYPERSMART_LEADER_MID_FALLBACK_MAX_AGE_MS", "5000")
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    report = find_fresh_opportunities(
        [_delta(wallet_a, ms=10_000), _delta(wallet_b, ms=11_500)],
        [_leader(wallet_a, 96), _leader(wallet_b, 94)],
        now_timestamp_ms=12_000,
        current_mids={},
        active_window_ms=20_000,
        consensus_window_ms=4_000,
        min_wallets=2,
    )
    assert report.groups_seen == 1
    opp = report.opportunities[0]
    assert "CURRENT_MID_REQUIRED_FOR_LOCAL_SIMULATION" not in opp.refusal_reasons
    assert opp.current_mid is not None
    assert opp.current_mid_source == "leader_reference_fallback"
    assert "CURRENT_MID_FALLBACK_FROM_LEADER_PRICE" in opp.warnings
    assert opp.decision == "ACCEPT_LOCAL_SIMULATION"
    assert report.accepted_for_simulation == 1


def test_fresh_opportunity_leader_mid_fallback_still_refuses_when_stale(monkeypatch) -> None:
    # EDGE FABRIQUE (2026-07-11) : `_expected_edge_bps` = score x 0,55 + wallets x 9
    # + notional/25000 + tightness x 10. Aucune constante mesuree : ce nombre n'a JAMAIS
    # touche un prix. Par DEFAUT le bot le refuse desormais (deny-by-default).
    # Ces tests exercent l'ANCIEN chemin -> mode A/B EXPLICITE, jamais le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    # 🚩 CORRIGE LE 13/07 (G2) : le commentaire ci-dessus disait « mode A/B EXPLICITE », mais il
    # posait l'ANCIEN flag. Le verrou de Q1 s'appelle `HYPERSMART_EDGE_SOURCE` -- et il vaut
    # `table` par defaut. Ces tests refusaient donc TOUS depuis Q1, et personne ne l'a vu : je
    # n'avais lance que des tests cibles, jamais la suite complete. La suite complete, elle,
    # ne ment pas. Ces tests exercent le CLUSTERING, pas l'edge : on assume le mode formule ici.
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    # Meme flag actif : un signal VIEUX reste refuse (le prix leader n'est plus ~= mid courant).
    monkeypatch.setenv("HYPERSMART_LEADER_MID_FALLBACK_MAX_AGE_MS", "5000")
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    report = find_fresh_opportunities(
        [_delta(wallet_a, ms=10_000), _delta(wallet_b, ms=11_000)],
        [_leader(wallet_a, 96), _leader(wallet_b, 94)],
        now_timestamp_ms=50_000,
        current_mids={},
        active_window_ms=120_000,
        consensus_window_ms=4_000,
        min_wallets=2,
        risk_config=RealtimeCopyRiskConfig(max_signal_age_ms=15_000),
    )
    assert report.groups_seen == 1
    opp = report.opportunities[0]
    assert "CURRENT_MID_REQUIRED_FOR_LOCAL_SIMULATION" in opp.refusal_reasons
    assert opp.decision == "REJECT_NO_TRADE"


def test_opportunity_report_cli_reads_recent_deltas_from_db(tmp_path, monkeypatch) -> None:
    # EDGE FABRIQUE (2026-07-11) : `_expected_edge_bps` = score x 0,55 + wallets x 9
    # + notional/25000 + tightness x 10. Aucune constante mesuree : ce nombre n'a JAMAIS
    # touche un prix. Par DEFAUT le bot le refuse desormais (deny-by-default).
    # Ces tests exercent l'ANCIEN chemin -> mode A/B EXPLICITE, jamais le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    # 🚩 CORRIGE LE 13/07 (G2) : le commentaire ci-dessus disait « mode A/B EXPLICITE », mais il
    # posait l'ANCIEN flag. Le verrou de Q1 s'appelle `HYPERSMART_EDGE_SOURCE` -- et il vaut
    # `table` par defaut. Ces tests refusaient donc TOUS depuis Q1, et personne ne l'a vu : je
    # n'avais lance que des tests cibles, jamais la suite complete. La suite complete, elle,
    # ne ment pas. Ces tests exercent le CLUSTERING, pas l'edge : on assume le mode formule ici.
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    db_path = tmp_path / "opportunities.sqlite3"
    monkeypatch.setenv("HL_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("HL_LOGS_DIR", str(tmp_path / "logs"))
    init_db(f"sqlite:///{db_path}")
    factory = create_session_factory(create_sqlite_engine(f"sqlite:///{db_path}"))
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    current_ms = now_ms()
    with factory() as session:
        session.add_all([_leader(wallet_a, 96, selected_at_ms=current_ms), _leader(wallet_b, 93, selected_at_ms=current_ms)])
        session.add_all([
            _delta(wallet_a, ms=current_ms - 2_000),
            _delta(wallet_b, ms=current_ms - 500),
        ])
        session.add(MarketSnapshot(source="allMids", exchange_ts=current_ms, raw_json={"HYPE": "25.0"}))
        session.commit()

    result = CliRunner().invoke(
        app,
        [
            "opportunity-report",
            "--active-window-seconds",
            "20",
            "--consensus-window-seconds",
            "4",
            "--min-wallets",
            "2",
            "--max-deltas",
            "100",
        ],
    )

    assert result.exit_code == 0
    assert "opportunity_report=research_only" in result.output
    assert "accepted_for_virtual_simulation=1" in result.output
    assert "HYPE LONG decision=ACCEPT_LOCAL_SIMULATION" in result.output
    assert "real_orders_created=0" in result.output
