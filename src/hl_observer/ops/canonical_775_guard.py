"""Canonical provenance/progress guard for the HyperSmart 1..775 roadmap.

Literal labels 321..775 remain unrecoverable and are never invented. Technical
progress is separate from literal provenance and only advances on specific
executable evidence.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ROADMAP_ID="HYPERSMART_PNL_CANONICAL_775"; ROADMAP_TOTAL=775
RECOVERY_CLOSED_SOURCE_LOSS="RECOVERY_CLOSED_SOURCE_LOSS"
IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST="IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST"
DONE_TECHNICAL_775_SOURCE_LOSS_HONEST="DONE_TECHNICAL_775_SOURCE_LOSS_HONEST"
THEMATIC_REQUIREMENTS_PATH="docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md"
TECHNICAL_GUARD_PATH="src/hl_observer/ops/pre_run_guard_321_775.py"
TECHNICAL_WORKFLOW_PATH=".github/workflows/pre-run-321-775.yml"
TECHNICAL_COMPLETION_MODE="EXISTING_CANONICAL_1_320_PLUS_SPECIFIC_EXECUTABLE_DERIVED_321_775"
KNOWN_CANONICAL_ANCHORS={301:"Interdire promotion par PnL sans coûts",314:"Reconstruction OPEN/ADD/REDUCE/CLOSE parfaite",315:"Retraits/dépôts non confondus avec PnL",316:"Wallet/vault identity stable",317:"Backfill complet",318:"Pagination userFillsByTime",319:"Déduplication fills",320:"Fraîcheur du leader"}
LEGACY_MASTER_V6_TOTAL=590
REQUIRED_SOURCE_SEARCHES={"GITHUB_REPOSITORY","GIT_HISTORY","CHAT_LIBRARY","PRIOR_CONVERSATION_CONTEXT"}
_PLACEHOLDER_LABELS={"x","todo","tbd","placeholder","unknown","inconnu","unrecovered","a recuperer","à récupérer","non recupere","non récupéré"}

def _literal_label(value:Any)->bool:
    if not isinstance(value,str): return False
    clean=" ".join(value.strip().split())
    if not clean: return False
    lowered=clean.casefold(); return lowered not in _PLACEHOLDER_LABELS and not lowered.startswith(("todo:","tbd:","placeholder:"))

def _proof_descriptor(value:Any)->str|None:
    if isinstance(value,str):
        clean=" ".join(value.strip().split()); return clean or None
    if isinstance(value,Mapping):
        for key in ("command","test","workflow","proof","path"):
            candidate=value.get(key)
            if isinstance(candidate,str) and candidate.strip(): return f"{key}:{' '.join(candidate.strip().split())}"
    return None

def _valid_sha256(value:Any)->bool:
    if not isinstance(value,str) or len(value)!=64: return False
    try: int(value,16)
    except ValueError: return False
    return True

def _validate_source_loss_provenance(manifest:Mapping[str,Any],issues:list[str],*,technical_completion_allowed:bool)->None:
    if manifest.get("literal_source_unrecoverable") is not True: issues.append("SOURCE_LOSS_REQUIRES_UNRECOVERABLE_TRUE")
    if manifest.get("exact_literal_reconstruction_claimed") is not False: issues.append("SOURCE_LOSS_FORBIDS_LITERAL_RECONSTRUCTION_CLAIM")
    if not technical_completion_allowed and manifest.get("technical_completion_claimed") is not False: issues.append("SOURCE_LOSS_FORBIDS_TECHNICAL_COMPLETION_CLAIM")
    if manifest.get("blocking") is not False: issues.append("SOURCE_LOSS_TERMINAL_MUST_BE_NONBLOCKING")
    if manifest.get("next_unrecovered_literal") is not None: issues.append("SOURCE_LOSS_TERMINAL_HAS_NO_NEXT_LITERAL")
    if manifest.get("thematic_requirements_path")!=THEMATIC_REQUIREMENTS_PATH: issues.append("SOURCE_LOSS_REQUIRES_THEMATIC_REQUIREMENTS_PATH")
    if not _valid_sha256(manifest.get("thematic_requirements_sha256")): issues.append("SOURCE_LOSS_REQUIRES_VALID_THEMATIC_SHA256")
    reason=manifest.get("source_loss_reason")
    if not isinstance(reason,str) or len(reason.strip())<20: issues.append("SOURCE_LOSS_REQUIRES_EXPLICIT_REASON")
    searches=manifest.get("source_searches_completed")
    if not isinstance(searches,Sequence) or isinstance(searches,(str,bytes)): searches=[]
    if not REQUIRED_SOURCE_SEARCHES.issubset({str(item) for item in searches}): issues.append("SOURCE_LOSS_REQUIRES_ALL_SOURCE_SEARCHES")
    recovered=manifest.get("recovered_literal_labels"); recovered=recovered if isinstance(recovered,Mapping) else {}
    for number,expected in KNOWN_CANONICAL_ANCHORS.items():
        if recovered.get(str(number),recovered.get(number))!=expected: issues.append(f"SOURCE_LOSS_RECOVERED_ANCHOR_MISMATCH:{number}")
    if manifest.get("recovered_literal_count")!=len(KNOWN_CANONICAL_ANCHORS): issues.append("SOURCE_LOSS_RECOVERED_COUNT_MISMATCH")
    if manifest.get("labels") not in (None,[],{}): issues.append("SOURCE_LOSS_FORBIDS_CANONICAL_LABEL_SET")
    if manifest.get("proofs") not in (None,[],{}): issues.append("SOURCE_LOSS_FORBIDS_775_LITERAL_PROOF_CLAIM")

def _validate_progress(manifest:Mapping[str,Any],issues:list[str])->None:
    _validate_source_loss_provenance(manifest,issues,technical_completion_allowed=False)
    if manifest.get("technical_completion_total")!=ROADMAP_TOTAL: issues.append("TECHNICAL_PROGRESS_REQUIRES_TOTAL_775")
    done=manifest.get("technical_completion_done")
    if not isinstance(done,int) or not (320<=done<ROADMAP_TOTAL): issues.append("TECHNICAL_PROGRESS_DONE_RANGE_INVALID")
    if manifest.get("technical_completion_mode")!=TECHNICAL_COMPLETION_MODE: issues.append("TECHNICAL_PROGRESS_WRONG_MODE")
    if manifest.get("technical_completion_guard")!=TECHNICAL_GUARD_PATH: issues.append("TECHNICAL_PROGRESS_WRONG_GUARD_PATH")
    if manifest.get("technical_completion_workflow")!=TECHNICAL_WORKFLOW_PATH: issues.append("TECHNICAL_PROGRESS_WRONG_WORKFLOW_PATH")
    derived=manifest.get("derived_technical_controls"); derived=derived if isinstance(derived,Mapping) else {}
    expected={"start":321,"end":775,"count":455,"base_requirements":91,"facets":5,"historical_literal":False,"provenance":"DERIVED_TECHNICAL_REQUIREMENT"}
    for key,value in expected.items():
        if derived.get(key)!=value: issues.append(f"TECHNICAL_PROGRESS_DERIVED_MISMATCH:{key}")
    derived_done=derived.get("done")
    if not isinstance(done,int) or not isinstance(derived_done,int) or done!=320+derived_done or not (0<=derived_done<455): issues.append("TECHNICAL_PROGRESS_DERIVED_DONE_MISMATCH")
    prior=manifest.get("prior_canonical_controls"); prior=prior if isinstance(prior,Mapping) else {}
    if prior.get("start")!=1 or prior.get("end")!=320 or prior.get("count")!=320: issues.append("TECHNICAL_PROGRESS_PRIOR_1_320_MISMATCH")

def _validate_technical_done(manifest:Mapping[str,Any],issues:list[str])->None:
    _validate_source_loss_provenance(manifest,issues,technical_completion_allowed=True)
    if manifest.get("technical_completion_claimed") is not True: issues.append("TECHNICAL_DONE_REQUIRES_COMPLETION_TRUE")
    if manifest.get("technical_completion_total")!=ROADMAP_TOTAL: issues.append("TECHNICAL_DONE_REQUIRES_TOTAL_775")
    if manifest.get("technical_completion_done")!=ROADMAP_TOTAL: issues.append("TECHNICAL_DONE_REQUIRES_DONE_775")
    if manifest.get("technical_completion_mode")!=TECHNICAL_COMPLETION_MODE: issues.append("TECHNICAL_DONE_WRONG_MODE")
    if manifest.get("technical_completion_guard")!=TECHNICAL_GUARD_PATH: issues.append("TECHNICAL_DONE_WRONG_GUARD_PATH")
    if manifest.get("technical_completion_workflow")!=TECHNICAL_WORKFLOW_PATH: issues.append("TECHNICAL_DONE_WRONG_WORKFLOW_PATH")
    derived=manifest.get("derived_technical_controls"); derived=derived if isinstance(derived,Mapping) else {}
    expected={"start":321,"end":775,"count":455,"done":455,"base_requirements":91,"facets":5,"historical_literal":False,"provenance":"DERIVED_TECHNICAL_REQUIREMENT"}
    for key,value in expected.items():
        if derived.get(key)!=value: issues.append(f"TECHNICAL_DONE_DERIVED_MISMATCH:{key}")

def validate_manifest(manifest:Mapping[str,Any])->dict[str,Any]:
    issues=[]
    if manifest.get("roadmap_id")!=ROADMAP_ID: issues.append("WRONG_ROADMAP_ID")
    if manifest.get("total")!=ROADMAP_TOTAL: issues.append("WRONG_ROADMAP_TOTAL")
    if manifest.get("legacy_master_v6_equivalent") is not False: issues.append("LEGACY_V6_MUST_NOT_BE_DECLARED_EQUIVALENT")
    anchors=manifest.get("anchors"); anchors=anchors if isinstance(anchors,Mapping) else {}
    for number,expected in KNOWN_CANONICAL_ANCHORS.items():
        if anchors.get(str(number),anchors.get(number))!=expected: issues.append(f"CANONICAL_ANCHOR_MISMATCH:{number}")
    status=str(manifest.get("status") or "").upper()
    if status=="DONE":
        labels=manifest.get("labels"); proofs=manifest.get("proofs")
        labels=labels if isinstance(labels,Sequence) and not isinstance(labels,(str,bytes)) else []; proofs=proofs if isinstance(proofs,Mapping) else {}
        if len(labels)!=ROADMAP_TOTAL: issues.append("DONE_REQUIRES_775_LITERAL_LABELS")
        elif not all(_literal_label(label) for label in labels): issues.append("DONE_REQUIRES_LITERAL_NON_PLACEHOLDER_LABELS")
        else:
            for number,expected in KNOWN_CANONICAL_ANCHORS.items():
                if labels[number-1]!=expected: issues.append(f"DONE_LITERAL_LABEL_MISMATCH:{number}")
        expected_numbers=set(range(1,ROADMAP_TOTAL+1)); proof_numbers=set(); descriptors=[]; invalid=0
        for key,value in proofs.items():
            try: number=int(key)
            except (TypeError,ValueError): continue
            descriptor=_proof_descriptor(value)
            if descriptor is None: invalid+=1; continue
            proof_numbers.add(number); descriptors.append(descriptor)
        if proof_numbers!=expected_numbers or invalid: issues.append("DONE_REQUIRES_775_EXECUTABLE_PROOFS")
        if len(descriptors)!=ROADMAP_TOTAL or len(set(descriptors))!=ROADMAP_TOTAL: issues.append("DONE_REQUIRES_775_DISTINCT_EXECUTABLE_PROOFS")
    elif status==RECOVERY_CLOSED_SOURCE_LOSS: _validate_source_loss_provenance(manifest,issues,technical_completion_allowed=False)
    elif status==IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST: _validate_progress(manifest,issues)
    elif status==DONE_TECHNICAL_775_SOURCE_LOSS_HONEST: _validate_technical_done(manifest,issues)
    else: issues.append("UNKNOWN_CANONICAL_STATUS")
    return {"ok":not issues,"roadmap_id":ROADMAP_ID,"roadmap_total":ROADMAP_TOTAL,"status":status or "UNKNOWN","terminal_recovery":status in {RECOVERY_CLOSED_SOURCE_LOSS,IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST,DONE_TECHNICAL_775_SOURCE_LOSS_HONEST} and not issues,"technical_completion_claimed":bool(manifest.get("technical_completion_claimed")),"technical_done":manifest.get("technical_completion_done",0),"issues":issues}

__all__=["DONE_TECHNICAL_775_SOURCE_LOSS_HONEST","IN_PROGRESS_TECHNICAL_775_SOURCE_LOSS_HONEST","KNOWN_CANONICAL_ANCHORS","LEGACY_MASTER_V6_TOTAL","RECOVERY_CLOSED_SOURCE_LOSS","REQUIRED_SOURCE_SEARCHES","ROADMAP_ID","ROADMAP_TOTAL","TECHNICAL_COMPLETION_MODE","TECHNICAL_GUARD_PATH","TECHNICAL_WORKFLOW_PATH","THEMATIC_REQUIREMENTS_PATH","validate_manifest"]
