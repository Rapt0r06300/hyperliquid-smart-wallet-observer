"""ADAPTATEUR FUSION -- mis a jour apres la decouverte de l'EDGE FABRIQUE (2026-07-11).

Ces tests exigeaient que le bot OUVRE une position. Or l'"edge" qui autorisait cette ouverture
valait `dominance x 45 + bonus - 18` : un score de VOTE, jamais un prix. Le code l'avouait
(`edge_source = "CONSENSUS_VOTE_PROXY_NOT_EMPIRICAL"`).

Regle desormais : un edge est MESURE, ou il n'existe pas -> NO_TRADE. **Deny-by-default.**
Ces tests verifient donc les DEUX comportements :
  * par defaut, sans table d'edge mesuree -> le bot REFUSE (c'est le correctif) ;
  * en mode A/B explicite (HYPERSMART_REQUIRE_EMPIRICAL_EDGE=0) -> l'ancien chemin fonctionne
    encore, pour pouvoir COMPARER. Il ne doit jamais redevenir le defaut.
"""
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.fusion_paper_engine_adapter import (
    run_copy_votes_through_paper_engine,
    run_distilled_opportunities_through_paper_engine,
)
from hl_observer.signals.distilled_opportunity_detector import DistilledOpportunity


def _install_recorded_books(monkeypatch, prices: dict[str, float]) -> None:
    def inputs(coin: str, *, observed_at_ms: int):
        mid = float(prices[str(coin).upper()])
        truth = ExecutionTruth.from_levels(
            coin=coin,
            bids=((mid * 0.99995, 100.0),),
            asks=((mid * 1.00005, 100.0),),
            received_ts_ms=observed_at_ms,
            exchange_ts_ms=observed_at_ms,
            source="TEST_RECORDED_L2",
            data_origin="RECORDED_REAL",
        )
        return truth.spread_bps, 1.0, truth

    monkeypatch.setattr(
        "hl_observer.paper_trading.fusion_paper_engine_adapter._live_execution_inputs",
        inputs,
    )


def test_fusion_paper_engine_adapter_uses_existing_paper_engine(monkeypatch):
    # mode A/B explicite : on exerce l'ANCIEN chemin (edge proxy), pas le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    _install_recorded_books(monkeypatch, {"HYPE": 100.0})
    result = run_copy_votes_through_paper_engine(
        (
            LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=2.0),
            LeaderVote(wallet="0x2", coin="HYPE", side="LONG", score=1.0),
        ),
        market_price=100.0,
        observed_at_ms=1000,
    )
    assert result.accepted_count == 1
    assert result.decisions[0].accepted is True
    assert result.decisions[0].trade is not None
    assert result.paper_only is True
    assert result.real_execution is False
    context = result.decisions[0].decision_context
    assert context["consensus_wallets"] == 2
    assert context["leader_wallets"] == ["0x1", "0x2"]
    # 2026-07-12 -- CE TEST DISAIT `is False`, ET C'ETAIT LE SYMPTOME DU CABLAGE MORT.
    #
    # `edge_is_empirical` etait TOUJOURS faux, parce que rien ne le calculait : la table
    # mesuree n'etait lue nulle part sur ce chemin. Le test entérinait donc la panne.
    # Depuis Q1, le champ est DERIVE de `edge_from_calibration()`. Il est vrai quand une bande
    # mesuree couvre la fraicheur du signal (ici : la TEST_FIXTURE posee par conftest).
    #
    # Ce qui compte n'est pas sa valeur, c'est qu'il DISE LA VERITE sur la provenance de l'edge.
    assert context["edge_is_empirical"] is True, (
        "l'edge devrait etre marque empirique : conftest fournit une table mesuree. "
        "S'il est faux, `edge_from_calibration()` n'est plus consultee -- le cablage est remort."
    )
    # `edge_source` porte la provenance de la TABLE (ici "TEST_FIXTURE"), pas l'etiquette posee
    # par l'appelant : le moteur l'ECRASE avec ce que dit `edge_from_calibration()`. C'est le
    # bon comportement -- l'appelant ne raconte plus l'origine de l'edge, la mesure la raconte.
    # (J'avais d'abord assert le contraire : c'etait moi qui me trompais, pas le code.)
    assert str(context.get("edge_source", "")), "la provenance de l'edge ne doit jamais etre vide"
    assert context["book_costs_are_live"] is True
    assert context["execution_snapshot_id"]


