from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "portable_runtime.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("hypersmart_portable_runtime", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_portability_files_exist_and_unified_launcher_bootstraps_first():
    assert (ROOT / "requirements-portable.txt").is_file()
    assert (ROOT / "tools" / "portable_env.cmd").is_file()
    assert (ROOT / "tools" / "install_portable_runtime.ps1").is_file()
    assert (ROOT / "tools" / "create_portable_bundle.ps1").is_file()
    assert (ROOT / "docs" / "PORTABILITE_WINDOWS.md").is_file()
    # item 2/3 : point d'entree utilisateur pour assembler le Python embarque + wheelhouse hors ligne.
    assert (ROOT / "tools" / "preparer_python_portable.cmd").is_file()
    assert (ROOT / "PREPARER_GIT_PORTABLE.cmd").is_file()
    assert (ROOT / "tools" / "git" / "cmd" / "git.exe").is_file()
    assert (ROOT / "POUSSER-GITHUB-FORCE.cmd").is_file()
    assert (ROOT / "ANALYSER_BACKTESTS_REPLAYS.cmd").is_file()

    launcher = (ROOT / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8")
    # item 4 : le lanceur bootstrappe portable_env.cmd AVANT toute invocation de Python, et n'utilise
    # QUE le Python portable place en tete du PATH, jamais un `py -3` du PATH.
    bootstrap_index = launcher.index("portable_env.cmd")
    first_python_index = launcher.index("python", bootstrap_index + len("portable_env.cmd"))
    assert bootstrap_index < first_python_index
    assert "py -3" not in launcher                          # jamais le lanceur Windows global
    assert "if errorlevel 1" in launcher[bootstrap_index:bootstrap_index + 400]  # errorlevel verifie

    raw_launcher = (ROOT / "LANCER_HYPERSMART.cmd").read_bytes()
    assert b"\x00" not in raw_launcher


def test_python_selection_prefers_embedded_runtime(tmp_path):
    module = _load_module()
    embedded = tmp_path / "tools" / "python" / "python.exe"
    embedded.parent.mkdir(parents=True)
    embedded.write_bytes(b"MZ")
    system = tmp_path / "system-python.exe"
    system.write_bytes(b"MZ")

    selection = module.select_python(tmp_path, path_candidates=[str(system)])

    assert selection is not None
    assert selection.portable is True
    assert selection.source == "embedded-tools-python"
    assert Path(selection.executable) == embedded.resolve()


def test_bundle_member_policy_excludes_active_runtime_and_secrets():
    module = _load_module()
    rejected = (
        ".git/config",
        "runtime/data/live.sqlite3",
        "data/leaderboard.db",
        "logs/live.log",
        ".env",
        "nested/.env",
        "cache/__pycache__/x.pyc",
        "archive.zip",
        "portable_runtime/python_backup_20260728/python.exe",
        "portable_runtime/python_failed_20260728/python.exe",
    )
    accepted = (
        "src/hl_observer/__init__.py",
        "tools/start_hypersmart_simulation.ps1",
        "tools/python/python.exe",
        "tools/python/python314.zip",
        "tools/git/cmd/git.exe",
        ".env.example",
        "LANCER_HYPERSMART.cmd",
    )
    assert all(not module.is_safe_bundle_member(path) for path in rejected)
    assert all(module.is_safe_bundle_member(path) for path in accepted)


def test_legacy_runtime_migration_is_non_destructive(tmp_path):
    module = _load_module()
    legacy = tmp_path / "portable_runtime" / "python"
    legacy.mkdir(parents=True)
    (legacy / "python.exe").write_bytes(b"MZ")
    (legacy / "python314.dll").write_bytes(b"DLL")

    result = module.migrate_legacy_runtime(tmp_path)

    assert result["migrated"] is True
    assert (tmp_path / "tools" / "python" / "python.exe").read_bytes() == b"MZ"
    assert (legacy / "python.exe").is_file()


def test_bundle_builder_is_staged_external_and_requires_embedded_python():
    text = (ROOT / "tools" / "create_portable_bundle.ps1").read_text(encoding="utf-8")
    assert "GetFolderPath(\"Desktop\")" in text
    assert "Portable bundles must be created outside the project" in text
    assert "hypersmart-bundle-" in text
    assert "check --require-embedded" in text
    assert "LANCER_HYPERSMART.cmd" in text
    assert "active_runtime_included = $false" in text
    assert "CreateFromDirectory" in text
    assert "Remove-GeneratedPythonCaches" in text
    assert '$n.Contains("/__pycache__/")' in text
    assert '$n.EndsWith(".pyc")' in text
    assert 'tools\\python\\python.exe' in text
    assert 'embedded_python = "tools/python/python.exe"' in text
    assert '"tools/python/portable_runtime_manifest.json"' in text
    assert '"portable_runtime/python/python.exe"' not in text
    portable_env = (ROOT / "tools" / "portable_env.cmd").read_text(encoding="utf-8")
    assert "tools\\python\\python.exe" in portable_env
    assert ".venv-portable" not in portable_env
    assert "where python" not in portable_env.lower()


def test_runtime_installer_pins_official_cpython_and_validates_hash():
    text = (ROOT / "tools" / "install_portable_runtime.ps1").read_text(encoding="utf-8")
    assert "https://www.python.org/ftp/python/" in text
    assert "python-$PythonVersion-embed-amd64.zip" in text
    assert "F05E28D161C6B15AF64A7CB7F08B4A22B3A6B03EEE71BAEE24EA557B3BDD5798" in text
    assert "Get-FileHash -Algorithm SHA256" in text
    assert "requirements-portable.txt" in text
    assert "portable_runtime_manifest.json" in text
    assert "tools\\wheelhouse" in text
    assert "--no-index" in text
    assert "--find-links" in text
    assert "--require-hashes" in text
    assert "--only-binary=:all:" in text
    assert "--ignore-installed" in text
    assert "get-pip.py" not in text
    assert "import site" not in text
    assert "requirements_sha256" in text
    assert "wheelhouse_lock_sha256" in text
    assert "isolated_from_user_site" in text


def test_portable_probe_rejects_external_python_paths(tmp_path):
    module = _load_module()
    payload = module.probe_python(Path(sys.executable))
    assert "external_path_leaks" in payload
    assert isinstance(payload["external_path_leaks"], list)


def test_real_embedded_runtime_status_is_complete_and_not_none():
    module = _load_module()

    status = module.runtime_status(ROOT, require_embedded=True)

    assert status is not None
    assert status.probe_ok is True
    assert status.selected_source == "embedded-tools-python"
    assert status.missing_imports == ()
    assert status.external_path_leaks == ()


def test_real_folder_is_relocatable_without_building_an_archive():
    module = _load_module()

    status = module.relocation_status(ROOT)

    assert status.ok is True
    assert status.embedded_runtime_ok is True
    assert status.relative_launcher_ok is True
    assert status.relative_python_paths_ok is True
    assert status.first_launch_regeneration_ok is True
    assert status.required_files_missing == ()
    assert status.hardcoded_user_paths == ()


def test_real_windows_launcher_can_dispatch_portable_check():
    if os.name != "nt":
        return
    completed = subprocess.run(
        f'call "{ROOT / "LANCER_HYPERSMART.cmd"}" portable-check',
        shell=True,
        executable=os.environ.get("COMSPEC", "cmd.exe"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 0, combined
    assert '"portable_python_exists": true' in combined
    assert '"selected_source": "embedded-tools-python"' in combined
    assert '"missing_imports": []' in combined
    assert "PORTABLE_LAUNCHER_CHECK_OK" in combined


def test_new_portability_files_have_no_user_specific_absolute_path():
    paths = (
        ROOT / "requirements-portable.txt",
        ROOT / "tools" / "portable_runtime.py",
        ROOT / "tools" / "portable_env.cmd",
        ROOT / "tools" / "install_portable_runtime.ps1",
        ROOT / "tools" / "create_portable_bundle.ps1",
        ROOT / "docs" / "PORTABILITE_WINDOWS.md",
        ROOT / "tools" / "install_portable_git.ps1",
        ROOT / "PREPARER_GIT_PORTABLE.cmd",
        ROOT / "POUSSER-GITHUB-FORCE.cmd",
        ROOT / "ANALYSER_BACKTESTS_REPLAYS.cmd",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users\\flo" not in text
