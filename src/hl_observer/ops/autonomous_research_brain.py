"""Décision de recherche pour le laboratoire autonome Alina SmartFlow.

Le cerveau n'est PAS un moteur de trading et ne produit aucun fill. Il lit les
preuves déjà générées puis décide où dépenser le prochain budget de calcul.

Règle centrale anti-overfit : les valeurs numériques OOS/forward ne servent
jamais de gradient de classement ni de réglage. Elles sont uniquement des
portes de confirmation/veto. La recherche de paramètres doit rester sur les
zones TRAIN/validation prévues par les moteurs dédiés.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from hl_observer.simulation.economic_objective import CANONICAL_FAMILIES

REPORT_DIR = Path("runtime") / "reports" / "economic_campaigns"
BRAIN_RELATIVE = Path("runtime") / "reports" / "autonomous_research" / "RESEARCH_BRAIN_DECISION.json"
BRAIN_MARKDOWN_RELATIVE = Path("runtime") / "reports" / "autonomous_research" / "RESEARCH_BRAIN_DECISION.md"
STRICT_COPY_RELATIVE = Path("runtime") / "replay" / "RECHERCHE_ADAPTATIVE_STRICTE.json"

_MISSING_MARKERS = (
    "UNMEASURED",
    "_MISSING",
    "PROOF_INCOMPLETE",
    "PARAMETERS_NOT_FROZEN",
    "POSITIONS_NOT_FULLY",
    "NOT_LIQUIDATABLE",
    "TWO_LEG_CLOSE_PROOF_MISSING",
)
_EDGE_MARKERS = (
    "NET_NOT_POSITIVE",
    "TARGET_NET_USD_NOT_REACHED",
    "PLACEBO_NOT_BEATEN",
)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_campaigns(root: str | Path) -> dict[str, dict[str, Any]]:
    root_path = Path(root).resolve()
    found: dict[str, dict[str, Any]] = {}
    for family in CANONICAL_FAMILIES:
        payload = _load_json(root_path / REPORT_DIR / f"{family}.json")
        if payload is not None:
            found[family] = payload
    return found


def _reasons(campaign: Mapping[str, Any]) -> list[str]:
    return [str(value) for value in campaign.get("objective_reasons") or []]


def _has_marker(reasons: Iterable[str], markers: tuple[str, ...]) -> bool:
    return any(any(marker in reason for marker in markers) for reason in reasons)


def _strict_copy_summary(root: Path) -> dict[str, Any] | None:
    strict = _load_json(root / STRICT_COPY_RELATIVE)
    if strict is None:
        return None
    robustesse = strict.get("robustesse") if isinstance(strict.get("robustesse"), Mapping) else {}
    promoted = strict.get("promus") if isinstance(strict.get("promus"), list) else []
    scout = strict.get("scout_audit") if isinstance(strict.get("scout_audit"), Mapping) else {}
    return {
        "status": strict.get("statut"),
        "promoted_count": len(promoted),
        "pbo": robustesse.get("pbo"),
        "robustness_verdict": robustesse.get("verdict"),
        "strict_train_only": strict.get("strict_train_only") is True,
        "validation_rows_seen_by_scout": scout.get("validation_rows_seen"),
        "validation_used_for_selection": scout.get("validation_used_for_selection"),
        "candidate_count": strict.get("n_candidats"),
    }


def decide_family(
    family: str,
    campaign: Mapping[str, Any] | None,
    *,
    strict_copy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Décide une phase sans utiliser la magnitude OOS/forward pour optimiser."""

    if campaign is None:
        return {
            "family": family,
            "priority": 100,
            "phase": "BUILD_EVIDENCE",
            "reason": "Aucune campagne économique machine-lisible disponible.",
            "holdout_used_for_ranking": False,
        }

    reasons = _reasons(campaign)
    status = str(campaign.get("objective_status") or "NON_ATTEINT")
    observed_net = campaign.get("net_pnl_usd")
    signal_count = campaign.get("signal_count")

    if status == "ATTEINT":
        return {
            "family": family,
            "priority": 20,
            "phase": "FREEZE_AND_CONFIRM_FORWARD",
            "reason": "La preuve stricte est atteinte; ne pas retuner sur ce holdout.",
            "holdout_gate": "PASS",
            "holdout_used_for_ranking": False,
            "signals": signal_count,
        }

    if _has_marker(reasons, _MISSING_MARKERS) or observed_net is None:
        return {
            "family": family,
            "priority": 100,
            "phase": "COMPLETE_EVIDENCE",
            "reason": "La famille n'est pas encore mesurable selon le contrat strict; compléter la preuve avant de conclure sur l'edge.",
            "holdout_gate": "UNKNOWN",
            "holdout_used_for_ranking": False,
            "signals": signal_count,
            "blocking_reasons": reasons,
        }

    if family == "copy_vault" and strict_copy:
        verdict = str(strict_copy.get("robustness_verdict") or "")
        promoted = int(strict_copy.get("promoted_count") or 0)
        if verdict == "SUR_AJUSTE":
            return {
                "family": family,
                "priority": 55,
                "phase": "EXPAND_DATA_NOT_PARAMETERS",
                "reason": "Le PBO signale du sur-ajustement; augmenter la diversité des données plutôt que raffiner les paramètres.",
                "holdout_gate": "VETO_OVERFIT",
                "holdout_used_for_ranking": False,
                "strict_search": dict(strict_copy),
            }
        if promoted > 0 and strict_copy.get("strict_train_only") is True:
            return {
                "family": family,
                "priority": 90,
                "phase": "INDEPENDENT_CONFIRMATION",
                "reason": "La recherche TRAIN-only a des promus; priorité à une confirmation indépendante, pas à un nouveau tuning sur le même holdout.",
                "holdout_gate": "CONFIRM_ONLY",
                "holdout_used_for_ranking": False,
                "strict_search": dict(strict_copy),
            }

    if _has_marker(reasons, _EDGE_MARKERS):
        try:
            net = float(observed_net)
        except (TypeError, ValueError):
            net = 0.0
        phase = "ROBUST_TRAIN_REFINEMENT" if net > 0 else "MECHANISM_SEARCH"
        priority = 80 if net > 0 else 75
        return {
            "family": family,
            "priority": priority,
            "phase": phase,
            "reason": (
                "Le diagnostic global est positif mais la preuve stricte ne franchit pas les portes; chercher sur TRAIN/validation puis reconfirmer."
                if net > 0
                else "Le mécanisme mesuré ne paie pas encore ses coûts; chercher un autre mécanisme ou sous-régime plutôt que forcer le seuil."
            ),
            "holdout_gate": "FAIL_OR_INCOMPLETE",
            "holdout_used_for_ranking": False,
            "signals": signal_count,
            "blocking_reasons": reasons,
        }

    return {
        "family": family,
        "priority": 65,
        "phase": "DIAGNOSE",
        "reason": "État non conclusif: diagnostiquer les portes qui bloquent avant d'augmenter l'espace de paramètres.",
        "holdout_gate": "NON_CONCLUSIVE",
        "holdout_used_for_ranking": False,
        "signals": signal_count,
        "blocking_reasons": reasons,
    }


