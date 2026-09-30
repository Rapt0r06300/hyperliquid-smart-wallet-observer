"""LE PnL PAR MOTEUR EST-IL VRAIMENT BRANCHÉ ? (2026-07-11)

Un module qui passe ses tests mais que personne n'appelle ne sert à RIEN. Le projet a déjà eu ce
problème (`docs/audit/ORPHAN_MODULES_AUDIT`) : des briques testées, jamais câblées.

Ce test exerce la vraie fonction de projection du ledger utilisée par le statut, et vérifie que
la séparation Grinder/Sniper y apparaît réellement — donc dans le dashboard et l'audit.

Aucun ordre réel.
"""
from __future__ import annotations

from hl_observer.strategies.strategy_mode import GRINDER, SNIPER
from hl_observer.ui.status_routes import _paper_ledger_projection_from_status_state


class _State:
    """État minimal : on ne construit pas un serveur pour vérifier une projection."""

    def __init__(self, events: list[dict]) -> None:
        self.simulation_ledger_events = events
        self.simulation_realized_pnl_usdc = sum(
            float(e.get("estimated_net_pnl_usdc") or 0.0)
            for e in events
            if str(e.get("paper_action_type") or "").upper() == "CLOSE"
        )
        self.simulation_entry_costs_paid_usdc = 0.0
        self.simulation_exit_costs_paid_usdc = 0.0
        self.simulation_equity_history: list[dict] = []
        self.simulation_virtual_positions: dict = {}


def _close(mode: str, net: float) -> dict:
    return {
        "paper_action_type": "CLOSE",
        "strategy_mode": mode,
        "coin": "BTC",
        "leader_side": "LONG",
        "estimated_net_pnl_usdc": net,
        "gross_pnl_usdc": net,
        "fee_cost_usdc": 0.30,
    }


def _projeter(events: list[dict]) -> dict:
    """La vraie fonction du statut, appelee comme le fait le serveur (arguments nommes)."""
    return _paper_ledger_projection_from_status_state(
        state=_State(events),
        starting_equity_usdt=1000.0,
        marked={},
        current_ms=1_800_000_000_000,
    )


def test_the_status_projection_exposes_both_engines_separately():
    """LE CÂBLAGE. Si ce champ disparaît, les deux moteurs redeviennent indiscernables en live."""
    projection = _projeter([_close(GRINDER, +4.0), _close(SNIPER, -9.0)])

    assert "pnl_par_moteur" in projection, "le PnL par moteur n'est PAS exposé : module orphelin"
    moteurs = projection["pnl_par_moteur"]["moteurs"]
    assert moteurs[GRINDER]["pnl_net_usdc"] == 4.0
    assert moteurs[SNIPER]["pnl_net_usdc"] == -9.0
    assert moteurs[SNIPER]["trades"] == 1


def test_an_idle_engine_is_shouted_not_hidden():
    """Un moteur qui ne trade pas doit être NOMMÉ dans le statut — pas absent en silence."""
    projection = _projeter([_close(SNIPER, -2.0)])
    assert GRINDER in projection["pnl_par_moteur"]["moteurs_inactifs"]


def test_the_projection_survives_an_empty_ledger():
    """État vide honnête : pas de plantage, pas de chiffre inventé."""
    projection = _projeter([])
    rapport = projection["pnl_par_moteur"]
    assert rapport["trades_total"] == 0
    assert rapport["pnl_net_total_usdc"] == 0.0
    assert rapport["real_execution"] is False


def test_the_projection_stays_read_only():
    """Le rapport ne doit RIEN pouvoir déclencher : il décrit, il n'agit pas."""
    projection = _projeter([_close(GRINDER, 1.0)])
    rapport = projection["pnl_par_moteur"]
    assert rapport["paper_only"] is True
    assert rapport["real_execution"] is False
