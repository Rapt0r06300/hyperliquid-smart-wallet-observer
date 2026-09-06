from hl_observer.explorer.explorer_transaction_tape import format_explorer_tape


def test_format_explorer_tape_explains_empty_result() -> None:
    rendered = format_explorer_tape([])
    assert rendered.splitlines() == [
        "explorer transaction tape",
        "transactions: 0",
        "Explorer inspecte, mais aucune transaction structuree exploitable n'a ete extraite automatiquement.",
    ]


def test_format_explorer_tape_renders_populated_row_with_fallbacks() -> None:
    rendered = format_explorer_tape(
        [{"tx_hash": "0xabc", "wallet_address": "0xwallet", "coin": None, "status": "OBSERVED"}]
    )
    assert rendered.splitlines() == [
        "explorer transaction tape",
        "transactions: 1",
        "- 0xabc wallet=0xwallet coin=- status=OBSERVED",
    ]
