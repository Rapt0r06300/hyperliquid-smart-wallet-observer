from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.hyperliquid_client.models import (
    ScoreBreakdown,
    Wallet,
    WalletScore,
    WalletScoreStatus,
    WalletStatus,
)
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address
from hyper_smart_observer.scoring.confidence import calculate_confidence, calculate_confidence_score
from hyper_smart_observer.scoring.drawdown import calculate_max_drawdown
from hyper_smart_observer.scoring.equity_curve import build_equity_curve_from_pnl, pnl_returns_from_curve
from hyper_smart_observer.scoring.pnl import (
    calculate_gross_pnl,
    calculate_net_pnl,
    calculate_net_pnl_after_fees,
    calculate_total_fees,
)
from hyper_smart_observer.scoring.risk_metrics import (
    calculate_calmar,
    calculate_profit_factor,
    calculate_sharpe,
    calculate_sortino,
)
from hyper_smart_observer.scoring.sample_quality import (
    calculate_consistency_score,
    calculate_history_days,
    calculate_recency_score,
    calculate_sample_quality_score,
)
from hyper_smart_observer.scoring.winrate import (
    calculate_average_loss,
    calculate_average_win,
    calculate_winrate,
)
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories import fills_repo, scores_repo, wallet_repo


@dataclass(frozen=True)
class _UsableFill:
    timestamp: datetime
    fee: float
    closed_pnl: float | None


def build_wallet_score(wallet_address: str, trade_pnls: list[float]) -> WalletScore:
    """Backward-compatible Sprint 1 helper.

    It remains intentionally simple and is not used as an execution signal.
    """

    gross_profit = sum(value for value in trade_pnls if value > 0)
    gross_loss = sum(value for value in trade_pnls if value < 0)
    confidence = calculate_confidence(len(trade_pnls))
    if len(trade_pnls) < 10:
        return WalletScore(
            wallet_address=wallet_address,
            calculated_at=datetime.now(UTC),
            total_trades=len(trade_pnls),
            confidence_score=confidence,
            refusal_reason="INSUFFICIENT_SAMPLE",
        )
    return WalletScore(
        wallet_address=wallet_address,
        calculated_at=datetime.now(UTC),
        total_trades=len(trade_pnls),
        winrate=calculate_winrate(trade_pnls),
        pnl_net=calculate_net_pnl(trade_pnls),
        max_drawdown=calculate_max_drawdown(build_equity_curve_from_pnl(trade_pnls)),
        profit_factor=calculate_profit_factor(gross_profit, gross_loss),
        confidence_score=confidence,
        final_score=min(100.0, confidence * 100.0),
    )


