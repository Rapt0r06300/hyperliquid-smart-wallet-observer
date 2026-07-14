from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)


def _input(**overrides):
    data = {
        "action_type": "OPEN_LONG",
        "direction": "LONG",
        "leader_expected_edge_bps": 120.0,
        "leader_consistency_factor": 0.95,
        "signal_age_ms": 500,
        "consensus_wallets": 3,
        "liquidity_score": 0.8,
        "leader_score": 88.0,
        "leader_reference_price": 100.0,
        "current_mid": 100.0,
        "leader_notional_usdt": 500.0,
        "current_open_exposure_usdt": 0.0,
        "current_open_positions": 0,
        "max_open_positions": 20,
    }
    data.update(overrides)
    return RealtimeCopyScoreInput(**data)


def test_realtime_magic_score_accepts_fresh_measurable_edge_for_local_simulation_only(monkeypatch):
    # EDGE FABRIQUE (2026-07-11) : par DEFAUT le bot refuse un edge non empirique.
    # Ce test exerce l'ANCIEN chemin (edge invente) -> mode A/B EXPLICITE.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    score = score_realtime_copy_candidate(_input())

    assert score.accepted
    assert score.edge_remaining_bps is not None
    assert score.edge_remaining_bps >= 25.0
    assert score.simulated_notional_usdt == 50.0
    assert score.decision == "ACCEPT_LOCAL_SIMULATION"


def test_realtime_magic_score_rejects_unmeasurable_edge():
    score = score_realtime_copy_candidate(_input(leader_expected_edge_bps=None))

    assert not score.accepted
    assert score.edge_remaining_bps is None
    assert "EDGE_UNMEASURABLE" in score.refusal_reasons


def test_realtime_magic_score_rejects_stale_signal():
    # Default max_signal_age_ms is 120min; use 8h to be clearly beyond any threshold
    score = score_realtime_copy_candidate(_input(signal_age_ms=8 * 3600 * 1000))

    assert not score.accepted
    assert "STALE_SIGNAL" in score.refusal_reasons


def test_realtime_magic_score_rejects_edge_after_costs_too_low(tmp_path, monkeypatch):
    """Un edge trop faible APRES COUTS doit etre refuse.

    2026-07-12 : l'edge se pilote par la TABLE MESUREE, plus par le signal (Q1). On pose donc
    une table faible -- trop peu pour couvrir les couts -- au lieu de le poser sur l'entree,
    ou il n'a plus aucun pouvoir.

    2026-07-13 (#594) : la table en question a change. Le scoreur lisait `empirical_edge` (indexee
    sur le seul age) alors que le chemin LIVE mesurait deja par `edge_source` (Q1). DEUX tables ;
    la plus pauvre gagnait. On a supprime la seconde -- donc c'est la table Q1 qu'il faut semer ici.
    """
    from hl_observer.edge.edge_source import ENV_CHEMIN_TABLE, vider_le_cache
    from hl_observer.edge.measured_edge_table import Features, Observation, construire

    # 14 bps : en dessous des couts (~17 bps). Assez de coins pour que la cellule LARGE existe.
    obs = [
        Observation(
            features=Features(strategie="COPY", coin=c, direction="LONG",
                              signal_age_ms=500.0, leader_score=88.0, consensus_wallets=1.0),
            markout_bps=14.0 + (0.5 if i % 2 else -0.5),
            signal_ms=0.0,
        )
        for c in ("BTC", "ETH", "SOL", "HYPE", "DOGE", "PURR")
        for i in range(6)
    ]
    p = tmp_path / "table_edge_14bps.json"
    p.write_text(construire(obs, horizon_ms=30_000, min_echantillons=30,
                            source="TEST_FIXTURE").vers_json(), encoding="utf-8")
    monkeypatch.setenv(ENV_CHEMIN_TABLE, str(p))
    vider_le_cache()

    score = score_realtime_copy_candidate(_input(consensus_wallets=1, liquidity_score=0.2))

    assert not score.accepted
    assert "EDGE_REMAINING_TOO_LOW" in score.refusal_reasons


