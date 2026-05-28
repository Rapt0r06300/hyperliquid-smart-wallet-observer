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
    GOD-MODE Delta Detector.
    Advanced Action Decomposition, PnL Proofs, and Intent Analysis.
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
            "pnl_mathematical_proof": None,
            "size_matching": None,
            "temporal_order": None,
            "state_alignment": None,
            "market_price_sanity": None,
            "fill_sequence_continuity": None
        }

        weights = {
            "delta_vs_fills_exact": 4.0,
            "delta_vs_fills_subset": 2.5,
            "dir_vs_side": 1.5,
            "start_pos_consistency": 2.0,
            "closed_pnl_consistency": 2.0,
            "pnl_mathematical_proof": 3.0,
            "size_matching": 1.0,
            "temporal_order": 0.5,
            "state_alignment": 1.0,
            "market_price_sanity": 0.5,
            "fill_sequence_continuity": 2.0
        }

        warnings: list[str] = []
        sub_actions: list[dict[str, Any]] = []
        intent = "UNKNOWN"
        source_evidence: dict[str, Any] = {
            "previous_size": previous_size,
            "new_size": new_size,
            "delta_size": delta_size,
            "scorecard": scorecard
        }

        if fills:
            coin_fills = sorted([f for f in fills if fill_coin(f) == coin.upper()], key=fill_timestamp)

            # 14. Fill Sequence Continuity
            if len(coin_fills) > 1:
                continuity = True
                for i in range(1, len(coin_fills)):
                    prev_f = coin_fills[i-1]
                    curr_f = coin_fills[i]
                    prev_signed = signed_fill_size(prev_f)
                    curr_start = start_position(curr_f)
                    prev_start = start_position(prev_f)
                    if prev_signed is not None and curr_start is not None and prev_start is not None:
                        expected_curr_start = prev_start + prev_signed
                        if abs(expected_curr_start - curr_start) > 1e-7:
                            continuity = False
                            warnings.append(f"fill_sequence_gap_at_index_{i}")
                scorecard["fill_sequence_continuity"] = continuity

            # Subset-Sum Reconciler
            best_subset: list[dict[str, Any]] | None = None
            total_signed_all = 0.0
            signed_fills_list = []
            for f in coin_fills:
                sf = signed_fill_size(f)
                if sf is not None:
                    signed_fills_list.append((sf, f))
                    total_signed_all += sf

            if abs(total_signed_all - delta_size) < 1e-7:
                best_subset = coin_fills
                scorecard["delta_vs_fills_exact"] = True
            else:
                scorecard["delta_vs_fills_exact"] = False
                if 1 < len(signed_fills_list) <= 12:
                    for r in range(1, len(signed_fills_list)):
                        for combo in itertools.combinations(signed_fills_list, r):
                            if abs(sum(x[0] for x in combo) - delta_size) < 1e-7:
                                best_subset = [x[1] for x in combo]
                                scorecard["delta_vs_fills_subset"] = True
                                break
                        if best_subset: break

            reconciliation_fills = best_subset if best_subset else coin_fills

            # Aggregate stats
            total_sz = sum(fill_size(f) or 0.0 for f in reconciliation_fills)
            weighted_px = sum((fill_price(f) or 0.0) * (fill_size(f) or 0.0) for f in reconciliation_fills)
            avg_price = weighted_px / total_sz if total_sz > 0 else None
            total_cpnl = sum(float(first_present(f, "closedPnl", "closed_pnl") or 0) for f in reconciliation_fills)
            has_cpnl = any(first_present(f, "closedPnl", "closed_pnl") is not None for f in reconciliation_fills)
            max_ts = max(fill_timestamp(f) for f in reconciliation_fills) if reconciliation_fills else 0

            # Intent Analysis
            if mid_price and avg_price:
                # If buying above mid or selling below mid -> AGGRESSIVE (Taker-like)
                is_buy = delta_size > 0
                if (is_buy and avg_price > mid_price) or (not is_buy and avg_price < mid_price):
                    intent = "AGGRESSIVE"
                else:
                    intent = "PASSIVE"

            # 4. Closed PnL Mathematical Proof
            if has_cpnl and entry_price and avg_price and abs(delta_size) > 0:
                # Basic PnL = (exit - entry) * size_closed
                # If delta_size reduces position, size_closed is abs(delta_size)
                # This only works for REDUCE/CLOSE/FLIP(partially)
                if action in {PositionAction.REDUCE, PositionAction.CLOSE}:
                    dir_mult = 1 if previous_side == PositionSide.LONG else -1
                    theoretical_pnl = (avg_price - entry_price) * abs(delta_size) * dir_mult
                    scorecard["pnl_mathematical_proof"] = abs(theoretical_pnl - total_cpnl) < 1.0 # $1 tolerance
                    if not scorecard["pnl_mathematical_proof"]:
                        warnings.append(f"pnl_mismatch: th={theoretical_pnl:.2f} vs real={total_cpnl:.2f}")

            source_evidence.update({
                "fills_reconciled": len(reconciliation_fills),
                "avg_price": avg_price,
                "total_cpnl": total_cpnl if has_cpnl else None,
                "intent": intent
            })

            # Scorecard logic...
            scorecard["start_pos_consistency"] = abs((start_position(reconciliation_fills[0]) or previous_size) - previous_size) < 1e-7 if reconciliation_fills else None
            scorecard["size_matching"] = abs(total_sz - abs(delta_size)) < 1e-7 if action != PositionAction.FLIP else None
            scorecard["market_price_sanity"] = abs(avg_price - mid_price)/mid_price < 0.05 if mid_price and avg_price else True
            scorecard["temporal_order"] = max_ts >= (context_ts or 0)

            # --- GOD-MODE CONFIDENCE ---
            total_possible_weight = 0.0
            earned_weight = 0.0
            negatives = []
            for k, v in scorecard.items():
                if v is not None:
                    if k == "delta_vs_fills_subset" and scorecard["delta_vs_fills_exact"] is not None: continue
                    total_possible_weight += weights[k]
                    if v is True: earned_weight += weights[k]
                    elif v is False:
                        if k == "delta_vs_fills_exact" and scorecard["delta_vs_fills_subset"]:
                            earned_weight += weights["delta_vs_fills_subset"]
                            continue
                        negatives.append(k)

            confidence_pct = earned_weight / total_possible_weight if total_possible_weight > 0 else 0

            if negatives:
                confidence, action, reason = ConfidenceLevel.UNKNOWN, PositionAction.UNKNOWN, f"contradiction: {negatives}"
            elif confidence_pct >= 0.8: confidence, reason = ConfidenceLevel.HIGH, "god_mode_verified"
            elif confidence_pct >= 0.4: confidence, reason = ConfidenceLevel.MEDIUM, "solid_evidence"
            else: confidence, reason = ConfidenceLevel.UNKNOWN, "weak_evidence"

            final_price, final_ts, final_sz = avg_price, max_ts, total_sz
        else:
            confidence = ConfidenceLevel.MEDIUM if abs(delta_size) > 1e-8 else ConfidenceLevel.HIGH
            action = action if abs(delta_size) > 1e-8 else PositionAction.UNKNOWN
            reason = "position_change_without_fill" if abs(delta_size) > 1e-8 else "no_change"
            final_price, final_ts, final_sz = None, None, None

        # Flip Decomposition
        if action == PositionAction.FLIP or (new_side != previous_side and previous_side != PositionSide.FLAT and new_side != PositionSide.FLAT):
            sub_actions = [
                {"action": PositionAction.CLOSE, "size": abs(previous_size), "side": previous_side},
                {"action": PositionAction.OPEN, "size": abs(new_size), "side": new_side}
            ]
            confidence = ConfidenceLevel.UNKNOWN # Mark as unknown for the main record as per request
            reason = "flip_decomposed_as_unknown"
            action = PositionAction.UNKNOWN

        is_paper_eligible = confidence in {ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM} and scorecard.get("state_alignment") is not False

        all_notes = list(warnings)
        if reason: all_notes.append(reason)
        if not is_paper_eligible: all_notes.append("NOT_PAPER_ELIGIBLE")

        return PositionDeltaRecord(
            wallet_address=wallet_address, coin=coin,
            previous_side=previous_side, new_side=new_side,
            previous_size=previous_size, new_size=new_size,
            delta_size=delta_size, delta_notional_usdc=abs(delta_size) * (final_price or 0),
            action=action, sub_actions=sub_actions, intent=intent,
            exchange_ts=final_ts, price=final_price, fill_size=final_sz,
            confidence_score=1.0 if confidence == ConfidenceLevel.HIGH else (0.65 if confidence == ConfidenceLevel.MEDIUM else 0.0),
            confidence_level=confidence, warnings=warnings, reason=reason,
            source_evidence=source_evidence, notes=all_notes,
            raw=fills[0] if fills else {"previous_size": previous_size, "new_size": new_size}
        )
