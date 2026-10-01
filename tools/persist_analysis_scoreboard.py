#!/usr/bin/env python3
"""Persist the current ANALYZE scoreboard as an epoch-bound Dataset V2 receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ACTIVE_FAMILIES = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def build_improvement_ledger(
    scoreboard: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    *,
    campaign_id: str,
    phase_epoch: int,
    source_collection_epoch: int,
    dataset_selection_id: str,
    code_sha: str,
    analysis_stage: str = "SCOREBOARD",
    evidence_tag: str | None = None,
    evidence_repository: str | None = None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    """Conserve un historique comparable et un meilleur resultat par etape.

    BACKTEST n'est compare qu'a BACKTEST, OOS qu'a OOS, etc. Un resultat
    non mesurable est historise mais ne remplace jamais la reference.
    """
    previous = dict(previous or {})
    prior_families = previous.get("families")
    if not isinstance(prior_families, Mapping):
        prior_families = {}
    scoreboard_families = scoreboard.get("families")
    if not isinstance(scoreboard_families, Mapping):
        scoreboard_families = {}
    stage = str(analysis_stage or "SCOREBOARD").upper()
    allowed_stages = {"BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD"}
    if stage not in allowed_stages:
        raise ValueError(f"unsupported improvement stage: {stage}")

    def metric(source: Mapping[str, Any]) -> tuple[float | None, str | None]:
        direct = _number(source.get("comparison_metric_usd"))
        if direct is not None:
            return direct, str(source.get("comparison_metric_source") or "comparison_metric_usd")
        proof = _number(source.get("proof_net_pnl_usd"))
        if proof is not None:
            return proof, "proof_net_pnl_usd"
        observed = _number(source.get("net_pnl_usd"))
        closed = _number(source.get("closed_positions"))
        if observed is not None and (closed or 0.0) > 0:
            return observed, "net_pnl_usd"
        return None, None

    families: dict[str, Any] = {}
    scoreboard_sha256 = _digest(dict(scoreboard))
    stage_priority = ("SCOREBOARD", "PNL_PROOF", "FORWARD_PAPER", "OOS", "BACKTEST")

    for family in ACTIVE_FAMILIES:
        source = scoreboard_families.get(family)
        source = source if isinstance(source, Mapping) else {}
        candidate_net, metric_source = metric(source)
        prior = prior_families.get(family)
        prior = prior if isinstance(prior, Mapping) else {}

        prior_stages = prior.get("stages")
        if not isinstance(prior_stages, Mapping):
            prior_stages = {}
            # Compatibility with the short-lived v1 ledger.
            if isinstance(prior.get("champion"), Mapping) or prior.get("history"):
                prior_stages = {
                    "SCOREBOARD": {
                        "champion": prior.get("champion"),
                        "latest": prior.get("latest"),
                        "history": list(prior.get("history") or []),
                    }
                }
        stages = json.loads(json.dumps(dict(prior_stages), sort_keys=True))
        stage_row = stages.get(stage)
        stage_row = stage_row if isinstance(stage_row, Mapping) else {}
        champion = stage_row.get("champion")
        champion = champion if isinstance(champion, Mapping) else None
        champion_net = _number(champion.get("net_pnl_usd")) if champion else None

        identity = {
            "campaign_id": campaign_id,
            "analysis_stage": stage,
            "phase_epoch": phase_epoch,
            "source_collection_epoch": source_collection_epoch,
            "dataset_selection_id": dataset_selection_id,
            "code_sha": code_sha,
            "unit_id": str(unit_id) if unit_id is not None else None,
        }
        history = list(stage_row.get("history") or [])
        existing = next(
            (
                row for row in history
                if isinstance(row, Mapping)
                and all(row.get(key) == value for key, value in identity.items())
            ),
            None,
        )
        if existing is not None:
            latest = dict(existing)
            new_champion = champion
        else:
            if candidate_net is None:
                status = "NON_MESURABLE"
                delta = None
                new_champion = champion
            elif champion_net is None:
                status = "REFERENCE_ETABLIE"
                delta = None
                new_champion = {
                    **identity,
                    "net_pnl_usd": candidate_net,
                    "metric_source": metric_source,
                    "evidence_tag": evidence_tag,
                    "evidence_repository": evidence_repository,
                    "scoreboard_sha256": scoreboard_sha256,
                }
            else:
                delta = round(candidate_net - champion_net, 12)
                if delta > 0:
                    status = "AMELIORATION"
                    new_champion = {
                        **identity,
                        "net_pnl_usd": candidate_net,
                        "metric_source": metric_source,
                        "evidence_tag": evidence_tag,
                        "evidence_repository": evidence_repository,
                        "scoreboard_sha256": scoreboard_sha256,
                    }
                else:
                    status = "PAS_D_AMELIORATION"
                    new_champion = champion

            latest = {
                **identity,
                "net_pnl_usd": candidate_net,
                "metric_source": metric_source,
                "previous_champion_net_pnl_usd": champion_net,
                "delta_vs_previous_champion_usd": delta,
                "status": status,
                "verdict": source.get("verdict"),
                "measurement_status": source.get("measurement_status"),
                "evidence_tag": evidence_tag,
                "evidence_repository": evidence_repository,
                "scoreboard_sha256": scoreboard_sha256,
                "paper_read_only": True,
                "real_execution": False,
            }
            history.append(latest)

        stages[stage] = {
            "champion": new_champion,
            "latest": latest,
            "history": history,
        }

        reference_stage = next(
            (
                name for name in stage_priority
                if isinstance(stages.get(name), Mapping)
                and isinstance(stages[name].get("champion"), Mapping)
            ),
            None,
        )
        reference = (
            dict(stages[reference_stage]["champion"])
            if reference_stage is not None
            else None
        )
        families[family] = {
            "champion": reference,
            "reference_stage": reference_stage,
            "latest": latest,
            "stages": stages,
        }

    body = {
        "schema": "alina.economic_improvement_ledger.v2",
        "policy": "MEILLEUR_RESULTAT_HISTORIQUE_COMPARABLE_PAR_MODULE_ET_ETAPE",
        "comparison_metric": "gain_net_usd_apres_couts",
        "amelioration_stricte_requise": True,
        "families": families,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    body["ledger_digest"] = _digest(body)
    return body


def build_receipt(
    manifest: Mapping[str, Any],
    scoreboard: Mapping[str, Any],
    *,
    evidence_tag: str,
    repository: str,
    unit_id: str,
    environment_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if manifest.get("schema_version") != "alina.resumable_campaign.v2":
        raise ValueError("scoreboard campaign must use resumable campaign v2")
    if manifest.get("kind") != "scoreboard" or manifest.get("creation_phase") != "ANALYZE":
        raise ValueError("receipt requires an ANALYZE scoreboard campaign")
    phase_epoch = manifest.get("phase_epoch")
    source_epoch = manifest.get("source_collection_epoch")
    if isinstance(phase_epoch, bool) or not isinstance(phase_epoch, int) or phase_epoch < 1:
        raise ValueError("invalid phase_epoch")
    if isinstance(source_epoch, bool) or not isinstance(source_epoch, int) or source_epoch < 1:
        raise ValueError("invalid source_collection_epoch")
    selection_id = str(manifest.get("dataset_selection_id") or "")
    code_sha = str(manifest.get("code_sha") or "")
    campaign_id = str(manifest.get("campaign_id") or "")
    cutoff = str(manifest.get("collection_cutoff_at_utc") or "")
    if not campaign_id or not selection_id or not cutoff:
        raise ValueError("campaign identity/selection/cutoff is incomplete")
    if len(code_sha) != 40 or any(ch not in "0123456789abcdef" for ch in code_sha.lower()):
        raise ValueError("invalid pinned code_sha")
    if scoreboard.get("schema_version") != "hypersmart.economic_family_scoreboards.v2":
        raise ValueError("unexpected economic scoreboard schema")
    if scoreboard.get("paper_read_only") is not True or scoreboard.get("real_execution") is not False:
        raise ValueError("scoreboard is not paper/read-only")
    if not evidence_tag or not repository:
        raise ValueError("durable evidence coordinates are required")

    scoreboard_copy = json.loads(json.dumps(dict(scoreboard), sort_keys=True))
    environment_copy = (
        json.loads(json.dumps(dict(environment_receipt), sort_keys=True))
        if isinstance(environment_receipt, Mapping)
        else None
    )
    if environment_copy is not None:
        if environment_copy.get("schema") != "alina.analysis_stage_artifact.v1":
            raise ValueError("unexpected analysis stage receipt schema")
        if environment_copy.get("analysis_stage") != "SCOREBOARD":
            raise ValueError("environment receipt is not from SCOREBOARD stage")
        if environment_copy.get("paper_only") is not True or environment_copy.get("real_execution") is not False:
            raise ValueError("environment receipt is not paper/read-only")
        provenance = environment_copy.get("environment_provenance")
        if not isinstance(provenance, Mapping) or not provenance:
            raise ValueError("environment provenance missing from SCOREBOARD stage receipt")

    body = {
        "schema": "alina.analysis_scoreboard_receipt.v1",
        "campaign_id": campaign_id,
        "unit_id": str(unit_id),
        "phase_epoch": phase_epoch,
        "source_collection_epoch": source_epoch,
        "collection_cutoff_at_utc": cutoff,
        "dataset_selection_id": selection_id,
        "code_sha": code_sha,
        "evidence_repository": str(repository),
        "evidence_tag": str(evidence_tag),
        "scoreboard_sha256": _digest(scoreboard_copy),
        "scoreboard": scoreboard_copy,
        "environment_receipt_sha256": (
            _digest(environment_copy) if environment_copy is not None else None
        ),
        "environment_provenance": (
            environment_copy.get("environment_provenance")
            if environment_copy is not None
            else None
        ),
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    body["receipt_digest"] = _digest(body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-manifest", required=True)
    parser.add_argument("--scoreboard", required=True)
    parser.add_argument("--evidence-tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--unit-id", required=True)
    parser.add_argument("--environment-receipt")
    parser.add_argument("--output", default="catalog/ANALYSIS_SCOREBOARD_RECEIPT.json")
    parser.add_argument("--improvement-ledger", default="catalog/ECONOMIC_IMPROVEMENT_LEDGER.json")
    args = parser.parse_args(argv)

    receipt = build_receipt(
        _load(Path(args.campaign_manifest)),
        _load(Path(args.scoreboard)),
        evidence_tag=args.evidence_tag,
        repository=args.repository,
        unit_id=args.unit_id,
        environment_receipt=(
            _load(Path(args.environment_receipt))
            if args.environment_receipt
            else None
        ),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    ledger_path = Path(args.improvement_ledger)
    previous_ledger = _load(ledger_path) if ledger_path.is_file() else None
    improvement_ledger = build_improvement_ledger(
        receipt["scoreboard"],
        previous_ledger,
        campaign_id=receipt["campaign_id"],
        phase_epoch=receipt["phase_epoch"],
        source_collection_epoch=receipt["source_collection_epoch"],
        dataset_selection_id=receipt["dataset_selection_id"],
        code_sha=receipt["code_sha"],
        analysis_stage="SCOREBOARD",
        evidence_tag=receipt["evidence_tag"],
        evidence_repository=receipt["evidence_repository"],
        unit_id=receipt["unit_id"],
    )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(improvement_ledger, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "output": str(output),
        "campaign_id": receipt["campaign_id"],
        "phase_epoch": receipt["phase_epoch"],
        "scoreboard_sha256": receipt["scoreboard_sha256"],
        "receipt_digest": receipt["receipt_digest"],
        "improvement_ledger": str(ledger_path),
        "improvement_ledger_digest": improvement_ledger["ledger_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
