"""V13 #157 — Rapport `ledger calibration` (CloddsBot A1 + backtesting A4), langage simple.

Mesure si les notes de l'IA sont FIABLES : pour chaque tranche de confiance (ex: ~70%),
quelle est la vraie proportion de trades gagnants ? + Brier vs hasard + distribution des
raisons de refus (block-reasons). Pur / lecture seule ; état vide honnête ; zéro fabrication.
"""

from __future__ import annotations

from collections.abc import Mapping

from hl_observer.calibration.brier import cumulative_brier_advantage
from hl_observer.calibration.confidence_buckets import bucketize, calibration_error


def _normalize_block_reasons(block_reasons) -> list[dict]:
    pairs: list[tuple[str, int]] = []
    if isinstance(block_reasons, Mapping):
        pairs = [(str(k), int(v)) for k, v in block_reasons.items()]
    else:
        for x in block_reasons or ():
            if isinstance(x, Mapping):
                pairs.append((str(x.get("reason")), int(x.get("count", 1))))
            elif isinstance(x, str):
                pairs.append((x, 1))
            else:
                pairs.append((str(x[0]), int(x[1])))
    agg: dict[str, int] = {}
    for r, c in pairs:
        agg[r] = agg.get(r, 0) + c
    return [{"reason": r, "count": c} for r, c in sorted(agg.items(), key=lambda t: -t[1])]


def build_ledger_calibration_report(
    *,
    predictions: list[tuple[float, float | bool | int]] | None = None,
    block_reasons=None,
    n_buckets: int = 10,
) -> dict:
    preds = list(predictions or [])
    buckets = bucketize(preds, n_buckets=n_buckets) if preds else []
    cal_err = calibration_error(buckets) if buckets else None
    br = cumulative_brier_advantage([p for p, _ in preds], [y for _, y in preds]) if preds else None
    blocks = _normalize_block_reasons(block_reasons)

    bucket_rows = [
        {"from": round(b.low, 2), "to": round(b.high, 2), "count": b.count,
         "win_rate": None if b.win_rate is None else round(b.win_rate, 4),
         "mean_confidence": None if b.mean_confidence is None else round(b.mean_confidence, 4),
         "gap": None if b.calibration_gap is None else round(b.calibration_gap, 4)}
        for b in buckets if b.count > 0
    ]

    # phrase simple
    if not preds:
        plain = ("Pas encore assez de décisions notées pour juger la fiabilité de l'IA. "
                 "Le rapport se remplira au fil des trades.")
    else:
        beats = bool(br and br.advantage is not None and br.advantage > 0)
        err_pct = None if cal_err is None else round(cal_err * 100)
        plain = (f"Sur {br.samples if br else len(preds)} décisions notées, "
                 f"l'écart moyen entre ce que l'IA annonce et la réalité est d'environ "
                 f"{err_pct if err_pct is not None else '?'} points. "
                 + ("Ses notes sont globalement fiables (mieux que le hasard)."
                    if beats else "Ses notes ne battent pas encore le hasard — elle apprend."))

    return {
        "buckets": bucket_rows,
        "calibration_error": None if cal_err is None else round(cal_err, 4),
        "brier": None if br is None else br.brier,
        "baseline_brier": None if br is None else br.baseline_brier,
        "brier_advantage": None if br is None else br.advantage,
        "beats_baseline": bool(br and br.advantage is not None and br.advantage > 0),
        "block_reasons": blocks[:15],
        "n_predictions": len(preds),
        "plain_summary": plain,
        "empty": not preds and not blocks,
        "context_only": True,
    }


__all__ = ["build_ledger_calibration_report"]
