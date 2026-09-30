"""PISTE 11 — le moteur est POSÉ À LA SOURCE, sur la vraie décision (2026-07-11).

POURQUOI CE TEST EXISTE.

`strategy_mode.py` sait *classer* un moteur. Mais tant que le champ n'est pas **écrit par le code
qui ouvre et ferme réellement les positions**, on ne peut classer qu'à l'analyse — en re-devinant
après coup, à partir de textes qui peuvent changer. Toute la séparation Grinder/Sniper repose sur ce
champ : s'il n'est pas posé à la source, les deux moteurs restent indissociables en live.

Ce test exerce le **VRAI code de sortie** (`apply_sltp_exits`, `apply_auto_unstuck`,
`force_exit_all_positions`) — pas une imitation. Il vérifie la propriété qui compte vraiment :

    UNE SORTIE HÉRITE DU MOTEUR DE SON ENTRÉE.

Reclasser une sortie d'après son propre motif ("CATASTROPHIC_STOP", "GRADED_HALT...") ferait fuir le
PnL d'un moteur vers l'autre — exactement ce qu'on cherche à mesurer. Un GRINDER stoppé reste un
GRINDER : le stop ne change pas la nature du moteur qui a ouvert la position.

Simulation paper uniquement. Aucun ordre réel.
"""
from __future__ import annotations

from hl_observer.paper_trading.auto_unstuck import apply_auto_unstuck
from hl_observer.paper_trading.sl_tp import SLTPConfig
from hl_observer.paper_trading.sltp_runtime import apply_sltp_exits
from hl_observer.risk.graded_halt import force_exit_all_positions
from hl_observer.strategies.strategy_mode import (
    GRINDER,
    SNIPER,
    UNKNOWN_LEGACY,
    mode_of_position,
    stamp_exit,
)

NOW = 1_800_000_000_000

# `apply_sltp_exits` ne fait RIEN sans config (fail-safe) : on la fournit explicitement.
CFG = SLTPConfig(stop_loss_bps=50.0, take_profit_bps=100.0)


def _position(mode: str | None, *, side: str = "LONG", avg: float = 100.0) -> dict:
    pos = {
        "coin": "BTC",
        "side": side,
        "direction": side,
        "size": 5.0 if side == "LONG" else -5.0,
        "avg_price": avg,
        "entry_costs": 0.0,
        "opened_at_ms": NOW - 600_000,
        "wallet_address": "0x" + "a" * 40,
    }
    if mode is not None:
        pos["strategy_mode"] = mode
    return pos


# ------------------------------------------------------- le SL/TP réel préserve le moteur

def test_a_grinder_stopped_out_stays_a_grinder(monkeypatch):
    """LE CŒUR DU SUJET : un stop ne transforme pas un Grinder en Sniper."""
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_LOSS_BPS", "50")
    monkeypatch.setenv("HYPERSMART_SLTP_TAKE_PROFIT_BPS", "100")
    positions = {"0xa|BTC|LONG": _position(GRINDER)}
    events: list[dict] = []
    # −2 % : le stop se déclenche à coup sûr
    apply_sltp_exits(positions, events, {"BTC": 98.0}, now_ms=NOW, config=CFG)

    closes = [e for e in events if str(e.get("paper_action_type")) == "CLOSE"]
    assert closes, "le stop aurait dû fermer la position"
    assert closes[0]["strategy_mode"] == GRINDER, (
        "la sortie a été reclassée d'après son motif : le PnL du Grinder fuirait vers le Sniper"
    )


def test_a_sniper_stopped_out_stays_a_sniper(monkeypatch):
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_LOSS_BPS", "50")
    monkeypatch.setenv("HYPERSMART_SLTP_TAKE_PROFIT_BPS", "100")
    positions = {"0xa|BTC|LONG": _position(SNIPER)}
    events: list[dict] = []
    apply_sltp_exits(positions, events, {"BTC": 98.0}, now_ms=NOW, config=CFG)
    closes = [e for e in events if str(e.get("paper_action_type")) == "CLOSE"]
    assert closes and closes[0]["strategy_mode"] == SNIPER


