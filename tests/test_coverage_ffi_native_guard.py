from __future__ import annotations

from hl_observer.backtesting.runtime_guards import _existe_sous_windows
from tests import coverage_contract_harness as harness


def test_dummy_ne_simule_pas_les_protocoles_ctypes() -> None:
    dummy = harness.Dummy()
    for name in ("_as_parameter_", "_fields_", "_type_", "_length_"):
        assert not hasattr(dummy, name)


def test_fuzzer_fournit_un_pid_scalaire_aux_frontieres_natives(tmp_path) -> None:
    settings_sentinel = object()
    for name in ("pid", "ppid", "process_id", "parent_pid", "worker_pid"):
        assert harness._value(object, name, 1, tmp_path, settings_sentinel) == 1


def test_runtime_guard_refuse_un_pid_invalide_avant_ctypes() -> None:
    assert _existe_sous_windows(object()) is False
    assert _existe_sous_windows(0) is False
    assert _existe_sous_windows(-1) is False
