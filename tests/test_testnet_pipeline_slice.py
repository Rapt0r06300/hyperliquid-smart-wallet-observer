from __future__ import annotations

import asyncio

from hl_observer.config.settings import Settings
from hl_observer.decision_engine.local_engine import DecisionAction, LocalDecisionEngine
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.mainnet_readonly_observer.observer import MainnetReadOnlyObserver
from hl_observer.testnet.models import TestnetAction as Action
from hl_observer.testnet.models import TestnetSide as Side


class FakeReadOnlyInfoClient:
    async def all_mids(self) -> dict[str, str]:
        return {"BTC": "60000", "HYPE": "40"}

    async def l2_book(self, coin: str) -> dict[str, object]:
        return {"coin": coin, "levels": []}

    async def clearinghouse_state(self, wallet: str) -> dict[str, object]:
        return {"user": wallet, "assetPositions": []}

    async def user_fills(self, wallet: str) -> list[dict[str, object]]:
        return [{"user": wallet, "coin": "BTC", "px": "60000", "sz": "0.01"}]


def test_mainnet_readonly_observer_returns_partial_public_state_without_execution() -> None:
    observer = MainnetReadOnlyObserver(client=FakeReadOnlyInfoClient())

    observation = asyncio.run(
        observer.observe(
            coins=["BTC"],
            wallets=["0x1111111111111111111111111111111111111111"],
            include_l2=True,
            include_wallet_fills=True,
        )
    )

    assert observation.source == "hyperliquid_mainnet_readonly"
    assert observation.all_mids["BTC"] == 60000.0
    assert "BTC" in observation.l2_books
    assert observation.wallet_states
    assert observation.wallet_fills
    assert observation.errors == []


def _candidat_qui_s_auto_autorise() -> SignalCandidate:
    """Un candidat qui APPORTE SON PROPRE EDGE (80 bps). Personne ne l'a mesure."""
    return SignalCandidate(
        id="sig-testnet-1",
        source_wallet="0x2222222222222222222222222222222222222222",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=60000.0,
        timestamp_ms=1,
        signal_age_ms=100,
        wallet_score=95.0,
        signal_score=90.0,
        edge_remaining_bps=80.0,      # <- le chiffre magique. D'ou vient-il ? De NULLE PART.
        estimated_fee_bps=4.0,
        estimated_spread_bps=1.0,
        estimated_slippage_bps=1.0,
        orderbook_depth_usdc=1_000_000.0,
    )


def test_G2_le_noyau_REFUSE_le_candidat_qui_apporte_son_propre_edge(monkeypatch) -> None:
    """🔴 CE TEST A CHANGE DE VERDICT LE 13/07, ET C'EST LE BUT.

    Avant G2, ce candidat passait : il annoncait `edge_remaining_bps=80`, le RiskEngine notait
    ce 80 avec une arithmetique impeccable, et un ordre testnet etait prepare. Le juge notait le
    CHIFFRE sans jamais questionner sa PROVENANCE -- c'est le trou par lequel trois edges
    FABRIQUES sont entres.

    Le noyau (G2) refuse maintenant AVANT tout calcul : un fill public de leader appartient a la
    famille DISCRETIONNAIRE_PUBLIC, zone morte MESUREE (24 133 signaux OOS, edge net negatif meme
    a cout zero). L'ancien comportement n'etait pas « bon puis casse » : il etait FAUX, et le test
    le certifiait.
    """
    monkeypatch.setenv("HYPERSMART_NOYAU_AUTORITAIRE", "1")

    decision = LocalDecisionEngine(Settings()).decide_from_candidate(
        _candidat_qui_s_auto_autorise(),
        notional_usdc=2.0,
        cloid="decision-testnet-btc-open",
    )

    assert decision.action is DecisionAction.NO_TRADE
    assert decision.order_request is None
    assert decision.reasons == ["NOYAU_SIGNAL_DANS_UNE_ZONE_MORTE_PROUVEE"]

    # Et la contradiction est ECRITE, pas seulement refusee.
    noyau = decision.evidence["noyau"]
    assert noyau["autoritaire"] is True
    assert noyau["edge_brut_bps"] is None, "le noyau n'a meme pas eu a calculer un edge"
    assert noyau["real_execution"] is False


def test_le_plomberie_testnet_reste_correcte_quand_le_noyau_est_consultatif(monkeypatch) -> None:
    """Le noyau eteint, la PLOMBERIE (RiskEngine -> TestnetOrderRequest) doit rester intacte.

    Ce test ne dit PAS que le trade est bon -- il dit que la tuyauterie fonctionne. Et il verifie
    que meme ignore, le verdict du noyau reste ECRIT dans la preuve : un verdict qu'on ignore doit
    laisser une trace, sinon personne ne saura jamais qu'on l'a ignore.
    """
    monkeypatch.setenv("HYPERSMART_NOYAU_AUTORITAIRE", "0")

    decision = LocalDecisionEngine(Settings()).decide_from_candidate(
        _candidat_qui_s_auto_autorise(),
        notional_usdc=2.0,
        cloid="decision-testnet-btc-open",
    )

    assert decision.action is DecisionAction.ENTER
    assert decision.order_request is not None
    assert decision.order_request.action is Action.OPEN
    assert decision.order_request.side is Side.LONG
    assert decision.order_request.coin == "BTC"
    assert decision.order_request.source_signal_id == "sig-testnet-1"
    assert decision.evidence["decision_layer"] == "local_decision_engine"

    noyau = decision.evidence["noyau"]
    assert noyau["autoritaire"] is False
    assert noyau["verdict"] == "NO_TRADE"
    assert "NOYAU_CONSULTATIF_VERDICT_IGNORE" in noyau["signalements"]
