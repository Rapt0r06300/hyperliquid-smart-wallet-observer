from __future__ import annotations

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
    Advanced Professional Delta Detector.
    Uses a Nine-Proof Scorecard to cross-verify position changes with fill data.
    """

    def detect(
        self,
        wallet_address: str,
        coin: str,
        previous_size: float,
        new_size: float,
        fill: dict[str, Any] | None = None,
        context_ts: int | None = None,
    ) -> PositionDeltaRecord:
        delta_size = new_size - previous_size
        previous_side = position_side(previous_size)
        new_side = position_side(new_size)

        # Initial action classification
        action = classify_action(previous_size, new_size)

        scorecard: dict[str, bool | None] = {
            "signed_delta_vs_fill": None,
            "dir_vs_side": None,
            "start_pos_consistency": None,
            "closed_pnl_consistency": None,
            "side_consistency": None,
            "size_matching": None,
            "price_validity": None,
            "temporal_order": None,
            "state_alignment": None
        }

        warnings: list[str] = []
        source_evidence: dict[str, Any] = {
            "previous_size": previous_size,
            "new_size": new_size,
            "delta_size": delta_size,
            "scorecard": scorecard
        }

        # 9. State Alignment (Is the detected action logically possible from previous state?)
        scorecard["state_alignment"] = True
        if previous_side == PositionSide.FLAT and action in {PositionAction.REDUCE, PositionAction.CLOSE}:
            scorecard["state_alignment"] = False
            warnings.append("impossible_reduction_from_flat")

        if fill:
            # Extract fill data
            s_fill = signed_fill_size(fill)
            sz = fill_size(fill)
            px = fill_price(fill)
            ts = fill_timestamp(fill)
            start_pos = start_position(fill)
            closed_pnl = first_present(fill, "closedPnl", "closed_pnl")
            direction = str(first_present(fill, "dir", "direction") or "").lower()
            side_str = str(first_present(fill, "side") or "").lower()

            source_evidence.update({
                "fill": fill,
                "s_fill": s_fill,
                "sz": sz,
                "px": px,
                "ts": ts,
                "start_pos": start_pos,
                "closed_pnl": closed_pnl,
                "direction": direction,
                "side_str": side_str
            })

            # 1. Signed Delta vs Fill
            if s_fill is not None:
                scorecard["signed_delta_vs_fill"] = abs(s_fill - delta_size) < 1e-8

            # 2. Fill direction (dir) vs Position Side
            if direction:
                is_opening = "open" in direction
                is_closing = "close" in direction
                if is_opening and action not in {PositionAction.OPEN, PositionAction.ADD, PositionAction.FLIP}:
                    scorecard["dir_vs_side"] = False
                elif is_closing and action not in {PositionAction.REDUCE, PositionAction.CLOSE, PositionAction.FLIP}:
                    scorecard["dir_vs_side"] = False
                else:
                    scorecard["dir_vs_side"] = True

            # 3. startPosition Consistency
            if start_pos is not None:
                scorecard["start_pos_consistency"] = abs(start_pos - previous_size) < 1e-8

            # 4. closedPnl Consistency
            if closed_pnl is not None:
                has_pnl = float(closed_pnl) != 0
                if has_pnl and action not in {PositionAction.REDUCE, PositionAction.CLOSE, PositionAction.FLIP}:
                    scorecard["closed_pnl_consistency"] = False
                    warnings.append("unexpected_closed_pnl")
                else:
                    scorecard["closed_pnl_consistency"] = True

            # 5. Side Consistency (Buy/Sell)
            if side_str:
                is_buy = side_str in {"b", "buy", "bid"}
                is_sell = side_str in {"a", "s", "sell", "ask"}
                if (is_buy and delta_size < 0) or (is_sell and delta_size > 0):
                    scorecard["side_consistency"] = False
                else:
                    scorecard["side_consistency"] = True

            # 6. Size matching
            if sz is not None:
                scorecard["size_matching"] = abs(sz - abs(delta_size)) < 1e-8

            # 7. Price validity
            scorecard["price_validity"] = px is not None and px > 0

            # 8. Temporal order
            if context_ts is not None and ts > 0:
                scorecard["temporal_order"] = ts >= context_ts
            else:
                scorecard["temporal_order"] = ts > 0

            # --- CONFIDENCE CALCULATION ---
            positives = [v for k, v in scorecard.items() if v is True]
            negatives = [v for k, v in scorecard.items() if v is False]

            if negatives:
                confidence = ConfidenceLevel.UNKNOWN
                action = PositionAction.UNKNOWN
                failed_keys = [k for k, v in scorecard.items() if v is False]
                reason = f"contradiction_detected: {failed_keys}"
                warnings.append(f"failed_proofs: {failed_keys}")
            elif len(positives) >= 5: # Threshold for high confidence
                confidence = ConfidenceLevel.HIGH
                reason = "multiple_proofs_confirmed"
            else:
                confidence = ConfidenceLevel.MEDIUM
                reason = "insufficient_proofs_for_high_confidence"

        else:
            # Case: Position change but NO fill evidence
            if abs(delta_size) > 1e-8:
                confidence = ConfidenceLevel.MEDIUM
                reason = "position_change_without_fill"
                warnings.append("missing_fill_evidence")
            else:
                confidence = ConfidenceLevel.HIGH
                action = PositionAction.UNKNOWN
                reason = "no_change_detected"

        # Special rule for Flip
        if action == PositionAction.FLIP:
            # A Flip is complex, marks as UNKNOWN for safety unless we split it later
            confidence = ConfidenceLevel.UNKNOWN
            reason = "flip_detected_as_unknown"
            action = PositionAction.UNKNOWN

        # Final check for paper eligibility
        # Requirement: "si données insuffisantes : aucun paper intent"
        is_paper_eligible = confidence in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM}
        if confidence == ConfidenceLevel.UNKNOWN or not scorecard["state_alignment"]:
             is_paper_eligible = False

        # Backward compatibility
        confidence_score = 0.0
        if confidence == ConfidenceLevel.HIGH:
            confidence_score = 1.0
        elif confidence == ConfidenceLevel.MEDIUM:
            confidence_score = 0.65

        all_notes = list(warnings)
        if reason:
            all_notes.append(reason)
        if not is_paper_eligible:
            all_notes.append("NOT_PAPER_ELIGIBLE")

        price = fill_price(fill) if fill else None
        delta_notional = abs(delta_size) * price if price is not None else None

        return PositionDeltaRecord(
            wallet_address=wallet_address,
            coin=coin,
            previous_side=previous_side,
            new_side=new_side,
            previous_size=previous_size,
            new_size=new_size,
            delta_size=delta_size,
            delta_notional_usdc=delta_notional,
            action=action,
            exchange_ts=fill_timestamp(fill) if fill else None,
            price=price,
            fill_size=fill_size(fill) if fill else None,
            side=first_present(fill, "side") if fill else None,
            confidence_score=confidence_score,
            confidence_level=confidence,
            warnings=warnings,
            reason=reason,
            source_evidence=source_evidence,
            notes=all_notes,
            raw=fill if fill else {"previous_size": previous_size, "new_size": new_size}
        )
