from __future__ import annotations

from pathlib import Path

from hl_observer.ops.entrypoint_topology import (
    ENTRYPOINT_ROLES,
    OFFICIAL_ENTRYPOINTS,
    EntrypointRole,
    audit_entrypoint_topology,
    render_entrypoint_topology_report,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _official_content(extra: str = "") -> str:
    return "\n".join(
        [
            '@echo off',
            'call "%~dp0tools\\portable_env.cmd"',
            'set "HL_ENABLE_MAINNET_EXECUTION=0"',
            'set "HL_ENABLE_TESTNET_EXECUTION=0"',
            '"%HYPERSMART_PYTHON%" -V',
            extra,
        ]
    )


def _seed_registered_launchers(root: Path) -> None:
    for path in ENTRYPOINT_ROLES:
        _write(root / path, "@echo off\n")
    _write(root / OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RUNTIME], _official_content("port_owner"))
    _write(root / OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_ANALYSIS], _official_content("analysis"))
    _write(
        root / OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RESEARCH],
        _official_content("tools\\recherche_continue.py"),
    )
    _write(root / "CREER_ARCHIVE_PORTABLE.cmd", _official_content("portable archive"))


def test_current_repository_entrypoint_topology_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    issues = audit_entrypoint_topology(root)
    assert render_entrypoint_topology_report(issues) == "ENTRYPOINT_TOPOLOGY=PASS"


def test_unclassified_root_cmd_fails_closed(tmp_path: Path) -> None:
    _seed_registered_launchers(tmp_path)
    _write(tmp_path / "NEW_UNREGISTERED.cmd", "@echo off\n")

    issues = audit_entrypoint_topology(tmp_path)

    assert any(issue.code == "UNCLASSIFIED_ENTRYPOINT" for issue in issues)


def test_official_research_rejects_system_python_fallback(tmp_path: Path) -> None:
    _seed_registered_launchers(tmp_path)
    path = tmp_path / OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RESEARCH]
    _write(path, _official_content("tools\\recherche_continue.py\npython bad.py"))

    issues = audit_entrypoint_topology(tmp_path)

    assert any(issue.code == "SYSTEM_PYTHON_FALLBACK" for issue in issues)


def test_official_research_rejects_server_duplication(tmp_path: Path) -> None:
    _seed_registered_launchers(tmp_path)
    path = tmp_path / OFFICIAL_ENTRYPOINTS[EntrypointRole.OFFICIAL_RESEARCH]
    _write(path, _official_content("tools\\recherche_continue.py\nhl_observer.cli run"))

    issues = audit_entrypoint_topology(tmp_path)

    assert any(issue.code == "RESEARCH_SERVER_DUPLICATION" for issue in issues)
