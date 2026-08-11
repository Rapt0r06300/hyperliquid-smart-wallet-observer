from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "tools" / "start_hypersmart_simulation.ps1"


def _function_body(text: str, name: str) -> str:
    marker = f"function {name} "
    start = text.index(marker)
    next_function = text.find("\nfunction ", start + len(marker))
    return text[start:] if next_function < 0 else text[start:next_function]


def test_runtime_process_cleanup_is_scoped_to_current_checkout_and_excludes_health_monitor():
    text = PS1.read_text(encoding="utf-8", errors="replace")
    assert "function Test-HyperSmartProcessBelongsToRoot" in text
    body = _function_body(text, "Get-HyperSmartRuntimeProcesses")
    assert "Test-HyperSmartProcessBelongsToRoot" in body
    assert "moniteur_sante" in body
    assert "MONITEUR_SANTE_PRESERVE" in body
    assert "$ProjectRoot" not in text, "undefined root alias can break verified port-owner checks"


def test_collector_loop_shutdown_never_matches_another_checkout():
    text = PS1.read_text(encoding="utf-8", errors="replace")
    body = _function_body(text, "Stop-HyperSmartRuntime")
    assert "boucle_collecteur" in body
    assert "Test-HyperSmartProcessBelongsToRoot" in body
    assert "Refusing to stop foreign collector loop" in body


def test_broad_hlobserver_signatures_are_never_sufficient_ownership_proof():
    text = PS1.read_text(encoding="utf-8", errors="replace")
    body = _function_body(text, "Get-HyperSmartRuntimeProcesses")
    assert "*python*hl_observer*" in body  # compatibility signature may remain
    assert "*-m hl_observer*" in body
    # But the candidate must first prove checkout ownership; signature alone can
    # never authorize a kill/restart.
    assert body.index("Test-HyperSmartProcessBelongsToRoot") < body.index("*python*hl_observer*")
