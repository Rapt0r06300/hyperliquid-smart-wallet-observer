from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
LEGACY_CHECKOUT_SHA = "11d5960a326750d5838078e36cf38b85af677262"
HISTORICAL_CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
LEGACY_SETUP_PYTHON_SHA = "a26af69be951a213d495a4c3e4e4022e16d87065"
LEGACY_UPLOAD_ARTIFACT_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
ATTEST_BUILD_PROVENANCE_SHA = "e8998f949152b193b063cb0ec769d69d929409be"

PINNED = {
    "actions/checkout": frozenset({HISTORICAL_CHECKOUT_SHA, LEGACY_CHECKOUT_SHA, CHECKOUT_SHA}),
    "actions/setup-python": frozenset({LEGACY_SETUP_PYTHON_SHA, SETUP_PYTHON_SHA}),
    "actions/upload-artifact": frozenset({LEGACY_UPLOAD_ARTIFACT_SHA, UPLOAD_ARTIFACT_SHA}),
    "actions/attest-build-provenance": frozenset({ATTEST_BUILD_PROVENANCE_SHA}),
}

# These workflows intentionally mutate the canonical repository/control plane.
# The allowlist is closed: any new workflow remains read-only by default until
# its mutation requirement is reviewed and added here.
MUTATING_WORKFLOWS = frozenset({
    "advance-analysis-stage.yml",
    "alina-operator-dispatch.yml",
    "analysis-stage-controller.yml",
    "backfill-exact-trade-counts.yml",
    "backfill-global-unique-trade-counts.yml",
    "backfill-replay-compatibility.yml",
    "campaign-resilience-receipt.yml",
    "campaign-watchdog.yml",
    "collect-and-publish-v2.yml",
    "collect-copy-vault-v2.yml",
    "collect-event-intelligence-v2.yml",
    "collect-market-data-v2.yml",
    "collect-official-archives-v2.yml",
    "control-phase.yml",
    "copy-vault-v2-smoke.yml",
    "create-resumable-campaigns.yml",
    "dataset-health-receipt.yml",
    "dataset-metrics-v2.yml",
    "dataset-v2-smoke.yml",
    "durable-two-segment-resume-smoke.yml",
    "global-implementation-closure.yml",
    "migrate-campaign-manifests-v2.yml",
    "phase-request-controller.yml",
    "portable-wheelhouse-security-once.yml",
    "promote-manifest.yml",
    "reconcile-v2-catalog.yml",
    "recover-current-market-publication.yml",
    "resumable-campaign-worker.yml",
    "uncompressed-size-v2.yml",
    "clone-lfs-probe.yml",
    "clone-payload-lfs-mirror.yml",
    "collect-two-segment-resume-smoke.yml",
    "quarantine-audit.yml",
    "recover-durable-publication.yml",
})


def _texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.yml"))}


def test_all_github_actions_are_pinned_to_immutable_shas():
    failures: list[str] = []
    for name, text in _texts().items():
        for action, ref in re.findall(r"uses:\s*([^@\s]+)@([^\s#]+)", text):
            if action.startswith("./"):
                continue
            if action in PINNED:
                if ref not in PINNED[action]:
                    failures.append(f"{name}: {action}@{ref}")
            elif not re.fullmatch(r"[0-9a-f]{40}", ref):
                failures.append(f"{name}: action externe non pinnee {action}@{ref}")
    assert not failures, "Actions flottantes/non approuvees: " + "; ".join(failures)


def test_read_only_checkouts_ne_persistent_aucun_credential():
    failures: list[str] = []
    for name, text in _texts().items():
        if name in MUTATING_WORKFLOWS:
            continue
        for checkout_sha in PINNED["actions/checkout"]:
            needle = f"uses: actions/checkout@{checkout_sha}"
            if needle not in text:
                continue
            segments = text.split(needle)[1:]
            for index, segment in enumerate(segments, start=1):
                step = segment.split("\n      - ", 1)[0]
                if "persist-credentials: false" not in step:
                    failures.append(f"{name} checkout #{index}")
    assert not failures, "Checkout read-only avec credentials persistants: " + "; ".join(failures)


def test_workflows_ci_et_recherche_sont_read_only_par_defaut():
    failures: list[str] = []
    for name, text in _texts().items():
        if name in MUTATING_WORKFLOWS:
            if "permissions:" not in text or "contents: write" not in text:
                failures.append(f"{name} (mutation sans contents:write explicite)")
            continue
        if "permissions:" not in text or "contents: read" not in text:
            failures.append(name)
    assert not failures, "Workflow sans permissions explicites conformes: " + ", ".join(failures)


def test_reparation_portable_one_shot_est_strictement_bornee_et_auto_supprimee():
    path = WORKFLOWS / "portable-wheelhouse-security-once.yml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    assert "contents: write" in text
    assert "persist-credentials: false" in text
    assert "pytest-9.0.3-py3-none-any.whl" in text
    assert "2c5efc453d45394fdd706ade797c0a81091eccd1d6e4bccfcd476e2b8e0ab5d9" in text
    assert "375249" in text
    assert "git rm .github/workflows/portable-wheelhouse-security-once.yml" in text
    assert "git push origin HEAD:main" in text
    assert "pull_request" not in text


def test_aucun_tag_flottant_connu_ne_reapparait():
    text = "\n".join(_texts().values())
    for floating in (
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
        "actions/attest-build-provenance@v2",
        "@main",
        "@master",
    ):
        assert floating not in text, floating


def test_pre_run_101_200_clean_gate_precedes_workspace_mutating_setup():
    text = (WORKFLOWS / "pre-run-101-200.yml").read_text(encoding="utf-8")
    gate = text.index("Gate initial exact HEAD securite et couverture")
    setup = text.index("uses: actions/setup-python@")
    install = text.index("Installer dependances fail-closed")
    assert gate < setup
    assert gate < install
