from __future__ import annotations

from pathlib import Path


SIMULATION_PAGE = Path("src/hl_observer/ui/static/simulation_v2.html")


def test_simulation_page_keeps_ledger_inside_normal_pnl_readout() -> None:
    page = SIMULATION_PAGE.read_text(encoding="utf-8", errors="replace")

    assert "function normalPnlLedgerReadout(status)" in page
    assert "paperLedgerFromStatus(status)" in page
    assert "Controle du PnL normal" in page
    assert "PnL normal = solde depart + encaisse + latent" in page
    assert "ledger_spike_links" in page
    assert "spike_links" in page
    assert "paper_ledger" in page


def test_simulation_page_does_not_create_a_separate_fake_ledger_panel() -> None:
    page = SIMULATION_PAGE.read_text(encoding="utf-8", errors="replace")

    assert "ledgerExplain" not in page
    assert "ledgercard" not in page
    assert "fake" not in page.lower()
    assert "/exchange" not in page