class WalletScoreEngine:
    """Research-only wallet scorer using local SQLite fills.

    The engine never performs network calls and never creates trading signals.
    It only scores local data quality and historical closed-PnL observations
    when those observations are already present in the database.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def score_wallet(self, wallet_address: str) -> ScoreBreakdown:
        try:
            wallet_address = normalize_wallet_address(wallet_address)
        except ValueError:
            return self._refused(
                wallet_address,
                WalletScoreStatus.INVALID_DATA,
                total_fills=0,
                usable_fills=0,
                skipped_fills=0,
                reason="INVALID_WALLET_ADDRESS",
                warnings=["Wallet scoring requires a full 42-character 0x hex address."],
            )
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            wallet = wallet_repo.get_wallet(conn, wallet_address)
            if wallet and wallet.status == WalletStatus.BLOCKED:
                return self._blocked(wallet_address)
            rows = fills_repo.list_all_fills_for_wallet(conn, wallet_address)
        return self._score_rows(wallet_address, rows)

    def score_all_wallets(self, limit: int | None = None) -> list[ScoreBreakdown]:
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            wallets = wallet_repo.list_wallets(conn, limit or 100)
        return [self.score_wallet(row["address"]) for row in wallets]

    def persist_score(self, score_breakdown: ScoreBreakdown) -> None:
        if score_breakdown.status != WalletScoreStatus.SCORED and not self.config.score_store_rejected:
            return
        try:
            normalize_wallet_address(score_breakdown.wallet_address)
        except ValueError:
            return
        initialize_database(self.config)
        with get_connection(self.config) as conn:
            if wallet_repo.get_wallet(conn, score_breakdown.wallet_address) is None:
                wallet_repo.insert_wallet(
                    conn, Wallet(address=score_breakdown.wallet_address, source="score_engine")
                )
            scores_repo.insert_score_breakdown(conn, score_breakdown)
            conn.commit()

    def score_and_store_wallet(self, wallet_address: str) -> ScoreBreakdown:
        score = self.score_wallet(wallet_address)
        self.persist_score(score)
        return score

    def score_and_store_all(self, limit: int | None = None) -> list[ScoreBreakdown]:
        scores = self.score_all_wallets(limit=limit)
        for score in scores:
            self.persist_score(score)
        return scores

    def _score_rows(self, wallet_address: str, rows: list) -> ScoreBreakdown:
        warnings: list[str] = []
        total_fills = len(rows)
        if total_fills == 0:
            return self._refused(
                wallet_address,
                WalletScoreStatus.INSUFFICIENT_DATA,
                total_fills=0,
                usable_fills=0,
                skipped_fills=0,
                reason="NO_LOCAL_FILLS",
                warnings=["No local fills found; collect read-only data first."],
            )

        usable, skipped = self._extract_usable_fills(rows, warnings)
        if not usable:
            return self._refused(
                wallet_address,
                WalletScoreStatus.INVALID_DATA,
                total_fills=total_fills,
                usable_fills=0,
                skipped_fills=skipped,
                reason="NO_USABLE_FILLS",
                warnings=warnings,
            )

        usable = self._apply_lookback(usable, warnings)
        first_fill_at = min(fill.timestamp for fill in usable)
        last_fill_at = max(fill.timestamp for fill in usable)
        history_days = calculate_history_days(first_fill_at, last_fill_at)
        pnl_values = [fill.closed_pnl for fill in usable if fill.closed_pnl is not None]
        fees = [fill.fee for fill in usable]
        closed_pnl_points = len(pnl_values)
        sample_quality = calculate_sample_quality_score(
            usable_fills=len(usable),
            skipped_fills=skipped,
            closed_pnl_points=closed_pnl_points,
            history_days=history_days,
            min_fills=self.config.min_fills_to_score,
            min_closed_pnl_points=self.config.min_closed_pnl_points,
            min_history_days=self.config.min_history_days_to_score,
        )
        recency_score = calculate_recency_score(
            last_fill_at, half_life_days=self.config.score_recency_half_life_days
        )
        confidence_score = calculate_confidence_score(
            sample_quality_score=sample_quality,
            recency_score=recency_score,
            closed_pnl_points=closed_pnl_points,
            min_closed_pnl_points=self.config.min_closed_pnl_points,
        )

        base = {
            "wallet_address": wallet_address.lower(),
            "calculated_at": datetime.now(UTC),
            "total_fills": total_fills,
            "usable_fills": len(usable),
            "skipped_fills": skipped,
            "first_fill_at": first_fill_at,
            "last_fill_at": last_fill_at,
            "history_days": history_days,
            "total_fees": calculate_total_fees(fees),
            "sample_quality_score": sample_quality,
            "recency_score": recency_score,
            "confidence_score": confidence_score,
        }

        refusal = self._data_refusal_reason(len(usable), history_days, closed_pnl_points)
        if refusal:
            return ScoreBreakdown(
                **base,
                status=refusal[0],
                refusal_reason=refusal[1],
                warnings=[*warnings, refusal[2]],
            )

        gross_profit = sum(value for value in pnl_values if value > 0)
        gross_loss = sum(value for value in pnl_values if value < 0)
        gross_pnl = calculate_gross_pnl(pnl_values)
        net_pnl = calculate_net_pnl_after_fees(pnl_values, fees)
        equity_curve = build_equity_curve_from_pnl(pnl_values)
        returns = pnl_returns_from_curve(equity_curve)
        max_drawdown = calculate_max_drawdown(equity_curve)
        consistency_score = calculate_consistency_score(pnl_values, max_drawdown)
        risk_score = self._risk_score(max_drawdown, pnl_values)
        profit_factor = calculate_profit_factor(gross_profit, gross_loss)
        sharpe = calculate_sharpe(returns)
        sortino = calculate_sortino(returns)
        calmar = calculate_calmar(net_pnl, max_drawdown)
        final_score = self._combine_scores(
            sample_quality_score=sample_quality,
            confidence_score=confidence_score,
            risk_score=risk_score,
            consistency_score=consistency_score,
            recency_score=recency_score,
            profit_factor=profit_factor,
            net_pnl=net_pnl,
        )
        if final_score is None:
            return ScoreBreakdown(
                **base,
                status=WalletScoreStatus.REJECTED_BY_RISK,
                gross_pnl=gross_pnl,
                net_pnl=net_pnl,
                winrate=calculate_winrate(pnl_values),
                average_win=calculate_average_win(pnl_values),
                average_loss=calculate_average_loss(pnl_values),
                profit_factor=profit_factor,
                max_drawdown=max_drawdown,
                sharpe=sharpe,
                sortino=sortino,
                calmar=calmar,
                consistency_score=consistency_score,
                risk_score=risk_score,
                refusal_reason="CONFIDENCE_OR_CRITICAL_METRICS_TOO_LOW",
                warnings=[*warnings, "Score not promoted: confidence or critical metrics are missing."],
            )

        return ScoreBreakdown(
            **base,
            status=WalletScoreStatus.SCORED,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            winrate=calculate_winrate(pnl_values),
            average_win=calculate_average_win(pnl_values),
            average_loss=calculate_average_loss(pnl_values),
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            consistency_score=consistency_score,
            risk_score=risk_score,
            final_score=final_score,
            warnings=warnings,
        )

    def _extract_usable_fills(self, rows: list, warnings: list[str]) -> tuple[list[_UsableFill], int]:
        usable: list[_UsableFill] = []
        skipped = 0
        for row in rows:
            parsed = self._parse_fill(row)
            if parsed is None:
                skipped += 1
                continue
            usable.append(parsed)
        if skipped:
            warnings.append(f"{skipped} fill(s) ignored because required fields were invalid.")
        return usable, skipped

    def _parse_fill(self, row) -> _UsableFill | None:
        try:
            price = float(row["price"])
            size = float(row["size"])
            fee = max(0.0, float(row["fee"] or 0.0))
            side = str(row["side"] or "").strip()
            timestamp = datetime.fromisoformat(str(row["timestamp"]))
        except (KeyError, TypeError, ValueError):
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        if price <= 0 or size <= 0 or not side:
            return None
        closed_pnl = self._optional_float(_row_value(row, "closed_pnl"))
        return _UsableFill(timestamp=timestamp, fee=fee, closed_pnl=closed_pnl)

    def _apply_lookback(self, fills: list[_UsableFill], warnings: list[str]) -> list[_UsableFill]:
        if not fills or self.config.score_max_lookback_days <= 0:
            return fills
        last_fill_at = max(fill.timestamp for fill in fills)
        cutoff = last_fill_at - timedelta(days=self.config.score_max_lookback_days)
        filtered = [fill for fill in fills if fill.timestamp >= cutoff]
        if len(filtered) != len(fills):
            warnings.append(
                f"{len(fills) - len(filtered)} fill(s) outside the scoring lookback were ignored."
            )
        return filtered

    def _data_refusal_reason(
        self, usable_fills: int, history_days: float | None, closed_pnl_points: int
    ) -> tuple[WalletScoreStatus, str, str] | None:
        if usable_fills < self.config.min_fills_to_score:
            return (
                WalletScoreStatus.INSUFFICIENT_DATA,
                "INSUFFICIENT_FILLS",
                "Not enough local fills to score without overfitting.",
            )
        if (history_days or 0.0) < self.config.min_history_days_to_score:
            return (
                WalletScoreStatus.NEEDS_MORE_HISTORY,
                "INSUFFICIENT_HISTORY_DAYS",
                "Local history window is too short for a robust score.",
            )
        if self.config.score_require_net_pnl and closed_pnl_points == 0:
            return (
                WalletScoreStatus.INSUFFICIENT_DATA,
                "NO_CLOSED_PNL_POINTS",
                "No closed PnL values are stored, so PnL is not invented.",
            )
        if self.config.score_require_net_pnl and closed_pnl_points < self.config.min_closed_pnl_points:
            return (
                WalletScoreStatus.INSUFFICIENT_DATA,
                "INSUFFICIENT_CLOSED_PNL_POINTS",
                "Not enough closed PnL points to produce a final score.",
            )
        return None

    def _combine_scores(
        self,
        *,
        sample_quality_score: float,
        confidence_score: float,
        risk_score: float,
        consistency_score: float,
        recency_score: float,
        profit_factor: float | None,
        net_pnl: float | None,
    ) -> float | None:
        if confidence_score < self.config.score_min_confidence * 100.0:
            return None
        if self.config.score_require_net_pnl and net_pnl is None:
            return None
        if profit_factor is None:
            return None
        score = (
            (0.30 * sample_quality_score)
            + (0.25 * confidence_score)
            + (0.20 * risk_score)
            + (0.15 * consistency_score)
            + (0.10 * recency_score)
        )
        return max(0.0, min(100.0, score))

    def _risk_score(self, max_drawdown: float | None, pnl_values: list[float]) -> float:
        total_abs = sum(abs(value) for value in pnl_values)
        if max_drawdown is None or total_abs <= 0:
            return 0.0
        drawdown_ratio = min(1.0, max_drawdown / total_abs)
        return max(0.0, min(100.0, 100.0 * (1.0 - drawdown_ratio)))

    def _blocked(self, wallet_address: str) -> ScoreBreakdown:
        return self._refused(
            wallet_address,
            WalletScoreStatus.BLOCKED,
            total_fills=0,
            usable_fills=0,
            skipped_fills=0,
            reason="WALLET_BLOCKED",
            warnings=["Wallet is blocked by local policy."],
        )

    def _refused(
        self,
        wallet_address: str,
        status: WalletScoreStatus,
        *,
        total_fills: int,
        usable_fills: int,
        skipped_fills: int,
        reason: str,
        warnings: list[str] | None = None,
    ) -> ScoreBreakdown:
        return ScoreBreakdown(
            wallet_address=wallet_address.lower(),
            calculated_at=datetime.now(UTC),
            status=status,
            total_fills=total_fills,
            usable_fills=usable_fills,
            skipped_fills=skipped_fills,
            refusal_reason=reason,
            warnings=warnings or [],
        )

    def _optional_float(self, value: object) -> float | None:
        try:
            if value in (None, ""):
                return None
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None


def _row_value(row, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None
