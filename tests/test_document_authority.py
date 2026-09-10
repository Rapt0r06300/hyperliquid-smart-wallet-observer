from __future__ import annotations

from pathlib import Path

from hl_observer.ops.document_authority import (
    REQUIRED_ACTIVE_DOCUMENTS,
    REQUIRED_CONSTITUTION_MARKERS,
    audit_document_authority,
    render_document_authority_report,
)


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_valid_authority(root: Path) -> None:
    constitution = "\n".join(REQUIRED_CONSTITUTION_MARKERS)
    for relative_path in REQUIRED_ACTIVE_DOCUMENTS:
        content = constitution if relative_path == "docs/HYPERSMART_CONSTITUTION.md" else "safe"
        _write(root, relative_path, content)
    _write(root, "AGENTS.md", "docs/HYPERSMART_CONSTITUTION.md\n")
    _write(root, "CLAUDE.md", "HL_ENABLE_TESTNET_EXECUTION=1\n")


def test_current_repository_document_authority_is_clean() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    issues = audit_document_authority(repo_root)
    assert render_document_authority_report(issues) == "DOCUMENT_AUTHORITY=PASS"


def test_rejects_unsafe_directive_in_active_agent_rules(tmp_path: Path) -> None:
    _seed_valid_authority(tmp_path)
    _write(
        tmp_path,
        "AGENTS.md",
        "docs/HYPERSMART_CONSTITUTION.md\nHL_ENABLE_TESTNET_EXECUTION=1\n",
    )

    issues = audit_document_authority(tmp_path)

    assert [issue.code for issue in issues] == ["UNSAFE_ACTIVE_DIRECTIVE"]
    assert issues[0].path == "AGENTS.md"
    assert issues[0].line == 2


def test_historical_claude_directives_do_not_override_active_policy(tmp_path: Path) -> None:
    _seed_valid_authority(tmp_path)

    assert audit_document_authority(tmp_path) == []


def test_missing_active_document_fails_closed(tmp_path: Path) -> None:
    _seed_valid_authority(tmp_path)
    (tmp_path / "SECURITY.md").unlink()

    issues = audit_document_authority(tmp_path)

    assert any(issue.code == "MISSING_ACTIVE_DOCUMENT" for issue in issues)
