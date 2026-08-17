from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest


PORTABLE_CONTRACT_ENV = "HYPERSMART_EXTRACTED_PORTABLE_TEST"
pytestmark = pytest.mark.skipif(
    os.environ.get(PORTABLE_CONTRACT_ENV) != "1",
    reason=(
        "Contrat réservé à l'archive Windows déjà extraite; "
        f"{PORTABLE_CONTRACT_ENV}=1 est posé uniquement par le workflow portable."
    ),
)

ROOT = Path.cwd().resolve()


def test_archive_extraite_possede_le_runtime_embarque_et_les_lanceurs() -> None:
    assert (ROOT / "tools" / "python" / "python.exe").is_file()
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
        assert importlib.import_module(module) is not None, module


def test_archive_extraite_ne_depend_pas_du_git_systeme_pour_demarrer() -> None:
    # Le runtime portable embarque son propre Git; le PATH hermétique peut donc
    # rester limité au runtime + composants Windows de base.
    embedded_git = ROOT / "tools" / "git" / "cmd" / "git.exe"
    assert embedded_git.is_file()
