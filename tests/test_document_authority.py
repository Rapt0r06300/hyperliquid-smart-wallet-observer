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
    scope_path = Path(__file__).resolve().parents[1] / "src/hl_observer/strategies/active_scope.py"
    _write(root, "src/hl_observer/strategies/active_scope.py", scope_path.read_text(encoding="utf-8"))
    _write(
        root,
        "SECURITY.md",
        "## 8. Scope économique effectif\n"
        "Famille économique active unique : **Copy-Vault**.\n",
    )
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


def test_scope_authority_reference_points_to_the_existing_machine_file() -> None:
    assert "src/hl_observer/strategies/active_scope.py" in REQUIRED_CONSTITUTION_MARKERS
    assert "schema/active_scope.json" not in REQUIRED_CONSTITUTION_MARKERS


def test_security_document_cannot_activate_families_disabled_by_machine_scope(
    tmp_path: Path,
) -> None:
    _seed_valid_authority(tmp_path)
    _write(
        tmp_path,
        "SECURITY.md",
        "Familles actives : Copy-Vault, Lead-Lag et Cross-Venue.\n",
    )

    issues = audit_document_authority(tmp_path)

    assert "SECURITY_ACTIVE_SCOPE_CONTRADICTION" in {issue.code for issue in issues}


def test_missing_machine_scope_file_fails_closed(tmp_path: Path) -> None:
    _seed_valid_authority(tmp_path)
    (tmp_path / "src/hl_observer/strategies/active_scope.py").unlink()

    issues = audit_document_authority(tmp_path)

    assert "MISSING_ACTIVE_SCOPE_AUTHORITY" in {issue.code for issue in issues}


def test_machine_scope_cannot_activate_a_second_economic_family(tmp_path: Path) -> None:
    _seed_valid_authority(tmp_path)
    _write(
        tmp_path,
        "src/hl_observer/strategies/active_scope.py",
        """_SCOPE = (
    StrategyScopeEntry("copy_vault", StrategyScopeStatus.ACTIVE, True, "active"),
    StrategyScopeEntry("lead_lag", StrategyScopeStatus.ACTIVE, True, "must stay disabled"),
)
""",
    )

    issues = audit_document_authority(tmp_path)

    assert "ACTIVE_SCOPE_MISMATCH" in {issue.code for issue in issues}
