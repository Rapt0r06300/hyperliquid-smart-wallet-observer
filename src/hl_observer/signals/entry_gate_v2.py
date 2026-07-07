"""R5/R6/R7/R8 — Gate d'entree unifie et trace (une seule decision).

Compose en un verdict : fraicheur, edge net apres couts, liquidite, calibration,
confirmation OBI, fill confirme (jamais openOrder), et consensus multi-wallet
(conflit -> NO_TRADE). Couche de decision pure : consomme des signaux deja calcules
par freshness/edge/features/scoring en amont. Aucune action reelle.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EntryGateInputs:
    signal_freshness_score: float          # 0..1 (0 = stale)
    edge_net_bps: float                    # apres couts
    min_edge_bps: float = 30.0
    liquidity_ok: bool = True
    calibrated: bool = True                 # bucket de confiance calibre
    obi_confirms: bool = True               # order book imbalance dans le sens
    require_obi: bool = False
    fill_confirmed: bool = True             # fill reel, pas un openOrder
    leader_consensus: int = 1               # nb de wallets d'accord
    min_consensus: int = 1
    conflict: bool = False                  # signaux leaders contradictoires


@dataclass(frozen=True, slots=True)
class EntryVerdict:
    accepted: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def no_trade(self) -> bool:
        return not self.accepted


def evaluate_entry_gate(inp: EntryGateInputs) -> EntryVerdict:
    reasons: list[str] = []
    if inp.signal_freshness_score <= 0.0:
        reasons.append("STALE_SIGNAL")
    if not inp.fill_confirmed:
        reasons.append("OPEN_ORDER_NOT_A_FILL")     # un openOrder n'est pas un fill
    if inp.conflict:
        reasons.append("LEADER_CONFLICT_NO_TRADE")
    if inp.leader_consensus < inp.min_consensus:
        reasons.append(f"CONSENSUS_TOO_LOW<{inp.min_consensus}")
    if inp.edge_net_bps < inp.min_edge_bps:
        reasons.append(f"EDGE_TOO_LOW<{inp.min_edge_bps:.1f}bps")
    if not inp.liquidity_ok:
        reasons.append("LIQUIDITY_TOO_LOW")
    if not inp.calibrated:
        reasons.append("NOT_CALIBRATED")
    if inp.require_obi and not inp.obi_confirms:
        reasons.append("OBI_NOT_CONFIRMING")
    return EntryVerdict(accepted=(len(reasons) == 0), reasons=tuple(reasons))


__all__ = ["EntryGateInputs", "EntryVerdict", "evaluate_entry_gate"]
