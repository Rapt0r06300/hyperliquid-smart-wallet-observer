from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


PORTABLE_CONTRACT_ENV = "HYPERSMART_EXTRACTED_PORTABLE_TEST"
ROOT = Path.cwd().resolve()


def _portable_contract_active() -> bool:
    if os.environ.get(PORTABLE_CONTRACT_ENV) == "1":
        return True
    raw_root = os.environ.get("HYPERSMART_RUNTIME_ROOT", "").strip()
    if not raw_root:
        return False
    try:
        runtime_root = Path(raw_root).resolve()
        executable = Path(sys.executable).resolve()
    except OSError:
        return False
    return bool(
        os.name == "nt"
        and runtime_root == ROOT
        and executable == (ROOT / "tools" / "python" / "python.exe").resolve()
        and (ROOT / "_validation_workspace").is_dir()
        and os.environ.get("PIP_NO_INDEX") == "1"
        and os.environ.get("PYTHONNOUSERSITE") == "1"
    )


pytestmark = pytest.mark.skipif(
    not _portable_contract_active(),
    reason=(
        "Contrat réservé à l'archive Windows réellement extraite et exécutée "
        "avec son Python embarqué."
    ),
)


def test_archive_extraite_possede_le_runtime_embarque_et_les_lanceurs() -> None:
    assert (ROOT / "tools" / "python" / "python.exe").is_file()
    assert Path(sys.executable).resolve() == (ROOT / "tools" / "python" / "python.exe").resolve()
    assert (ROOT / "PORTABLE_MANIFEST.json").is_file()
    for name in (
        "LANCER_HYPERSMART.cmd",
        "ANALYSER_BACKTESTS_REPLAYS.cmd",
        "CREER_ARCHIVE_PORTABLE.cmd",
    ):
        assert (ROOT / name).is_file(), name


def test_archive_extraite_est_forcee_paper_read_only() -> None:
    assert os.environ.get("HL_ENABLE_MAINNET_EXECUTION") == "0"
    assert os.environ.get("HL_ENABLE_TESTNET_EXECUTION") == "0"
    assert os.environ.get("REAL_MAINNET_TRADING", "").casefold() == "false"
    assert os.environ.get("TESTNET_EXECUTION_ENABLED", "").casefold() == "false"


def test_modules_portables_critiques_s_importent_depuis_l_archive() -> None:
    for module in (
        "hl_observer.ops.portable_clone",
        "hl_observer.ops.archive_portable",
        "hl_observer.ops.validation_portable",
        "hl_observer.backtesting.copy_vault_executable",
        "hyper_smart_observer.app.main",
    ):
        imported = importlib.import_module(module)
        assert imported is not None, module
        module_file = Path(getattr(imported, "__file__", "")).resolve()
        assert ROOT in module_file.parents, f"{module} importé hors archive: {module_file}"


def test_archive_extraite_ne_depend_pas_du_git_systeme_pour_demarrer() -> None:
    # Le runtime portable embarque son propre Git; le PATH hermétique peut donc
    # rester limité au runtime + composants Windows de base.
    embedded_git = ROOT / "tools" / "git" / "cmd" / "git.exe"
    assert embedded_git.is_file()
