from __future__ import annotations

from typing import Any

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
    Core of the bot. Detects and classifies position changes with confidence scoring
    based on multiple proofs: position snapshots, fills, start positions, and PnL.
    """

    def detect(
        self,
        wallet_address: str,
        coin: str,
        previous_size: float,
        new_size: float,
        fill: dict[str, Any] | None = None,
    ) -> PositionDeltaRecord:
        delta_size = new_size - previous_size
        previous_side = position_side(previous_size)
        new_side = position_side(new_size)

        # Initial action classification from position change
        action = classify_action(previous_size, new_size)

        is_flip = action == PositionAction.FLIP
        reason = None

        warnings: list[str] = []
        source_evidence: dict[str, Any] = {
            "previous_size": previous_size,
            "new_size": new_size,
            "delta_size": delta_size,
        }

        if fill:
            signed_fill = signed_fill_size(fill)
            start_pos = start_position(fill)
            closed_pnl = first_present(fill, "closedPnl", "closed_pnl")

            source_evidence["fill"] = fill
            source_evidence["signed_fill"] = signed_fill
            source_evidence["start_position_from_fill"] = start_pos
            source_evidence["closed_pnl"] = closed_pnl

            # Cross-referencing logic
            fill_matches_delta = False
            if signed_fill is not None and abs(signed_fill - delta_size) < 1e-8:
                fill_matches_delta = True

            start_pos_matches = False
            if start_pos is not None and abs(start_pos - previous_size) < 1e-8:
                start_pos_matches = True

            # Confirmation rules
            if fill_matches_delta and (start_pos_matches or start_pos is None):
                confidence = ConfidenceLevel.HIGH
                reason = "position_change_confirmed_by_fill"
            elif not fill_matches_delta and signed_fill is not None:
                confidence = ConfidenceLevel.UNKNOWN
                action = PositionAction.UNKNOWN
                reason = "fill_contradicts_position_change"
                warnings.append(f"fill_size={signed_fill} != delta_size={delta_size}")
            else:
                # Some evidence matches but not all, or missing pieces
                confidence = ConfidenceLevel.MEDIUM
                reason = "partial_fill_confirmation" if fill_matches_delta else "unconfirmed_fill_presence"

            # closedPnl check for REDUCE/CLOSE
            if closed_pnl is not None and action not in {PositionAction.REDUCE, PositionAction.CLOSE, PositionAction.UNKNOWN}:
                warnings.append("closed_pnl_present_on_non_reducing_action")
                confidence = ConfidenceLevel.MEDIUM

            # Update delta record fields
            price = fill_price(fill)
            exchange_ts = fill_timestamp(fill)
            fill_sz = fill_size(fill)
            side = first_present(fill, "side")
        else:
            # Case: Position change but no fill evidence
            if abs(delta_size) > 1e-8:
                confidence = ConfidenceLevel.MEDIUM
                reason = "position_change_without_fill"
            else:
                confidence = ConfidenceLevel.HIGH
                action = PositionAction.UNKNOWN # No change
                reason = "no_change_detected"

            price = None
            exchange_ts = None
            fill_sz = None
            side = None

        # Special rule: if flip long/short, mark as UNKNOWN for now as requested
        if is_flip:
            action = PositionAction.UNKNOWN
            confidence = ConfidenceLevel.UNKNOWN
            reason = "flip_detected_as_unknown"

        # Final action adjustment for UNKNOWN
        if action == PositionAction.UNKNOWN and reason != "no_change_detected" and not is_flip:
            confidence = ConfidenceLevel.UNKNOWN

        # Mapping confidence level to score for backward compatibility
        confidence_score = 0.0
        if confidence == ConfidenceLevel.HIGH:
            confidence_score = 1.0
        elif confidence == ConfidenceLevel.MEDIUM:
            confidence_score = 0.65

        # Include reason in notes for rebuilder compatibility
        all_notes = list(warnings)
        if reason:
            all_notes.append(reason)

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
            exchange_ts=exchange_ts,
            price=price,
            fill_size=fill_sz,
            side=side,
            confidence_score=confidence_score,
            confidence_level=confidence,
            warnings=warnings,
            reason=reason,
            source_evidence=source_evidence,
            notes=all_notes, # Keep notes for backward compatibility
            raw=fill if fill else {"previous_size": previous_size, "new_size": new_size}
        )