def test_realtime_magic_score_requires_stronger_edge_for_single_wallet_entries(tmp_path, monkeypatch):
    """Un signal MONO-wallet doit franchir une barre PLUS HAUTE (55 bps) que la barre normale (28).

    #594 : l'edge ne se pose plus sur l'entree -- il vient de la TABLE (porte Q1). On seme donc
    une table a 55 bps : assez pour passer le plancher normal (28), pas assez pour la barre
    mono-wallet (55) une fois les couts payes. C'est exactement la zone que ce gate doit refuser.
    """
    from hl_observer.edge.edge_source import ENV_CHEMIN_TABLE, vider_le_cache
    from hl_observer.edge.measured_edge_table import Features, Observation, construire

    obs = [
        Observation(
            features=Features(strategie="COPY", coin=c, direction="LONG",
                              signal_age_ms=500.0, leader_score=88.0, consensus_wallets=1.0),
            markout_bps=55.0 + (0.5 if i % 2 else -0.5),
            signal_ms=0.0,
        )
        for c in ("BTC", "ETH", "SOL", "HYPE", "DOGE", "PURR")
        for i in range(6)
    ]
    p = tmp_path / "table_edge_55bps.json"
    p.write_text(construire(obs, horizon_ms=30_000, min_echantillons=30,
                            source="TEST_FIXTURE").vers_json(), encoding="utf-8")
    monkeypatch.setenv(ENV_CHEMIN_TABLE, str(p))
    vider_le_cache()

    score = score_realtime_copy_candidate(_input(consensus_wallets=1))

    assert not score.accepted
    assert "SINGLE_WALLET_EDGE_TOO_LOW" in score.refusal_reasons
    assert "EDGE_REMAINING_TOO_LOW" not in score.refusal_reasons, (
        "l'edge passe la barre NORMALE (28 bps) : le refus doit venir de la barre MONO-WALLET, "
        "pas du plancher general -- sinon ce test ne prouve pas ce qu'il pretend prouver"
    )


def test_realtime_magic_score_rejects_price_that_moved_too_far_against_copy():
    score = score_realtime_copy_candidate(_input(current_mid=100.2))

    assert not score.accepted
    assert "PRICE_DEVIATION_TOO_HIGH" in score.refusal_reasons


def test_realtime_magic_score_rejects_when_exposure_cap_is_full():
    score = score_realtime_copy_candidate(_input(current_open_exposure_usdt=200.0))

    assert not score.accepted
    assert "MAX_EXPOSURE_REACHED" in score.refusal_reasons


def test_realtime_magic_score_rejects_reduce_without_local_position_context():
    score = score_realtime_copy_candidate(_input(action_type="REDUCE"))

    assert not score.accepted
    assert "REDUCE_OR_CLOSE_NOT_ENTRY" in score.refusal_reasons


def test_realtime_magic_score_caps_position_size_against_small_leader_trade(monkeypatch):
    # EDGE FABRIQUE (2026-07-11) : par DEFAUT le bot refuse un edge non empirique.
    # Ce test exerce l'ANCIEN chemin (edge invente) -> mode A/B EXPLICITE.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    score = score_realtime_copy_candidate(_input(leader_notional_usdt=12.0))

    assert score.accepted
    assert score.simulated_notional_usdt == 12.0


def test_realtime_magic_score_rejects_excessive_crowding_as_risk_not_guarantee():
    score = score_realtime_copy_candidate(_input(consensus_wallets=22))

    assert not score.accepted
    assert "COPY_DEGRADATION_TOO_HIGH" in score.refusal_reasons
    assert "CROWDING_PENALTY_APPLIED" in score.warnings
    assert score.copy_degradation_bps > RealtimeCopyRiskConfig().fee_bps
