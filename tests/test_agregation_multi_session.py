"""AUD-063 — agregation ECONOMIQUE cross-session (PLUSIEURS sessions distinctes).

L'infra cumulative existe (decision_replay_analyzer agrege l'append-only ledger, forward_frozen
recharge des obs inter-sessions), MAIS l'analyse phare (analyser_session, lab_alpha) est
MONO-session : aucun test ne prouvait qu'un run couvrant PLUSIEURS sessions distinctes combine
bien leur economie (PnL/frais/compteurs = SOMME des sessions, pas une seule).

Ces tests fabriquent 2 sessions distinctes (chacune son propre append-only ledger sur disque),
les analysent, puis verifient que l'agregat = somme des deux -- jamais une seule.

Donnees de test CLAIRES : PnL fabrique et etiquete comme tel, aucun chiffre presente comme reel.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.simulation.decision_replay_analyzer import (
    aggregate_decision_logs,
    aggregate_replay_analyses,
    analyze_decision_logs,
)

WALLET_A = "0x" + "1" * 40
WALLET_B = "0x" + "2" * 40
WALLET_C = "0x" + "3" * 40


def _ecrire_session(log_dir: Path, rows: list[dict]) -> None:
    """Ecrit UNE session : son propre dossier de logs + append-only ledger."""
    log_dir.mkdir(parents=True)
    (log_dir / "simulation_decisions_append_only.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _session_a(tmp_path: Path) -> Path:
    log_dir = tmp_path / "session_a" / "logs a envoyer"
    _ecrire_session(log_dir, [
        {  # trade papier GAGNANT (donnee de test, pas un PnL reel)
            "timestamp_ms": 1000, "wallet_address": WALLET_A, "coin": "ETH",
            "bot_decision": "PAPER_ENTRY_REPLAYED", "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": 1.50, "fee_cost_usdc": 0.10,
            "execution": "forbidden", "research_only": True,
        },
        {  # refus
            "timestamp_ms": 1100, "wallet_address": WALLET_B, "coin": "BTC",
            "bot_decision": "REJECT_NO_TRADE", "status": "REFUSED",
            "reason": "EDGE_REMAINING_TOO_LOW",
            "estimated_net_pnl_usdc": 0, "fee_cost_usdc": 0,
            "execution": "forbidden", "research_only": True,
        },
    ])
    return log_dir


def _session_b(tmp_path: Path) -> Path:
    log_dir = tmp_path / "session_b" / "logs a envoyer"
    _ecrire_session(log_dir, [
        {  # trade papier PERDANT
            "timestamp_ms": 2000, "wallet_address": WALLET_A, "coin": "ETH",
            "bot_decision": "PAPER_ENTRY_REPLAYED", "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": -0.75, "fee_cost_usdc": 0.05,
            "execution": "forbidden", "research_only": True,
        },
        {  # trade papier GAGNANT sur un autre coin
            "timestamp_ms": 2100, "wallet_address": WALLET_C, "coin": "SOL",
            "bot_decision": "PAPER_ENTRY_REPLAYED", "status": "LOCAL_REPLAY",
            "estimated_net_pnl_usdc": 2.00, "fee_cost_usdc": 0.20,
            "execution": "forbidden", "research_only": True,
        },
        {  # refus (meme raison que session A -> doit se cumuler)
            "timestamp_ms": 2200, "wallet_address": WALLET_B, "coin": "BTC",
            "bot_decision": "REJECT_NO_TRADE", "status": "REFUSED",
            "reason": "EDGE_REMAINING_TOO_LOW",
            "estimated_net_pnl_usdc": 0, "fee_cost_usdc": 0,
            "execution": "forbidden", "research_only": True,
        },
    ])
    return log_dir


def test_agregat_combine_les_deux_sessions_pas_une_seule(tmp_path):
    dir_a = _session_a(tmp_path)
    dir_b = _session_b(tmp_path)

    a = analyze_decision_logs(dir_a)
    b = analyze_decision_logs(dir_b)
    agg = aggregate_replay_analyses([a, b])

    # --- pre-conditions : les deux sessions sont bien distinctes et non vides
    assert a.event_count == 2 and b.event_count == 3
    assert a.total_estimated_pnl_usdc == 1.50
    assert round(b.total_estimated_pnl_usdc, 8) == 1.25

    # --- l'agregat = SOMME des deux, strictement > chacune (donc les DEUX sont dedans)
    assert agg.event_count == a.event_count + b.event_count == 5
    assert agg.event_count > a.event_count and agg.event_count > b.event_count
    assert agg.accepted_count == a.accepted_count + b.accepted_count == 3
    assert agg.refused_count == a.refused_count + b.refused_count == 2
    assert agg.positive_count == a.positive_count + b.positive_count == 2
    assert agg.negative_count == a.negative_count + b.negative_count == 1

    # --- economie : PnL/frais = somme, jamais une seule session
    assert agg.total_estimated_pnl_usdc == round(
        a.total_estimated_pnl_usdc + b.total_estimated_pnl_usdc, 8) == 2.75
    assert agg.total_estimated_pnl_usdc != a.total_estimated_pnl_usdc
    assert agg.total_estimated_pnl_usdc != b.total_estimated_pnl_usdc
    assert agg.total_fees_usdc == round(a.total_fees_usdc + b.total_fees_usdc, 8) == 0.35

    # --- ETH n'apparait QUE si les deux sessions sont fusionnees : +1.50 (A) + -0.75 (B) = 0.75
    assert agg.pnl_by_coin["ETH"] == 0.75
    assert agg.pnl_by_coin["SOL"] == 2.00               # present uniquement dans B
    assert agg.pnl_by_wallet[WALLET_A] == 0.75          # wallet vu dans A ET B

    # --- compteurs d'action = somme des deux sessions
    assert agg.action_counts["PAPER_ENTRY_REPLAYED"] == 3
    assert agg.action_counts["REJECT_NO_TRADE"] == 2

    # --- raisons de refus : la meme raison des deux sessions se cumule (1 + 1 = 2)
    assert ("EDGE_REMAINING_TOO_LOW", 2) in agg.top_refusal_reasons


def test_aggregate_decision_logs_lit_les_dossiers_et_agrege(tmp_path):
    """Point d'entree multi-session sur DISQUE : lit chaque append-only ledger puis agrege."""
    dir_a = _session_a(tmp_path)
    dir_b = _session_b(tmp_path)

    agg_dirs = aggregate_decision_logs([dir_a, dir_b])
    agg_ref = aggregate_replay_analyses([analyze_decision_logs(dir_a), analyze_decision_logs(dir_b)])

    assert agg_dirs.event_count == 5
    assert agg_dirs.total_estimated_pnl_usdc == 2.75
    assert agg_dirs.total_estimated_pnl_usdc == agg_ref.total_estimated_pnl_usdc
    assert agg_dirs.pnl_by_coin == agg_ref.pnl_by_coin
    assert agg_dirs.action_counts == agg_ref.action_counts


def test_agregat_neutre_et_mono_session(tmp_path):
    """Garde-fous : agregat vide = zero ; agregat d'UNE session = cette session (economie identique)."""
    vide = aggregate_replay_analyses([])
    assert vide.event_count == 0
    assert vide.total_estimated_pnl_usdc == 0.0
    assert vide.pnl_by_coin == {}

    a = analyze_decision_logs(_session_a(tmp_path))
    agg_un = aggregate_replay_analyses([a])
    assert agg_un.event_count == a.event_count
    assert agg_un.total_estimated_pnl_usdc == a.total_estimated_pnl_usdc
    assert agg_un.pnl_by_coin == a.pnl_by_coin
    assert agg_un.top_refusal_reasons == a.top_refusal_reasons
