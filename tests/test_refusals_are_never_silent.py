"""UN REFUS NON JOURNALISE EST UN BUG, PAS UNE DISCIPLINE (2026-07-12).

LE BUG
------
`fusion_runtime.run_fusion_strategy_runtime` alimentait `no_trade_reasons` depuis le consensus,
le distille et le triangulaire -- mais JAMAIS depuis `paper_engine.refusal_reasons`.

Or c'est exactement la qu'atterrit le verrou d'edge empirique
(`EDGE_NOT_EMPIRICAL_NO_TRADE`, edge < couts), c.-a-d. LA raison qui explique 100 % des
zero-position depuis le 11/07.

Symptome au dashboard : « 18 deltas d'entree frais · 0 position · aucun refus enregistre ».
Les signaux mouraient EN SILENCE. On ne peut pas debugger ce qu'on ne voit pas.

L'INVARIANT DEFENDU ICI
-----------------------
    tout motif de refus du moteur paper DOIT apparaitre dans no_trade_reasons.

C'est la version "trace" du deny-by-default : le deny-by-default protege les ORDRES,
il ne doit JAMAIS museler la TRACE.

Aucun ordre reel. Aucune cle. Aucune signature. Paper uniquement.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.realtime.multi_source_price_stream import PriceEvent
from hl_observer.strategies.fusion_runtime import (
    FusionRuntimeInput,
    run_fusion_strategy_runtime,
)

SOURCE = Path(__file__).resolve().parents[1] / "src" / "hl_observer" / "strategies" / "fusion_runtime.py"


def _payload(*, coin: str = "BTC", side: str = "LONG", now_ms: int = 1_000_000) -> FusionRuntimeInput:
    """Trois leaders d'accord sur un coin : de quoi produire un consensus a evaluer."""
    votes = tuple(
        LeaderVote(wallet=f"0xwallet{i}", coin=coin, side=side, score=1.0, observed_at_ms=now_ms)
        for i in range(3)
    )
    prices = (PriceEvent(source="hyperliquid", coin=coin, bid=99.95, ask=100.05, event_time_ms=now_ms),)
    return FusionRuntimeInput(
        session_id="test-refus-silencieux",
        leader_votes=votes,
        price_events=prices,
        funding_rows=(),
        triangular_edges=(),
        latencies_ms=(10,),
    )


def test_le_refus_du_moteur_paper_ARRIVE_dans_no_trade_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le verrou d'edge empirique refuse -> son motif DOIT etre journalise.

    C'est LE test du bug. Sans le correctif, `no_trade_reasons` ne contient pas le motif
    du moteur et le dashboard affiche « aucun refus enregistre » alors que TOUT est refuse.
    """
    # Verrou actif + table de calibration introuvable => refus deny-by-default garanti.
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "1")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", "runtime/calibration/_inexistant_.json")

    result = run_fusion_strategy_runtime(_payload())

    refus_moteur = tuple(result.paper_engine.refusal_reasons)
    assert refus_moteur, (
        "Le moteur devait refuser (verrou d'edge actif, calibration absente). "
        "S'il n'a pas refuse, le deny-by-default est casse -- c'est PIRE que le bug de trace."
    )

    manquants = [motif for motif in refus_moteur if motif not in result.no_trade_reasons]
    assert not manquants, (
        "REGRESSION : des motifs de refus du moteur paper n'apparaissent PAS dans "
        f"no_trade_reasons -> {manquants}. Le dashboard affichera « aucun refus enregistre » "
        "pendant que le bot refuse tout. Un refus invisible est un bug."
    )


def test_aucun_ordre_paper_ouvert_quand_le_moteur_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Corollaire : le refus doit etre VRAI, pas seulement affiche."""
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "1")
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", "runtime/calibration/_inexistant_.json")

    result = run_fusion_strategy_runtime(_payload())

    assert result.paper_engine.accepted_count == 0
    ouvertures = [
        order for order in result.paper_orders
        if "OPEN" in str(getattr(order, "action", "")).upper()
    ]
    assert not ouvertures, "Le moteur refuse mais ouvre quand meme : incoherence grave."


def test_le_merge_des_refus_ne_peut_pas_etre_RE_ENTERRE() -> None:
    """Garde structurel (AST) : quelqu'un qui supprime le merge fait ECHOUER ce test.

    Le meme bug de cablage s'est deja produit DEUX fois sur les pollers (funding le 08/07,
    carnet L2 le 12/07) : une capacite presente, un point de branchement absent, et personne
    ne se plaint. On verrouille par un test structurel, pas par la memoire humaine.
    """
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fonction = next(
        (n for n in ast.walk(arbre)
         if isinstance(n, ast.FunctionDef) and n.name == "run_fusion_strategy_runtime"),
        None,
    )
    assert fonction is not None, "run_fusion_strategy_runtime a disparu"

    corps = ast.unparse(fonction)
    assert "paper_engine.refusal_reasons" in corps, (
        "Le merge des refus du moteur paper dans `no_trade` a ete SUPPRIME de "
        "run_fusion_strategy_runtime. Les refus redeviendraient invisibles au dashboard."
    )
    assert "no_trade.append" in corps, "Le merge n'alimente plus `no_trade`."
