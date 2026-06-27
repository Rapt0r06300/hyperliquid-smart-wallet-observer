from __future__ import annotations

from hl_observer.ui.app import SMOOTH_METAGRAPH_SCRIPT, _inject_smooth_metagraph_script


def test_smooth_metagraph_loader_targets_v2() -> None:
    assert "metagraph_smooth_v2.js" in SMOOTH_METAGRAPH_SCRIPT


def test_smooth_metagraph_loader_fallback_injects_once() -> None:
    html = "<html><body>ok</body></html>"
    loaded = _inject_smooth_metagraph_script(html)
    loaded_again = _inject_smooth_metagraph_script(loaded)

    assert "metagraph_smooth_v2.js" in loaded
    assert loaded_again.count("metagraph_smooth") == 1