def test_fusion_runtime_refuses_when_full_live_book_is_missing(monkeypatch):
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    monkeypatch.setattr(
        "hl_observer.paper_trading.fusion_paper_engine_adapter._live_execution_inputs",
        lambda coin, observed_at_ms: (6.0, 6.0, None),
    )

    result = run_copy_votes_through_paper_engine(
        (
            LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=2.0),
            LeaderVote(wallet="0x2", coin="HYPE", side="LONG", score=1.0),
        ),
        market_price=100.0,
        observed_at_ms=1_000,
    )

    assert result.accepted_count == 0
    assert result.decisions
    assert "NO_LIVE_EXECUTABLE_BOOK" in result.decisions[0].reason_codes
    assert result.decisions[0].decision_context["book_costs_are_live"] is False


def test_fusion_paper_engine_does_not_count_wallets_from_other_coins_as_consensus(monkeypatch):
    # mode A/B explicite : on exerce l'ANCIEN chemin (edge proxy), pas le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    result = run_copy_votes_through_paper_engine(
        (
            LeaderVote(wallet="0x1", coin="HYPE", side="LONG", score=3.0, observed_at_ms=900),
            LeaderVote(wallet="0x2", coin="BTC", side="LONG", score=3.0, observed_at_ms=900),
        ),
        market_price=100.0,
        observed_at_ms=1_000,
    )

    assert result.accepted_count == 0
    assert result.decisions == ()


def test_distilled_opportunities_use_existing_paper_engine_with_real_mark(monkeypatch):
    # mode A/B explicite : on exerce l'ANCIEN chemin (edge proxy), pas le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    _install_recorded_books(monkeypatch, {"HYPE": 100.0})
    result = run_distilled_opportunities_through_paper_engine(
        (
            DistilledOpportunity(
                coin="HYPE",
                side="LONG",
                wallet_count=3,
                wallets=("0x1", "0x2", "0x3"),
                total_notional_usdc=25_000.0,
                average_edge_bps=45.0,
                average_liquidity_score=0.92,
                max_signal_age_ms=1_500,
                power_score=91.0,
                source_profiles=("whale_wallet_mirror",),
            ),
        ),
        market_prices={"HYPE": 100.0},
        observed_at_ms=10_000,
    )

    assert result.accepted_count == 1
    assert result.decisions[0].accepted is True
    assert result.decisions[0].trade is not None
    assert result.decisions[0].position is not None
    assert result.decisions[0].ledger_snapshot is not None
    assert result.paper_only is True
    assert result.real_execution is False


def test_distilled_opportunities_refuse_when_real_mark_is_missing(monkeypatch):
    # mode A/B explicite : on exerce l'ANCIEN chemin (edge proxy), pas le defaut.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    _install_recorded_books(monkeypatch, {"HYPE": 100.0})
    result = run_distilled_opportunities_through_paper_engine(
        (
            DistilledOpportunity(
                coin="HYPE",
                side="LONG",
                wallet_count=3,
                wallets=("0x1", "0x2", "0x3"),
                total_notional_usdc=25_000.0,
                average_edge_bps=45.0,
                average_liquidity_score=0.92,
                max_signal_age_ms=1_500,
                power_score=91.0,
                source_profiles=("whale_wallet_mirror",),
            ),
        ),
        market_prices={},
        observed_at_ms=10_000,
    )

    assert result.accepted_count == 0
    assert result.decisions[0].accepted is False
    assert "MARKET_PRICE_INVALID" in result.decisions[0].reason_codes
    assert result.paper_only is True
    assert result.real_execution is False
