"""Write a non-authoritative, fail-closed summary of a closure workflow run."""

from __future__ import annotations

import os
from pathlib import Path

PHASES = frozenset({"IDLE", "COLLECT", "ANALYZE"})
ANALYSIS_STAGES = frozenset(
    {
        "DRAIN",
        "QUALITY",
        "REPLAY",
        "BACKTEST",
        "OOS",
        "FORWARD_PAPER",
        "PNL_PROOF",
        "SCOREBOARD",
        "DONE",
    }
)
EARLY_ANALYSIS_STAGES = frozenset({"DRAIN", "QUALITY", "REPLAY"})


def _positive_epoch(value: str) -> bool:
    return value.isascii() and value.isdigit() and int(value) > 0


def classify_run(
    *,
    phase: str,
    stage: str,
    epoch: str,
    job_outcome: str,
    build_outcome: str,
    publish_outcome: str,
    publish_changed: str = "",
) -> dict[str, bool | str]:
    """Classify whether this workflow actually refreshed a closure receipt.

    This classification deliberately never claims economic proof or global
    completion. The canonical receipt and its validators remain authoritative.
    """
    phase = phase.strip().upper()
    stage = stage.strip().upper()
    job_outcome = job_outcome.strip().lower()
    build_outcome = build_outcome.strip().lower()
    publish_outcome = publish_outcome.strip().lower()
    publish_changed = publish_changed.strip().lower()

    if phase not in PHASES or not _positive_epoch(epoch.strip()):
        classification = "PHASE_UNVERIFIED_NOT_PROVEN"
    elif phase != "ANALYZE":
        classification = "NOT_A_CLOSURE_RUN"
    elif stage not in ANALYSIS_STAGES:
        classification = "PHASE_UNVERIFIED_NOT_PROVEN"
    elif stage in EARLY_ANALYSIS_STAGES:
        classification = "ANALYSIS_IN_PROGRESS_NOT_CLOSURE"
    elif build_outcome != "success" or publish_outcome != "success":
        classification = (
            "CLOSURE_ATTEMPT_FAILED_NOT_PROVEN"
            if job_outcome != "success"
            else "CLOSURE_INCOMPLETE_NOT_PROVEN"
        )
    elif publish_changed == "true":
        classification = "RECEIPT_PUBLISHED_REQUIRES_REVIEW"
    elif publish_changed == "false":
        classification = "CLOSURE_ALREADY_CURRENT_NOT_PUBLISHED"
    else:
        classification = "CLOSURE_PUBLICATION_UNVERIFIED_NOT_PROVEN"

    receipt_published = classification == "RECEIPT_PUBLISHED_REQUIRES_REVIEW"
    reasons = {
        "PHASE_UNVERIFIED_NOT_PROVEN": (
            "La phase ou l’epoch canonique n’est pas vérifiable. Aucune preuve de clôture n’est admissible."
        ),
        "CLOSURE_ATTEMPT_FAILED_NOT_PROVEN": (
            "Le job a échoué ou a été interrompu. Le reçu de clôture n’est pas une preuve valide."
        ),
        "NOT_A_CLOSURE_RUN": (
            f"La phase canonique est {phase}; ce run n’exécute pas la clôture "
            "d’analyse. Un job vert ne prouve pas la clôture."
        ),
        "ANALYSIS_IN_PROGRESS_NOT_CLOSURE": (
            f"L’analyse est encore à l’étape {stage}; la construction du reçu "
            "de clôture n’est pas encore admissible."
        ),
        "CLOSURE_INCOMPLETE_NOT_PROVEN": (
            "La construction ou la publication du reçu a échoué ou a été "
            "ignorée. La clôture n’est pas prouvée."
        ),
        "CLOSURE_ALREADY_CURRENT_NOT_PUBLISHED": (
            "Les reçus construits sont déjà identiques à ceux de main; aucun "
            "nouveau reçu n’a été publié par ce run."
        ),
        "CLOSURE_PUBLICATION_UNVERIFIED_NOT_PROVEN": (
            "Le statut de publication ne confirme pas un nouveau commit; "
            "aucune publication n’est revendiquée."
        ),
        "RECEIPT_PUBLISHED_REQUIRES_REVIEW": (
            "Un reçu a été publié. Son contenu et ses validateurs doivent être "
            "examinés; cela ne prouve pas à lui seul DONE ni la rentabilité."
        ),
    }
    return {
        "classification": classification,
        "reason": reasons[classification],
        "receipt_published": receipt_published,
        "economic_proof": False,
    }