def build_decision(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    campaigns = load_campaigns(root_path)
    strict_copy = _strict_copy_summary(root_path)
    decisions = [
        decide_family(
            family,
            campaigns.get(family),
            strict_copy=strict_copy if family == "copy_vault" else None,
        )
        for family in CANONICAL_FAMILIES
    ]
    ranked = sorted(decisions, key=lambda row: (-int(row["priority"]), str(row["family"])))

    phases = {str(row["phase"]) for row in ranked}
    if "COMPLETE_EVIDENCE" in phases or "BUILD_EVIDENCE" in phases:
        recommended_mode = "economic"
        recommended_suite = "economic-full"
    elif "MECHANISM_SEARCH" in phases or "ROBUST_TRAIN_REFINEMENT" in phases or "DIAGNOSE" in phases:
        recommended_mode = "historical-deep"
        recommended_suite = "research-lab-full"
    elif "INDEPENDENT_CONFIRMATION" in phases or "EXPAND_DATA_NOT_PARAMETERS" in phases:
        recommended_mode = "historical-full"
        recommended_suite = "research-lab-full"
    else:
        recommended_mode = "historical-full"
        recommended_suite = "economic-full"

    return {
        "schema": "alina.autonomous_research_brain.v1",
        "paper_read_only": True,
        "real_execution": False,
        "objective": "maximiser le PnL net robuste après coûts sans optimiser sur le holdout",
        "holdout_policy": {
            "numeric_oos_used_for_parameter_ranking": False,
            "numeric_forward_used_for_parameter_ranking": False,
            "oos_forward_allowed_as_gate": True,
            "retune_after_holdout_failure": "TRAIN_VALIDATION_ONLY_OR_NEW_DATA",
        },
        "family_decisions": ranked,
        "next_recommended_job": {
            "suite": recommended_suite,
            "mode": recommended_mode,
            "reason": ranked[0]["reason"] if ranked else "Aucune preuve disponible.",
            "top_family": ranked[0]["family"] if ranked else None,
        },
        "strict_copy_summary": strict_copy,
    }


def write_decision(root: str | Path, decision: Mapping[str, Any]) -> tuple[Path, Path]:
    root_path = Path(root).resolve()
    json_path = root_path / BRAIN_RELATIVE
    md_path = root_path / BRAIN_MARKDOWN_RELATIVE
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Alina SmartFlow — décision du cerveau de recherche",
        "",
        f"Objectif : **{decision.get('objective')}**.",
        "",
        "Le cerveau ne classe jamais les paramètres par la magnitude OOS/forward. Ces segments sont des portes de confirmation/veto.",
        "",
        "| Priorité | Famille | Phase | Action |",
        "|---:|---|---|---|",
    ]
    for row in decision.get("family_decisions") or []:
        lines.append(
            f"| {row.get('priority')} | `{row.get('family')}` | `{row.get('phase')}` | {row.get('reason')} |"
        )
    next_job = decision.get("next_recommended_job") or {}
    lines.extend(
        [
            "",
            "## Prochain type de run recommandé",
            "",
            f"- Suite : `{next_job.get('suite')}`",
            f"- Mode : `{next_job.get('mode')}`",
            f"- Famille prioritaire : `{next_job.get('top_family')}`",
            f"- Pourquoi : {next_job.get('reason')}",
            "",
            "> Une priorité élevée signifie qu'il est utile d'y dépenser du calcul ou de compléter la preuve. Elle ne constitue pas une promesse de rendement.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Décide le prochain axe du laboratoire autonome sans optimiser sur le holdout.")
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    decision = build_decision(Path(args.root))
    json_path, md_path = write_decision(Path(args.root), decision)
    next_job = decision["next_recommended_job"]
    print(
        f"ALINA_RESEARCH_BRAIN suite={next_job['suite']} mode={next_job['mode']} top_family={next_job['top_family']} json={json_path} md={md_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
