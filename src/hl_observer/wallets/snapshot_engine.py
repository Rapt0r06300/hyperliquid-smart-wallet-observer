from __future__ import annotations

import itertools
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
    Grandmaster Delta Detector.
    Advanced reconciliation using subset-sum analysis and weighted entropy scoring.
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
    ) -> PositionDeltaRecord:
        delta_size = new_size - previous_size
        previous_side = position_side(previous_size)
        new_side = position_side(new_size)

        # Initial action classification
        action = classify_action(previous_size, new_size)

        scorecard: dict[str, bool | None] = {
            "delta_vs_fills_exact": None,
            "delta_vs_fills_subset": None,
            "dir_vs_side": None,
            "start_pos_consistency": None,
            "closed_pnl_consistency": None,
            "side_consistency": None,
            "size_matching": None,
            "price_validity": None,
            "temporal_order": None,
            "state_alignment": None,
            "market_price_sanity": None
        }

        # Weights for confidence scoring
        weights = {
            "delta_vs_fills_exact": 3.0,
            "delta_vs_fills_subset": 2.0,
            "dir_vs_side": 1.0,
            "start_pos_consistency": 2.0,
            "closed_pnl_consistency": 1.5,
            "side_consistency": 1.0,
            "size_matching": 1.0,
            "price_validity": 0.5,
            "temporal_order": 0.5,
            "state_alignment": 1.0,
            "market_price_sanity": 0.5
        }

        warnings: list[str] = []
        source_evidence: dict[str, Any] = {
            "previous_size": previous_size,
            "new_size": new_size,
            "delta_size": delta_size,
            "scorecard": scorecard
        }

        # 10. State Alignment
        scorecard["state_alignment"] = True
        if previous_side == PositionSide.FLAT and action in {PositionAction.REDUCE, PositionAction.CLOSE}:
            scorecard["state_alignment"] = False
            warnings.append("impossible_reduction_from_flat")

        if fills:
            # Pre-filter fills for the specific coin
            coin_fills = [f for f in fills if fill_coin(f) == coin.upper()]

            # Subset-Sum Reconciler (Advanced)
            # Find if any subset of fills exactly matches the delta_size
            best_subset: list[dict[str, Any]] | None = None
            total_signed_all = 0.0

            signed_fills_list = []
            for f in coin_fills:
                sf = signed_fill_size(f)
                if sf is not None:
                    signed_fills_list.append((sf, f))
                    total_signed_all += sf

            # Exact match check
            if abs(total_signed_all - delta_size) < 1e-7:
                best_subset = coin_fills
                scorecard["delta_vs_fills_exact"] = True
            else:
                scorecard["delta_vs_fills_exact"] = False
                # Try subsets (limit to small N for performance)
                if 1 < len(signed_fills_list) <= 10:
                    for r in range(1, len(signed_fills_list)):
                        for combo in itertools.combinations(signed_fills_list, r):
                            combo_sum = sum(x[0] for x in combo)
                            if abs(combo_sum - delta_size) < 1e-7:
                                best_subset = [x[1] for x in combo]
                                scorecard["delta_vs_fills_subset"] = True
                                warnings.append(f"matched_subset_of_{r}_fills_out_of_{len(signed_fills_list)}")
                                break
                        if best_subset: break

            reconciliation_fills = best_subset if best_subset else coin_fills

            # Multi-fill aggregation for the chosen subset
            total_signed_fill = 0.0
            total_sz = 0.0
            weighted_price_sum = 0.0
            start_pos_from_fills: float | None = None
            total_closed_pnl = 0.0
            has_closed_pnl = False
            fill_timestamps = []

            for fill in reconciliation_fills:
                s_f = signed_fill_size(fill) or 0.0
                sz_f = fill_size(fill) or 0.0
                px_f = fill_price(fill) or 0.0
                total_signed_fill += s_f
                total_sz += sz_f
                weighted_price_sum += px_f * sz_f

                sp_f = start_position(fill)
                if sp_f is not None and start_pos_from_fills is None:
                    start_pos_from_fills = sp_f

                cpnl = first_present(fill, "closedPnl", "closed_pnl")
                if cpnl is not None:
                    total_closed_pnl += float(cpnl)
                    has_closed_pnl = True
                fill_timestamps.append(fill_timestamp(fill))

            avg_price = weighted_price_sum / total_sz if total_sz > 0 else None
            max_ts = max(fill_timestamps) if fill_timestamps else 0

            source_evidence.update({
                "fills_processed": len(coin_fills),
                "fills_reconciled": len(reconciliation_fills),
                "total_signed_fill": total_signed_fill,
                "total_sz": total_sz,
                "avg_price": avg_price,
                "total_closed_pnl": total_closed_pnl if has_closed_pnl else None,
                "max_ts": max_ts
            })

            # 2. Dir vs Side
            if (total_signed_fill > 0 and delta_size > 0) or (total_signed_fill < 0 and delta_size < 0):
                scorecard["dir_vs_side"] = True
            elif abs(delta_size) < 1e-7 and abs(total_signed_fill) < 1e-7:
                scorecard["dir_vs_side"] = True
            else:
                scorecard["dir_vs_side"] = False

            # 3. startPosition Consistency
            if start_pos_from_fills is not None:
                scorecard["start_pos_consistency"] = abs(start_pos_from_fills - previous_size) < 1e-7

            # 4. closedPnl Consistency
            if has_closed_pnl:
                if total_closed_pnl != 0 and action not in {PositionAction.REDUCE, PositionAction.CLOSE, PositionAction.FLIP}:
                    scorecard["closed_pnl_consistency"] = False
                    warnings.append("unexpected_closed_pnl_in_aggregate")
                else:
                    scorecard["closed_pnl_consistency"] = True

            # 5. Side Consistency
            scorecard["side_consistency"] = scorecard["dir_vs_side"]

            # 6. Size matching
            scorecard["size_matching"] = abs(total_sz - abs(delta_size)) < 1e-7 if action != PositionAction.FLIP else None

            # 7. Price validity
            scorecard["price_validity"] = avg_price is not None and avg_price > 0

            # 8. Temporal order
            if context_ts is not None and max_ts > 0:
                scorecard["temporal_order"] = max_ts >= context_ts
            else:
                scorecard["temporal_order"] = max_ts > 0

            # 11. Market Price Sanity
            if mid_price is not None and avg_price is not None:
                deviation = abs(avg_price - mid_price) / mid_price
                scorecard["market_price_sanity"] = deviation < 0.05
                if not scorecard["market_price_sanity"]:
                    warnings.append(f"price_deviation_high: {deviation:.2%}")

            # --- GRANDMASTER WEIGHTED CONFIDENCE ---
            # Use dynamic denominator: only count weights for proofs where evidence was present
            total_possible_weight = 0.0
            earned_weight = 0.0
            negatives = []

            for k, v in scorecard.items():
                if v is not None:
                    # special case: exact and subset are mutually exclusive for the same delta dimension
                    # we only count the highest possible weight for this dimension
                    if k == "delta_vs_fills_subset" and scorecard["delta_vs_fills_exact"] is not None:
                        continue

                    total_possible_weight += weights[k]
                    if v is True:
                        earned_weight += weights[k]
                    elif v is False:
                        # entropy check: if exact fails but subset matches, it's NOT a hard negative
                        if k == "delta_vs_fills_exact" and scorecard["delta_vs_fills_subset"]:
                            earned_weight += weights["delta_vs_fills_subset"] # Earn subset points instead
                            continue
                        negatives.append(k)

            confidence_pct = earned_weight / total_possible_weight if total_possible_weight > 0 else 0

            if negatives:
                confidence = ConfidenceLevel.UNKNOWN
                action = PositionAction.UNKNOWN
                reason = f"contradiction_detected: {negatives}"
                warnings.append(f"failed_proofs: {negatives}")
            elif confidence_pct >= 0.85:
                confidence = ConfidenceLevel.HIGH
                reason = f"grandmaster_high_confidence: {confidence_pct:.0%}"
            elif confidence_pct >= 0.45:
                confidence = ConfidenceLevel.MEDIUM
                reason = f"grandmaster_medium_confidence: {confidence_pct:.0%}"
            else:
                confidence = ConfidenceLevel.UNKNOWN
                reason = f"insufficient_evidence_score: {confidence_pct:.0%}"

            final_price = avg_price
            final_ts = max_ts
            final_sz = total_sz
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

            final_price = None
            final_ts = None
            final_sz = None

        # Special rule for Flip
        if action == PositionAction.FLIP:
            confidence = ConfidenceLevel.UNKNOWN
            reason = "flip_detected_as_unknown"
            action = PositionAction.UNKNOWN

        # Final check for paper eligibility
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
        if reason: all_notes.append(reason)
        if not is_paper_eligible: all_notes.append("NOT_PAPER_ELIGIBLE")

        delta_notional = abs(delta_size) * final_price if final_price is not None else None

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
            exchange_ts=final_ts,
            price=final_price,
            fill_size=final_sz,
            confidence_score=confidence_score,
            confidence_level=confidence,
            warnings=warnings,
            reason=reason,
            source_evidence=source_evidence,
            notes=all_notes,
            raw=fills[0] if fills else {"previous_size": previous_size, "new_size": new_size}
        )