def render_summary(
    result: dict[str, bool | str],
    *,
    phase: str,
    stage: str,
    epoch: str,
    source_collection_epoch: str,
    cutoff: str,
    build_outcome: str,
    publish_outcome: str,
    dispatch_outcome: str,
    job_outcome: str,
    commit_sha: str,
    run_id: str,
    publish_changed: str = "",
) -> str:
    stage_label = stage or "(aucune)"
    source_epoch_label = source_collection_epoch or "(aucun)"
    cutoff_label = cutoff or "(aucun)"
    receipt_label = "oui" if result["receipt_published"] else "non"
    return "\n".join(
        [
            "## Statut probant — global-implementation-closure",
            f"- Classification : `{result['classification']}`",
            f"- Résultat Actions : `{job_outcome or 'unknown'}`",
            f"- Phase canonique / epoch : `{phase or 'UNKNOWN'}` / `{epoch or 'UNKNOWN'}`",
            f"- Étape d’analyse : `{stage_label}`",
            f"- Epoch source de collecte : `{source_epoch_label}`",
            f"- Cutoff UTC : `{cutoff_label}`",
            f"- Reçu de clôture publié : `{receipt_label}`",
            f"- Build receipt : `{build_outcome or 'unknown'}`",
            f"- Publication receipt : `{publish_outcome or 'unknown'}`",
            f"- Nouveau reçu publié par ce run : `{publish_changed or 'unknown'}`",
            f"- Dispatch du contrôleur d’analyse : `{dispatch_outcome or 'unknown'}`",
            f"- Commit du run : `{commit_sha or 'unknown'}`",
            f"- Run Actions : `{run_id or 'unknown'}`",
            f"- Interprétation : {result['reason']}",
            "- Aucune preuve technique ou économique n’est déduite du seul succès Actions.",
            "- Preuve économique : `NON ÉTABLIE PAR CE WORKFLOW`",
            "",
        ]
    )


def main() -> int:
    phase = os.environ.get("ALINA_PHASE", "UNKNOWN")
    stage = os.environ.get("ALINA_STAGE", "")
    epoch = os.environ.get("ALINA_EPOCH", "")
    source_collection_epoch = os.environ.get("ALINA_SOURCE_COLLECTION_EPOCH", "")
    cutoff = os.environ.get("ALINA_COLLECTION_CUTOFF_UTC", "")
    job_outcome = os.environ.get("ALINA_JOB_OUTCOME", "unknown")
    build_outcome = os.environ.get("ALINA_BUILD_OUTCOME", "unknown")
    publish_outcome = os.environ.get("ALINA_PUBLISH_OUTCOME", "unknown")
    publish_changed = os.environ.get("ALINA_PUBLISH_CHANGED", "")
    dispatch_outcome = os.environ.get("ALINA_DISPATCH_OUTCOME", "unknown")

    result = classify_run(
        phase=phase,
        stage=stage,
        epoch=epoch,
        job_outcome=job_outcome,
        build_outcome=build_outcome,
        publish_outcome=publish_outcome,
        publish_changed=publish_changed,
    )
    summary = render_summary(
        result,
        phase=phase,
        stage=stage,
        epoch=epoch,
        source_collection_epoch=source_collection_epoch,
        cutoff=cutoff,
        build_outcome=build_outcome,
        publish_outcome=publish_outcome,
        dispatch_outcome=dispatch_outcome,
        job_outcome=job_outcome,
        commit_sha=os.environ.get("GITHUB_SHA", ""),
        run_id=os.environ.get("GITHUB_RUN_ID", ""),
        publish_changed=publish_changed,
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        raise SystemExit("GITHUB_STEP_SUMMARY is required")
    with Path(summary_path).open("a", encoding="utf-8") as output:
        output.write(summary)
    print(summary, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
