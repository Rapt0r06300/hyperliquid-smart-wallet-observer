from __future__ import annotations

from hl_observer.release.quality_gates import GATE_OK, _runtime_write_gate_status
from hl_observer.runtime.write_diagnostics import RUNTIME_WRITE_OK


def test_runtime_write_ok_maps_to_quality_gate_ok() -> None:
    assert _runtime_write_gate_status(RUNTIME_WRITE_OK) == GATE_OK
