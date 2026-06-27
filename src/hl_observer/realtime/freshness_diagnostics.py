from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from hl_observer.realtime.latency_report import LatencyReport, build_latency_report
from hl_observer.simulation.decision_replay_analyzer import ReplayAnalysis, analyze_decision_logs


@dataclass(frozen=True, slots=True)
class FreshnessRecommendation:
    code: str
    severity: str
    message_fr: str
    suggested_action: str


@dataclass(frozen=True, slots=True)
class FreshnessDiagnostics:
    latency: LatencyReport
    analysis: ReplayAnalysis
    stale_ratio: float | None
    top_stale_refusal_reasons: tuple[tuple[str, int], ...]
    recommendations: tuple[FreshnessRecommendation, ...]


def build_freshness_diagnostics(log_dir: Path) -> FreshnessDiagnostics:
    latency = build_latency_report(log_dir)
    analysis = analyze_decision_logs(log_dir)
    stale_reasons: Counter[str] = Counter()
    stale_events = 0
    age_samples = 0
    for event in analysis.events:
        if event.signal_age_ms is None:
            continue
        age_samples += 1
        if event.signal_age_ms > 3_000:
            stale_events += 1
            if event.reason:
                stale_reasons[event.reason] += 1
    stale_ratio = round(stale_events / age_samples, 6) if age_samples else None
    recommendations = _recommend(latency, analysis, stale_ratio)
    return FreshnessDiagnostics(
        latency=latency,
        analysis=analysis,
        stale_ratio=stale_ratio,
        top_stale_refusal_reasons=tuple(stale_reasons.most_common(10)),
        recommendations=tuple(recommendations),
    )


def format_freshness_diagnostics(report: FreshnessDiagnostics) -> str:
    lines = [
        "freshness_diagnostics=simulation_only",
        f"samples={report.latency.samples}",
        f"avg_signal_age_ms={report.latency.avg_ms}",
        f"p95_signal_age_ms={report.latency.p95_ms}",
        f"max_signal_age_ms={report.latency.max_ms}",
        f"stale_over_3000ms={report.latency.stale_over_3000ms}",
        f"stale_ratio={report.stale_ratio}",
        f"events={report.analysis.event_count}",
        f"refused={report.analysis.refused_count}",
        f"accepted={report.analysis.accepted_count}",
        "top_stale_refusal_reasons:",
    ]
    if report.top_stale_refusal_reasons:
        lines.extend(f"- {reason}: {count}" for reason, count in report.top_stale_refusal_reasons)
    else:
        lines.append("- none")
    lines.append("recommendations:")
    for item in report.recommendations:
        lines.append(f"- {item.severity} {item.code}: {item.message_fr} Action: {item.suggested_action}")
    return "\n".join(lines)


def _recommend(
    latency: LatencyReport,
    analysis: ReplayAnalysis,
    stale_ratio: float | None,
) -> list[FreshnessRecommendation]:
    recs: list[FreshnessRecommendation] = []
    if latency.samples == 0:
        recs.append(
            FreshnessRecommendation(
                "NO_SIGNAL_AGE_DATA",
                "BLOCKED",
                "Les logs ne contiennent pas d'age de signal mesurable.",
                "Verifier que copy-run/live-user-fills-scan ecrit signal_age_ms dans les decisions.",
            )
        )
        return recs
    if stale_ratio is not None and stale_ratio > 0.5:
        recs.append(
            FreshnessRecommendation(
                "STALE_RATIO_TOO_HIGH",
                "HIGH",
                "Plus de la moitie des signaux ne sont plus dans la fenetre ultra-chaude de quelques secondes.",
                "Prioriser la shortlist WS read-only, garder une rotation bornee et verifier que la decision reste dans la fenetre fraiche configuree.",
            )
        )
    if latency.p95_ms is not None and latency.p95_ms > 10_000:
        recs.append(
            FreshnessRecommendation(
                "P95_LATENCY_TOO_HIGH",
                "HIGH",
                "Le p95 de latence est beaucoup trop haut pour copier une ouverture courte.",
                "Utiliser les logs pour identifier les sources lentes, puis refuser les deltas au-dela de la fenetre de fraicheur configuree.",
            )
        )
    if analysis.top_refusal_reasons and analysis.top_refusal_reasons[0][0].startswith("NO_MATCHING_PAPER_POSITION_FOR_CLOSE"):
        recs.append(
            FreshnessRecommendation(
                "CLOSE_WITHOUT_POSITION_DOMINATES",
                "MEDIUM",
                "Beaucoup de fermetures arrivent sans position papier correspondante.",
                "Ne pas ouvrir retroactivement; ignorer ce bruit cote ledger et ameliorer la capture des ouvertures fraiches.",
            )
        )
    if analysis.accepted_count == 0 and analysis.refused_count > 0:
        recs.append(
            FreshnessRecommendation(
                "ALL_REFUSED",
                "MEDIUM",
                "Aucun evenement n'est exploitable par la simulation locale.",
                "Verifier edge_remaining, fraicheur, liquidite et exposition avant d'elargir le scan.",
            )
        )
    if not recs:
        recs.append(
            FreshnessRecommendation(
                "NO_MAJOR_FRESHNESS_ACTION",
                "LOW",
                "Aucun probleme de fraicheur dominant detecte dans les logs.",
                "Continuer a accumuler des evenements et verifier le PnL net apres couts.",
            )
        )
    return recs