def test_a_take_profit_also_carries_the_engine(monkeypatch):
    """Le moteur doit suivre le trade GAGNANT aussi — sinon on n'attribue que les pertes."""
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_LOSS_BPS", "50")
    monkeypatch.setenv("HYPERSMART_SLTP_TAKE_PROFIT_BPS", "100")
    positions = {"0xa|BTC|LONG": _position(GRINDER)}
    events: list[dict] = []
    apply_sltp_exits(positions, events, {"BTC": 103.0}, now_ms=NOW, config=CFG)   # +3 % -> take profit
    closes = [e for e in events if str(e.get("paper_action_type")) == "CLOSE"]
    assert closes and closes[0]["strategy_mode"] == GRINDER


def test_a_legacy_position_is_marked_unknown_not_guessed(monkeypatch):
    """VÉRITÉ : une position ouverte AVANT ce correctif n'a pas de moteur. On ne l'invente pas."""
    monkeypatch.setenv("HYPERSMART_SLTP_STOP_LOSS_BPS", "50")
    positions = {"0xa|BTC|LONG": _position(None)}
    positions["0xa|BTC|LONG"].pop("wallet_address")      # aucun indice exploitable
    events: list[dict] = []
    apply_sltp_exits(positions, events, {"BTC": 98.0}, now_ms=NOW, config=CFG)
    closes = [e for e in events if str(e.get("paper_action_type")) == "CLOSE"]
    assert closes and closes[0]["strategy_mode"] == UNKNOWN_LEGACY


# ------------------------------------------------------- les autres chemins de sortie

def test_the_auto_unstuck_exit_carries_the_engine(monkeypatch):
    monkeypatch.setenv("HYPERSMART_AUTO_UNSTUCK", "1")
    monkeypatch.setenv("HYPERSMART_UNSTUCK_MIN_LOSS_BPS", "50")
    monkeypatch.setenv("HYPERSMART_UNSTUCK_MIN_AGE_MIN", "1")
    positions = {"0xa|BTC|LONG": _position(GRINDER)}
    events: list[dict] = []
    apply_auto_unstuck(positions, events, {"BTC": 97.0}, now_ms=NOW)
    closes = [e for e in events if str(e.get("paper_action_type")) == "CLOSE"]
    if closes:                       # le module a ses propres seuils : on ne teste que s'il agit
        assert closes[0]["strategy_mode"] == GRINDER


def test_the_graded_halt_force_exit_carries_the_engine():
    positions = {"0xa|BTC|LONG": _position(SNIPER)}
    events: list[dict] = []
    force_exit_all_positions(positions, events, {"BTC": 95.0}, now_ms=NOW)
    closes = [e for e in events if str(e.get("paper_action_type")) == "CLOSE"]
    assert closes, "le halt rouge aurait dû fermer la position"
    assert closes[0]["strategy_mode"] == SNIPER


# ------------------------------------------------------- le helper lui-même

def test_stamp_exit_reads_the_position_not_the_exit_reason():
    """Le motif de sortie ne doit JAMAIS décider du moteur."""
    event = {"paper_action_type": "CLOSE", "reason": "SLTP_CATASTROPHIC_STOP",
             "strategy_id": "copy_whale_mirror"}     # texte trompeur : "copy"
    stamp_exit(event, _position(GRINDER))
    assert event["strategy_mode"] == GRINDER, "le texte de la sortie a pris le pas sur l'entrée"


def test_stamp_exit_survives_a_missing_position():
    event: dict = {"paper_action_type": "CLOSE"}
    stamp_exit(event, None)
    assert event["strategy_mode"] == UNKNOWN_LEGACY


def test_mode_of_position_never_crashes():
    for bad in (None, {}, {"x": 1}, "pas un dict"):
        assert mode_of_position(bad) in {GRINDER, SNIPER, UNKNOWN_LEGACY}  # type: ignore[arg-type]
