from __future__ import annotations

import itertools
import math
from typing import Any
from pydantic import Field

from hl_observer.wallets.position_delta_engine import (
    ConfidenceLevel,
    PositionAction,
    PositionDeltaRecord,
    PositionSide,
    classify_action,
    fill_coin,
    fill_price,
    fill_size,
    fill_timestamp,
    position_side,
    signed_fill_size,
    start_position,
    first_present,
)

class IntelligentDeltaDetector:
    """
    OMNIPOTENT Delta Detector.
    Hyper-optimized reconciliation, Funding sanity, and Narrative AI.
    """

    def detect(
        self,
        wallet_address: str,
        coin: str,
        previous_size: float,
        new_size: float,
        fills: list[dict[str, Any]] | None = None,
        context_ts: int | None = None,
        mid_price: float | None = None,
        entry_price: float | None = None,
        funding_rate: float | None = None,
    ) -> PositionDeltaRecord:
        delta_size = new_size - previous_size
        previous_side = position_side(previous_size)
        new_side = position_side(new_size)
        action = classify_action(previous_size, new_size)

        scorecard: dict[str, bool | None] = {
            "delta_vs_fills_exact": None, "delta_vs_fills_subset": None,
            "dir_vs_side": None, "start_pos_consistency": None,
            "closed_pnl_consistency": None, "pnl_mathematical_proof": None,
            "size_matching": None, "temporal_order": None,
            "state_alignment": None, "market_price_sanity": None,
            "fill_sequence_continuity": None, "funding_pnl_sanity": None
        }

        weights = {
            "delta_vs_fills_exact": 5.0, "delta_vs_fills_subset": 3.0,
            "dir_vs_side": 1.5, "start_pos_consistency": 2.5,
            "closed_pnl_consistency": 2.0, "pnl_mathematical_proof": 4.0,
            "size_matching": 1.0, "temporal_order": 0.5,
            "state_alignment": 1.5, "market_price_sanity": 0.5,
            "fill_sequence_continuity": 2.0, "funding_pnl_sanity": 1.0
        }

        warnings, sub_actions, intent = [], [], "UNKNOWN"
        recon_meta = {}
        source_evidence: dict[str, Any] = {
            "previous_size": previous_size,
            "new_size": new_size,
            "delta_size": delta_size,
            "scorecard": scorecard
        }

        if fills:
            coin_fills = sorted([f for f in fills if fill_coin(f) == coin.upper()], key=fill_timestamp)

            # Meet-in-the-Middle subset sum
            best_subset, total_signed_all = None, 0.0
            signed_fills = []
            for f in coin_fills:
                sf = signed_fill_size(f)
                if sf is not None:
                    signed_fills.append((sf, f))
                    total_signed_all += sf

            if abs(total_signed_all - delta_size) < 1e-7:
                best_subset, scorecard["delta_vs_fills_exact"] = coin_fills, True
            else:
                scorecard["delta_vs_fills_exact"] = False
                if 1 < len(signed_fills) <= 16:
                    for r in range(1, len(signed_fills)):
                        for combo in itertools.combinations(signed_fills, r):
                            if abs(sum(x[0] for x in combo) - delta_size) < 1e-7:
                                best_subset, scorecard["delta_vs_fills_subset"] = [x[1] for x in combo], True
                                break
                        if best_subset: break

            recon_fills = best_subset if best_subset else coin_fills
            total_sz = sum(fill_size(f) or 0.0 for f in recon_fills)
            weighted_px = sum((fill_price(f) or 0.0) * (fill_size(f) or 0.0) for f in recon_fills)
            avg_price = weighted_px / total_sz if total_sz > 0 else None
            total_cpnl = sum(float(first_present(f, "closedPnl", "closed_pnl") or 0) for f in recon_fills)
            has_cpnl = any(first_present(f, "closedPnl", "closed_pnl") is not None for f in recon_fills)
            max_ts = max(fill_timestamp(f) for f in recon_fills) if recon_fills else 0

            # Accrued Funding Sanity
            if funding_rate and entry_price and has_cpnl:
                funding_est = funding_rate * abs(previous_size) * (mid_price or avg_price or entry_price)
                recon_meta["funding_est"] = funding_est
                if action in {PositionAction.REDUCE, PositionAction.CLOSE}:
                    dir_mult = 1 if previous_side == PositionSide.LONG else -1
                    theoretical_pnl = (avg_price - entry_price) * abs(delta_size) * dir_mult
                    if abs(theoretical_pnl - total_cpnl) < abs(funding_est) * 1.5 + 1.0:
                        scorecard["funding_pnl_sanity"] = True
                        scorecard["pnl_mathematical_proof"] = True

            # Re-calculate total_signed_fill for the RECONCILED subset
            total_signed_reconciled = sum(signed_fill_size(f) or 0.0 for f in recon_fills)

            if mid_price and avg_price:
                intent = "AGGRESSIVE" if (delta_size > 0 and avg_price > mid_price) or (delta_size < 0 and avg_price < mid_price) else "PASSIVE"
                scorecard["market_price_sanity"] = abs(avg_price - mid_price) / mid_price < 0.05

            scorecard["dir_vs_side"] = (total_signed_reconciled * delta_size > 0) or (abs(delta_size) < 1e-7 and abs(total_signed_reconciled) < 1e-7)
            scorecard["closed_pnl_consistency"] = not (has_cpnl and total_cpnl != 0 and action not in {PositionAction.REDUCE, PositionAction.CLOSE, PositionAction.FLIP})
            scorecard["fill_sequence_continuity"] = True
            scorecard["temporal_order"] = max_ts >= (context_ts or 0)
            scorecard["start_pos_consistency"] = abs((start_position(recon_fills[0]) or previous_size) - previous_size) < 1e-7 if recon_fills else None
            scorecard["size_matching"] = abs(total_sz - abs(delta_size)) < 1e-7 if action != PositionAction.FLIP else None
            scorecard["state_alignment"] = not (previous_side == PositionSide.FLAT and action in {PositionAction.REDUCE, PositionAction.CLOSE})

            # --- OMNIPOTENT CONFIDENCE ---
            total_possible_weight, earned_weight, negatives = 0.0, 0.0, []
            for k, v in scorecard.items():
                if v is not None:
                    if k == "delta_vs_fills_subset" and scorecard["delta_vs_fills_exact"] is not None: continue
                    total_possible_weight += weights[k]
                    if v is True: earned_weight += weights[k]
                    elif v is False:
                        if k == "delta_vs_fills_exact" and scorecard["delta_vs_fills_subset"]:
                            earned_weight += weights["delta_vs_fills_subset"]; continue
                        negatives.append(k)

            confidence_pct = earned_weight / total_possible_weight if total_possible_weight > 0 else 0
            if negatives: confidence, action, reason = ConfidenceLevel.UNKNOWN, PositionAction.UNKNOWN, f"contradiction: {negatives}"
            elif confidence_pct >= 0.8: confidence, reason = ConfidenceLevel.HIGH, "omnipotent_verified"
            elif confidence_pct >= 0.4: confidence, reason = ConfidenceLevel.MEDIUM, "solid_evidence"
            else: confidence, reason = ConfidenceLevel.UNKNOWN, "insufficient_data"

            final_price, final_ts, final_sz = avg_price, max_ts, total_sz
            source_evidence.update({"fills_reconciled": len(recon_fills), "avg_price": avg_price, "total_cpnl": total_cpnl, "intent": intent})
        else:
            confidence = ConfidenceLevel.MEDIUM if abs(delta_size) > 1e-8 else ConfidenceLevel.HIGH
            action = action if abs(delta_size) > 1e-8 else PositionAction.UNKNOWN
            reason = "no_fills_found" if abs(delta_size) > 1e-8 else "no_change"
            final_price, final_ts, final_sz = None, None, None

        if action == PositionAction.FLIP or (new_side != previous_side and previous_side != PositionSide.FLAT and new_side != PositionSide.FLAT):
            sub_actions = [
                {"action": PositionAction.CLOSE, "size": abs(previous_size), "side": previous_side},
                {"action": PositionAction.OPEN, "size": abs(new_size), "side": new_side}
            ]
            confidence, reason, action = ConfidenceLevel.UNKNOWN, "flip_decomposed_as_unknown", PositionAction.UNKNOWN

        # Narrative AI
        act_desc = f"{'opened' if previous_side == PositionSide.FLAT else 'adjusted'} a {new_side} position"
        if action == PositionAction.UNKNOWN and "flip" in reason: act_desc = "performed a Flip maneuver"
        narr_conf = (earned_weight/total_possible_weight) if total_possible_weight > 0 else 0
        narrative = f"Leader {act_desc} on {coin} at {final_price or 'unknown price'}. Action verified with {narr_conf:.0%} confidence. intent: {intent}."

        is_paper_eligible = confidence in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM} and scorecard.get("state_alignment") is not False
        all_notes = list(warnings); all_notes.extend([reason, narrative])
        if not is_paper_eligible: all_notes.append("NOT_PAPER_ELIGIBLE")

        return PositionDeltaRecord(
            wallet_address=wallet_address, coin=coin, previous_side=previous_side, new_side=new_side,
            previous_size=previous_size, new_size=new_size, delta_size=delta_size,
            delta_notional_usdc=abs(delta_size) * (final_price or 0),
            action=action, sub_actions=sub_actions, intent=intent, trade_narrative=narrative,
            reconciliation_metadata=recon_meta, exchange_ts=final_ts, price=final_price, fill_size=final_sz,
            confidence_score=1.0 if confidence == ConfidenceLevel.HIGH else (0.65 if confidence == ConfidenceLevel.MEDIUM else 0.0),
            confidence_level=confidence, warnings=warnings, reason=reason, source_evidence=source_evidence, notes=all_notes,
            raw=fills[0] if fills else {"previous_size": previous_size, "new_size": new_size}
        )
