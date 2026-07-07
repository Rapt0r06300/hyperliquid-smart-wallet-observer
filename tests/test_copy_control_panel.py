from hl_observer.copy_wallet.copy_session_controller import start_copy_session
from hl_observer.dashboard.copy_control_panel import build_copy_control_panel


def test_copy_control_panel_is_read_only_payload():
    panel = build_copy_control_panel(start_copy_session("s1", watchlist=("0x1",)))
    assert panel["status"] == "RUNNING"
    assert panel["paper_only"] is True
    assert panel["real_execution"] is False
