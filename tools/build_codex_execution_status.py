"""Build the exhaustive Codex execution ledger from the master roadmap.

The generated document is deliberately fail-closed: a roadmap work unit is
PENDING_AUDIT until an explicit evidence override links it to current tests and
commits.  Historical/rejected items remain visible instead of being deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

WORK_UNIT_RE = re.compile(
    r"^#{2,4}\s+"
    r"(?P<id>(?:V\d+(?:\.\d+)?-(?:WU-)?P\d+-\d+)|(?:HS-(?:NEW-)?\d+))"
    r"\s*(?:[-—:]\s*)?(?P<title>.*)$"
)
STATUS_RE = re.compile(r"\*\*Status\s*:\s*\*\*\s*`?([^`\n]+)", re.IGNORECASE)
TRACE_ONLY_MARKERS = (
    "DUPLICATE",
    "HISTORICAL",
    "KILLED",
    "REJECT",
    "SUPERSEDED",
)


@dataclass(frozen=True, slots=True)
class WorkUnit:
    identifier: str
    title: str
    roadmap_disposition: str


@dataclass(frozen=True, slots=True)
class Evidence:
    state: str
    proof: str
    tests: str
    commits: str
    blocker: str
    next_action: str


def _verified(
    proof: str,
    tests: str,
    commits: str,
) -> Evidence:
    return Evidence(
        state="VERIFIED",
        proof=proof,
        tests=tests,
        commits=commits,
        blocker="Aucun",
        next_action="Conserver la regression et revalider dans la suite globale.",
    )


V21_EVIDENCE: dict[str, Evidence] = {
    "V21-P0-001": _verified(
        "Registre type et snapshots dans economics/assumptions.py et families.py.",
        "tests/test_economic_assumption_registry_v21.py",
        "9eef2f0a",
    ),
    "V21-P0-002": _verified(
        "DAG de formules et invalidation des descendants lies aux parents.",
        "tests/test_economic_assumption_registry_v21.py",
        "9eef2f0a, 21ebbea6",
    ),
    "V21-P0-003": _verified(
        "Les modes certifiables refusent source/config invalide; fallback explore non certifiable.",
        "tests/test_economic_assumption_registry_v21.py",
        "9eef2f0a, 863ce087",
    ),
    "V21-P0-004": _verified(
        "Evenements de controle types, schema ferme, capability allowlist et recu append-only.",
        "tests/test_typed_control_events_v21.py",
        "8839b4b8",
    ),
    "V21-P0-005": _verified(
        "CAS immuable, projection bornee et writer refusant les sources brutes.",
        "tests/test_untrusted_projection_air_gap_v21.py",
        "565aa562",
    ),
    "V21-P0-006": _verified(
        "Reconciliation exacte declare/charge avec digest de surface et motifs d'indisponibilite.",
        "tests/test_capability_reconciliation.py",
        "7a55180b",
    ),
    "V21-P1-001": _verified(
        "Hash du snapshot lie aux campagnes, trades, scoreboards, audits et certification.",
        "tests/test_economic_assumption_registry_v21.py; tests/test_economic_campaigns.py",
        "21ebbea6",
    ),
    "V21-P1-002": _verified(
        "Autorite de frais canonique commune aux trois familles avec formules de fills propres.",
        "tests/test_economic_assumption_registry_v21.py; tests/test_dislocation_2jambes.py",
        "863ce087, 21ebbea6",
    ),
    "V21-P1-003": _verified(
        "Scanner AST proposition-only distinguant conversions, schemas et autorites canoniques.",
        "tests/test_economic_hardcode_scanner_v21.py",
        "b9787ee9",
    ),
    "V21-P1-004": _verified(
        "Mutations deterministes fee/latence/notional et invariants non dependants.",
        "tests/test_economic_assumption_registry_v21.py",
        "21ebbea6",
    ),
    "V21-P1-005": _verified(
        "Zeros materiels lies a un ZeroCostReason; MISSING_UNMEASURABLE non certifiable.",
        "tests/test_economic_assumption_registry_v21.py; tests/test_economic_proof_audit.py",
        "21ebbea6",
    ),
    "V21-P1-006": _verified(
        "Recu lie formule, fill-count, frais, spread, latence, funding, slippage et capacite.",
        "tests/test_economic_assumption_registry_v21.py; tests/test_final_economic_certification.py",
        "21ebbea6",
    ),
    "V21-P1-007": _verified(
        "Pointeurs numeriques reconstruisent la chaine hypothese/formule/evidence.",
        "tests/test_economic_assumption_registry_v21.py; tests/test_economic_family_scoreboard.py",
        "21ebbea6",
    ),
    "V21-P1-008": _verified(
        "Contrat monotone BUILT->AUDIT->STRESS->OOS->FORWARD->PROMOTABLE.",
        "tests/test_economic_assumption_registry_v21.py; tests/test_final_economic_certification.py",
        "21ebbea6",
    ),
    "V21-P1-009": _verified(
        "Recu global fail-closed couvrant reconciliation, couts manquants, peremption, double comptage, hardcodes, zeros, dependances et fraicheur.",
        "tests/test_economic_proof_audit.py; tests/test_economic_hardcode_scanner_v21.py; tests/test_dislocation_2jambes.py",
        "64476606",
    ),
    "V21-P1-010": _verified(
        "Vues interactive/headless derivees de la meme requete worker et recu de parite fail-closed.",
        "tests/test_runtime_harness_parity_v21.py; tests/test_alina_self_hosted_control.py",
        "e38ae148",
    ),
    "V21-P1-011": _verified(
        "Budgets fermes sur tableaux, chaines, profondeur et projection; brut conserve en CAS.",
        "tests/test_untrusted_projection_air_gap_v21.py",
        "565aa562",
    ),
    "V21-P1-012": _verified(
        "Event id, nonce, source run, version d'etat et ledger single-use anti-rejeu.",
        "tests/test_typed_control_events_v21.py",
        "8839b4b8",
    ),
    "V21-P1-013": _verified(
        "Canary semantique positif et statut readiness par connecteur requis.",
        "tests/test_capability_reconciliation.py; tests/test_venue_capabilities.py",
        "7a55180b",
    ),
    "V21-P1-014": _verified(
        "Recu expected/loaded/unavailable/disabled avec mismatch bloquant.",
        "tests/test_capability_reconciliation.py",
        "7a55180b",
    ),
    "V21-P1-015": _verified(
        "Substitution source explicite, typee, raisonnee et liee aux identites attendue/chargee.",
        "tests/test_capability_reconciliation.py",
        "7a55180b",
    ),
    "V21-P1-016": _verified(
        "Entitlement, licence et redistribution portes par les sources/projections.",
        "tests/test_capability_reconciliation.py; tests/test_untrusted_projection_air_gap_v21.py",
        "565aa562, 7a55180b",
    ),
    "V21-P1-017": _verified(
        "Pointeur/hash source, spans et versions parser/projection rederivables.",
        "tests/test_untrusted_projection_air_gap_v21.py",
        "565aa562",
    ),
    "V21-P1-018": _verified(
        "Campagne, raw trades, scoreboard, audit et certification partagent le meme contrat economique.",
        "tests/test_economic_campaigns.py; tests/test_economic_family_scoreboard.py; tests/test_final_economic_certification.py",
        "21ebbea6",
    ),
    "V21-P1-019": _verified(
        "Sources reference-only non production-ready; adoption locale conditionnee aux tests.",
        "tests/test_external_evidence_governance_v21.py",
        "acab4571",
    ),
    "V21-P1-020": _verified(
        "Chronologie artefact/post/prior-match classe la recirculation sans autorite de fraicheur.",
        "tests/test_external_evidence_governance_v21.py",
        "acab4571",
    ),
}

V26_EVIDENCE: dict[str, Evidence] = {
    "V26-P0-001": _verified(
        "Spine local multi-producteur avec inbox isolees, writer OS unique, ledger append-only fsync, reprise crash idempotente et projection dashboard reconstruisible.",
        "tests/test_alert_spine_v26.py; tests/test_collecte_fiable.py; tests/test_jsonl_stream.py; tests/test_raw_spool_et_side_lock.py",
        "a1a443f0",
    ),
    "V26-P0-002": _verified(
        "Enveloppe versionnee fail-closed avec provenance hashee, horloges monotones, cycle ADMITTED immuable et etats PROJECTED/EXPIRED/CORRECTED/RETRACTED derives sans destruction.",
        "tests/test_alert_envelope_v26.py; tests/test_alert_spine_v26.py",
        "28f0154d",
    ),
    "V26-P0-003": _verified(
        "Epoque et sequence producteur explicites, identite source/fallback stable, gaps visibles, curseurs durables hashes, retry a effet unique et hash de projection reproductible.",
        "tests/test_alert_idempotency_v26.py; tests/test_alert_spine_v26.py; tests/test_alert_envelope_v26.py",
        "b4c46c6c",
    ),
    "V26-P0-004": _verified(
        "Score de classement versionne, pondere, hashe et ablate; opinion modele exclue de l autorite, admissibilite economique separee et capacites d ordre interdites.",
        "tests/test_alert_scoring_v26.py; tests/test_alert_idempotency_v26.py",
        "425f33c0",
    ),
    "V26-P0-005": _verified(
        "Horloges source/observation/parsing separees, etats frais/degrades/stale derives, SLO et distributions p50/p95/p99, gaps et NO_NEWS invalides sur source silencieuse.",
        "tests/test_alert_freshness_v26.py; tests/test_alert_envelope_v26.py",
        "92aa8672",
    ),
    "V26-P0-006": _verified(
        "Matrice complete a 18 axes et verdict fail-closed; la configuration Roh/MAX face a Bloomberg reste honnetement PARTIAL_SUBSTITUTE avec recu hashe.",
        "tests/test_replacement_parity_v26.py",
        "8e4a7517",
    ),
    "V26-P1-001": _verified(
        "Spools isoles par producteur, publication temporaire fsync puis lien exclusif, schema/epoque/sequence/hash payload verifies, archives immuables et reprise sans perte apres terminaison brutale.",
        "tests/test_alert_spool_v26.py; tests/test_alert_spine_v26.py",
        "48ff58fe",
    ),
    "V26-P1-002": _verified(
        "Ledger natif JSONL sous verrou unique, append+fsync, segments immuables hashes, rotation bornee et pointeur latest atomique validant le prefixe sans base de donnees prematuree.",
        "tests/test_alert_ledger_v26.py; tests/test_alert_spine_v26.py",
        "a0162181",
    ),
}


def parse_work_units(text: str) -> list[WorkUnit]:
    lines = text.splitlines()
    heading_indexes: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = WORK_UNIT_RE.match(line)
        if match:
            heading_indexes.append((index, match))

    rows: list[WorkUnit] = []
    for position, (index, match) in enumerate(heading_indexes):
        end = heading_indexes[position + 1][0] if position + 1 < len(heading_indexes) else len(lines)
        section = "\n".join(lines[index + 1 : end])
        status_match = STATUS_RE.search(section)
        disposition = status_match.group(1).strip(" .") if status_match else "UNSPECIFIED"
        rows.append(
            WorkUnit(
                identifier=match.group("id"),
                title=match.group("title").strip() or "(sans titre)",
                roadmap_disposition=disposition,
            )
        )
    return rows


def _head(root: Path) -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    return process.stdout.strip() if process.returncode == 0 else "UNAVAILABLE"


def _trace_only(disposition: str) -> bool:
    normalized = disposition.upper()
    return any(marker in normalized for marker in TRACE_ONLY_MARKERS)


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def evidence_for(unit: WorkUnit) -> Evidence:
    if unit.identifier in V21_EVIDENCE:
        return V21_EVIDENCE[unit.identifier]
    if unit.identifier in V26_EVIDENCE:
        return V26_EVIDENCE[unit.identifier]
    if _trace_only(unit.roadmap_disposition):
        return Evidence(
            state="TRACE_ONLY",
            proof=f"Disposition explicite: {unit.roadmap_disposition}.",
            tests="N/A",
            commits="N/A",
            blocker="Aucun",
            next_action="Conserver la classification; ne pas reactiver sans nouvelle preuve.",
        )
    return Evidence(
        state="PENDING_AUDIT",
        proof="Preuve HEAD non encore rattachee.",
        tests="Aucun test qualifie dans ce ledger.",
        commits="Aucun commit qualifie dans ce ledger.",
        blocker="Etat actuel insuffisamment audite.",
        next_action=f"Auditer {unit.identifier} contre code, tests et runtime actuels.",
    )


def render_status(*, units: list[WorkUnit], roadmap_sha256: str, head: str) -> str:
    evidence = [evidence_for(unit) for unit in units]
    counts: dict[str, int] = {}
    for row in evidence:
        counts[row.state] = counts.get(row.state, 0) + 1
    lines = [
        "# CODEX EXECUTION STATUS",
        "",
        "> Ledger fail-closed genere depuis chaque heading canonique de la roadmap. ",
        "> `PENDING_AUDIT` signifie que la preuve manque; ce n'est jamais un DONE implicite.",
        "",
        f"- Roadmap SHA256: `{roadmap_sha256}`",
        f"- HEAD audite: `{head}`",
        f"- Work units uniques: **{len(units)}**",
        f"- Etats: `{', '.join(f'{key}={counts[key]}' for key in sorted(counts))}`",
        "- Invariant: PAPER/READ-ONLY; aucune execution reelle ou testnet.",
        "",
        "| ID | Exigence | Disposition roadmap | Etat | Preuve | Tests | Commits | Blocage | Prochaine action |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for unit, row in zip(units, evidence, strict=True):
        lines.append(
            "| "
            + " | ".join(
                _escape(value)
                for value in (
                    unit.identifier,
                    unit.title,
                    unit.roadmap_disposition,
                    row.state,
                    row.proof,
                    row.tests,
                    row.commits,
                    row.blocker,
                    row.next_action,
                )
            )
            + " |"
        )
    next_pending = next(
        (unit for unit, row in zip(units, evidence, strict=True) if row.state == "PENDING_AUDIT"),
        None,
    )
    next_action = (
        f"Auditer `{next_pending.identifier}` contre le HEAD, les tests et le runtime, "
        "puis fermer uniquement les exigences réellement prouvees."
        if next_pending is not None
        else "Executer l'audit final requirement-by-requirement avant toute declaration de completion."
    )
    lines.extend(
        [
            "",
            "## Prochaine action canonique",
            "",
            next_action,
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roadmap", type=Path, default=Path("HYPERSMART_MASTER_ROADMAP.md"))
    parser.add_argument("--output", type=Path, default=Path("CODEX_EXECUTION_STATUS.md"))
    parser.add_argument("--expected-count", type=int, default=720)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    roadmap = args.roadmap if args.roadmap.is_absolute() else root / args.roadmap
    output = args.output if args.output.is_absolute() else root / args.output
    source = roadmap.read_text(encoding="utf-8")
    units = parse_work_units(source)
    identifiers = [unit.identifier for unit in units]
    if len(units) != args.expected_count or len(set(identifiers)) != len(identifiers):
        raise SystemExit(
            f"Inventaire refuse: rows={len(units)} unique={len(set(identifiers))} "
            f"expected={args.expected_count}"
        )
    payload = render_status(
        units=units,
        roadmap_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        head=_head(root),
    )
    output.write_text(payload, encoding="utf-8")
    print(f"CODEX_EXECUTION_STATUS_READY rows={len(units)} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
