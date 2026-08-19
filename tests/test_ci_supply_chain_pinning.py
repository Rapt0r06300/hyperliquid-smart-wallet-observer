from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

CHECKOUT_SHA = "11d5960a326750d5838078e36cf38b85af677262"
SETUP_PYTHON_SHA = "a26af69be951a213d495a4c3e4e4022e16d87065"
UPLOAD_ARTIFACT_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
ATTEST_BUILD_PROVENANCE_SHA = "e8998f949152b193b063cb0ec769d69d929409be"

PINNED = {
    "actions/checkout": CHECKOUT_SHA,
    "actions/setup-python": SETUP_PYTHON_SHA,
    "actions/upload-artifact": UPLOAD_ARTIFACT_SHA,
    "actions/attest-build-provenance": ATTEST_BUILD_PROVENANCE_SHA,
}


def _texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.yml"))}


def test_all_github_actions_are_pinned_to_immutable_shas():
    failures: list[str] = []
    for name, text in _texts().items():
        for action, ref in re.findall(r"uses:\s*([^@\s]+)@([^\s#]+)", text):
            if action.startswith("./"):
                continue
            if action in PINNED:
                if ref != PINNED[action]:
                    failures.append(f"{name}: {action}@{ref}")
            elif not re.fullmatch(r"[0-9a-f]{40}", ref):
                failures.append(f"{name}: action externe non pinnee {action}@{ref}")
    assert not failures, "Actions flottantes/non approuvees: " + "; ".join(failures)


def test_checkout_ne_persiste_aucun_credential_sur_les_workflows_qui_checkout():
    failures: list[str] = []
    needle = f"uses: actions/checkout@{CHECKOUT_SHA}"
    for name, text in _texts().items():
        if needle not in text:
            continue
        segments = text.split(needle)[1:]
        for index, segment in enumerate(segments, start=1):
            step = segment.split("\n      - ", 1)[0]
            if "persist-credentials: false" not in step:
                failures.append(f"{name} checkout #{index}")
    assert not failures, "Checkout avec credentials persistants: " + "; ".join(failures)


def test_workflows_ci_et_recherche_sont_read_only_par_defaut():
    exempt = {
        "portable-release-windows.yml",  # attestation OIDC: écriture attendue
        "branch-hygiene-once.yml",       # suppression one-shot de refs dependabot/* uniquement
    }
    failures: list[str] = []
    for name, text in _texts().items():
        if name == "portable-release-windows.yml":
            assert "contents: read" in text
            continue
        if name == "branch-hygiene-once.yml":
            assert "contents: write" in text
            continue
        if "permissions:" not in text or "contents: read" not in text:
            failures.append(name)
    assert not failures, "Workflow sans permissions contents:read explicites: " + ", ".join(failures)


def test_nettoyeur_one_shot_ne_peut_pas_toucher_main():
    path = WORKFLOWS / "branch-hygiene-once.yml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    assert "refs/heads/dependabot/" in text
    assert "REF == 'refs/heads/main'" in text
    assert "REFUSED_NON_DEPENDABOT_REF" in text
    assert "contents: write" in text
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
